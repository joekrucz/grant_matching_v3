import time
import re
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

from app.utils.hashing import sha256_for_grant
from app.utils.normalisation import parse_deadline
from app.utils.http_client import create_session, fetch_with_retry


def scrape_ukri(existing_grants: Dict[str, Dict[str, Any]] = None) -> List[Dict[str, Any]]:
  """
  Scrape UKRI funding opportunities from https://www.ukri.org/opportunity/
  Handles pagination to get all opportunities.
  
  Args:
    existing_grants: Dict of existing grants keyed by URL, to help optimize scraping.
                     Format: {url: {hash_checksum: "...", slug: "...", title: "..."}}
  """
  if existing_grants is None:
    existing_grants = {}
  
  grants: List[Dict[str, Any]] = []
  base_url = "https://www.ukri.org/opportunity/"
  seen_urls = set()
  
  session = create_session()
  
  existing_count = len(existing_grants)
  if existing_count > 0:
    print(f"Found {existing_count} existing UKRI grants in database")
  
  try:
    # Collect all opportunity URLs from all pages
    all_opportunity_urls = []
    page = 1
    max_pages = 20  # Safety limit
    
    while page <= max_pages:
      # UKRI uses /page/2/ format for pagination
      if page == 1:
        url = base_url
      else:
        url = f"{base_url}page/{page}/"
      
      try:
        print(f"Fetching UKRI opportunities page {page} from {url}...")
        resp = fetch_with_retry(session, url, timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # UKRI uses specific class for opportunity links: ukri-funding-opp__link
        opportunity_links = soup.select("a.ukri-funding-opp__link")
        
        new_urls_on_page = 0
        for link in opportunity_links:
          href = link.get("href", "")
          if not href:
            continue
          if href.startswith("/"):
            href = f"https://www.ukri.org{href}"
          elif not href.startswith("http"):
            continue
          
          # Skip if it's a pagination link or not an actual opportunity page
          if "/page/" in href or href == base_url or not "/opportunity/" in href:
            continue
          
          if href not in seen_urls:
            seen_urls.add(href)
            title = link.get_text(strip=True)
            if title and len(title) > 5:  # Minimum title length
              all_opportunity_urls.append((title, href))
              new_urls_on_page += 1
        
        if new_urls_on_page > 0:
          print(f"  Page {page}: Found {new_urls_on_page} new opportunities (total: {len(all_opportunity_urls)})")
          # Continue to next page
          page += 1
          time.sleep(1)  # Throttle between pages
        else:
          # No opportunities found on this page, we've reached the end
          print(f"  Page {page}: No opportunities found, reached end of pagination")
          break
      except Exception as e:
        print(f"Error fetching page {page} ({url}): {e}")
        # If it's page 1 and we have some opportunities, continue
        # Otherwise, stop
        if page == 1 and len(all_opportunity_urls) > 0:
          page += 1
          continue
        else:
          break
    
    print(f"Found {len(all_opportunity_urls)} total UKRI opportunities across {page - 1} page(s)")
    
    # Process all collected opportunity URLs
    print(f"Processing {len(all_opportunity_urls)} UKRI opportunities...")
    new_count = 0
    existing_count_in_listing = 0
    
    for idx, (title, url) in enumerate(all_opportunity_urls, 1):
      if idx % 10 == 0:
        print(f"  Processing opportunity {idx}/{len(all_opportunity_urls)} (new: {new_count}, existing: {existing_count_in_listing})")
      
      # Check if this grant already exists
      is_existing = url in existing_grants
      if is_existing:
        existing_count_in_listing += 1
      else:
        new_count += 1
      
      time.sleep(1)  # Throttle between requests
      try:
        detail_resp = fetch_with_retry(session, url, referer=base_url, timeout=30)
        detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
        
        # Extract description and structured sections
        desc_el = (
            detail_soup.select_one("main") or
            detail_soup.select_one(".content") or
            detail_soup.select_one("article") or
            detail_soup.select_one("div[class*='description']")
        )
        description = desc_el.get_text("\n", strip=True) if desc_el else ""
        
        # Extract structured sections from detail page
        sections = {}
        summary_from_sections = None
        
        if desc_el:
          # Look for headings (h2, h3) to identify sections
          headings = desc_el.find_all(["h2", "h3"])
          current_section = None
          current_content = []
          
          # Process all elements in the description area
          for element in desc_el.descendants:
            if element.name in ["h2", "h3"]:
              # Save previous section
              if current_section and current_content:
                sections[current_section] = "\n".join(current_content).strip()
              # Start new section
              heading_text = element.get_text(strip=True).lower()
              current_section = None
              
              # Identify section type by heading text
              if any(word in heading_text for word in ["overview", "summary", "introduction", "about", "background"]):
                current_section = "overview"
              elif any(word in heading_text for word in ["eligibility", "who can apply", "who is eligible", "who should apply"]):
                current_section = "eligibility"
              elif any(word in heading_text for word in ["funding", "budget", "cost", "financial", "value"]):
                current_section = "funding"
              elif any(word in heading_text for word in ["application", "how to apply", "apply", "submission", "submitting"]):
                current_section = "how_to_apply"
              elif any(word in heading_text for word in ["deadline", "closing", "dates", "timeline", "schedule", "key dates"]):
                current_section = "dates"
              elif any(word in heading_text for word in ["assessment", "evaluation", "review", "criteria", "selection"]):
                current_section = "assessment"
              elif any(word in heading_text for word in ["contact", "enquiries", "questions", "further information"]):
                current_section = "contact"
              elif any(word in heading_text for word in ["terms", "conditions", "requirements", "guidance"]):
                current_section = "terms"
              elif any(word in heading_text for word in ["scope", "aims", "objectives"]):
                current_section = "scope"
              else:
                # Use heading as section name (normalized)
                current_section = heading_text.replace(" ", "_").replace("-", "_")[:50]
              current_content = []
            elif element.name in ["p", "div", "li", "ul", "ol"] and current_section:
              text = element.get_text(strip=True)
              if text and len(text) > 10:  # Skip very short text (likely navigation)
                current_content.append(text)
          
          # Save last section
          if current_section and current_content:
            sections[current_section] = "\n".join(current_content).strip()
          
          # If no sections found via headings, try to split by common patterns
          if not sections and description:
            # Try to identify sections by common UKRI page patterns
            # Look for bold text or strong elements that might be section headers
            strong_elements = desc_el.find_all(["strong", "b"])
            if strong_elements:
              current_section = None
              current_content = []
              for element in desc_el.descendants:
                if element.name in ["strong", "b"]:
                  strong_text = element.get_text(strip=True).lower()
                  if len(strong_text) > 5 and len(strong_text) < 50:
                    # Might be a section header
                    if current_section and current_content:
                      sections[current_section] = "\n".join(current_content).strip()
                    # Check if it matches known section patterns
                    if any(word in strong_text for word in ["overview", "summary"]):
                      current_section = "overview"
                    elif any(word in strong_text for word in ["eligibility"]):
                      current_section = "eligibility"
                    elif any(word in strong_text for word in ["funding", "budget"]):
                      current_section = "funding"
                    elif any(word in strong_text for word in ["application", "apply"]):
                      current_section = "how_to_apply"
                    else:
                      current_section = strong_text.replace(" ", "_")[:50]
                    current_content = []
                elif element.name in ["p", "div"] and current_section:
                  text = element.get_text(strip=True)
                  if text and len(text) > 10:
                    current_content.append(text)
              
              if current_section and current_content:
                sections[current_section] = "\n".join(current_content).strip()
            
            # If still no sections, use first paragraph as overview
            if not sections and description:
              # Split description into paragraphs
              paragraphs = [p.strip() for p in description.split("\n") if p.strip() and len(p.strip()) > 20]
              if paragraphs:
                sections["overview"] = "\n\n".join(paragraphs[:3])  # First 3 paragraphs as overview
                if len(paragraphs) > 3:
                  sections["additional_information"] = "\n\n".join(paragraphs[3:])
                summary_from_sections = paragraphs[0][:200] + "..." if len(paragraphs[0]) > 200 else paragraphs[0]
        
        # Extract summary from meta description or first section
        summary_el = detail_soup.select_one("meta[name='description']")
        if summary_el and summary_el.get("content"):
          summary = summary_el["content"]
        elif summary_from_sections:
          summary = summary_from_sections
        elif sections.get("overview"):
          overview_text = sections["overview"]
          summary = overview_text[:200] + "..." if len(overview_text) > 200 else overview_text
        else:
          summary = description[:200] + "..." if len(description) > 200 else description
        
        # Extract dates and content from opportunity__summary section (priority method)
        deadline_raw = None
        opening_date_raw = None
        summary_content = {}
        closing_date_found = False  # Flag to track if we've processed the closing date field
        
        # First, try to extract from the structured dl.opportunity__summary format
        summary_dl = detail_soup.select_one("dl.govuk-table.opportunity__summary, dl.opportunity__summary")
        if summary_dl:
          # Extract all dt/dd pairs from the definition list
          dt_elements = summary_dl.find_all("dt")
          for dt in dt_elements:
            dt_text = dt.get_text(strip=True)
            dd = dt.find_next_sibling("dd")
            if dd:
              dd_text = dd.get_text(strip=True)
              
              # Store all summary fields
              summary_content[dt_text] = dd_text
              
              # Check for opening date - exact match for "Opening date:"
              dt_text_lower = dt_text.lower().strip()
              
              if dt_text_lower == "opening date:" or dt_text_lower == "opening date":
                opening_date_raw = dd_text
              # Check for closing date - exact match for "Closing date:"
              elif dt_text_lower == "closing date:" or dt_text_lower == "closing date":
                closing_date_found = True  # Mark that we found the closing date field
                # Check if it's "Open - no closing date" or similar
                dd_text_lower = dd_text.lower().strip()
                if "no closing date" in dd_text_lower or "open - no closing date" in dd_text_lower or dd_text_lower == "open":
                  # This is an open grant with no closing date
                  deadline_raw = None  # Explicitly set to None
                else:
                  deadline_raw = dd_text
        
        # Fallback to regex patterns if structured format not found
        page_text = detail_soup.get_text()  # Get page text for fallback and other extractions
        # Only use fallback if we haven't found the closing date field yet, or if we found it but it wasn't "no closing date"
        if (not closing_date_found and not deadline_raw) or not opening_date_raw:
            # Only search for missing dates
            # Don't search for deadline if we explicitly found "no closing date"
            if not deadline_raw and not closing_date_found:
        deadline_patterns = [
            r"deadline[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"closing[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"(\d{1,2}\s+\w+\s+\d{2,4})",
            r"closes?\s+(\d{1,2}\s+\w+\s+\d{2,4})",
        ]
        for pattern in deadline_patterns:
          match = re.search(pattern, page_text, re.IGNORECASE)
          if match:
            deadline_raw = match.group(1)
            break
            
            if not opening_date_raw:
                opening_patterns = [
                    r"opening[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                    r"opens[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                    r"opening[:\s]+(\d{1,2}\s+\w+\s+\d{2,4})",
                    r"opens[:\s]+(\d{1,2}\s+\w+\s+\d{2,4})",
                ]
                for pattern in opening_patterns:
                    match = re.search(pattern, page_text, re.IGNORECASE)
                    if match:
                        opening_date_raw = match.group(1)
                        break
        
        # Extract funding amount
        funding_amount = None
        funding_patterns = [
            r"£[\d,]+",
            r"funding[:\s]+£?([\d,]+)",
            r"up to £?([\d,]+)",
            r"maximum[:\s]+£?([\d,]+)",
        ]
        for pattern in funding_patterns:
          match = re.search(pattern, page_text, re.IGNORECASE)
          if match:
            funding_amount = f"£{match.group(1) if match.groups() else match.group(0)}"
            break
        
        # Format description with section headings for better readability
        formatted_description = description
        if sections:
          # Build formatted description with clear section headings
          formatted_parts = []
          section_order = ["overview", "scope", "eligibility", "funding", "how_to_apply", "dates", "assessment", "contact", "terms"]
          
          for section_key in section_order:
            if section_key in sections:
              section_title = section_key.replace("_", " ").title()
              formatted_parts.append(f"## {section_title}\n\n{sections[section_key]}")
          
          # Add any remaining sections not in the standard order
          for section_key, section_content in sections.items():
            if section_key not in section_order:
              section_title = section_key.replace("_", " ").title()
              formatted_parts.append(f"## {section_title}\n\n{section_content}")
          
          if formatted_parts:
            formatted_description = "\n\n".join(formatted_parts)
        
        grant: Dict[str, Any] = {
            "source": "ukri",
            "title": title,
            "url": url,
            "summary": summary,
            "description": formatted_description,
            "deadline": parse_deadline(deadline_raw) if deadline_raw else None,
            "opening_date": parse_deadline(opening_date_raw) if opening_date_raw else None,
            "funding_amount": funding_amount,
            "status": "unknown",  # Status is computed from dates, not stored
            "raw_data": {
                "listing_url": base_url,
                "scraped_url": url,
                "sections": sections if sections else None,
                "opportunity_summary": summary_content if summary_content else None
            },
        }
        grant["hash_checksum"] = sha256_for_grant(grant)
        grants.append(grant)
        
        if idx % 10 == 0:
          print(f"  Processed {idx}/{len(all_opportunity_urls)} opportunities...")
      except Exception as e:
        print(f"Error scraping UKRI opportunity {url}: {e}")
        continue
    
    print(f"Successfully scraped {len(grants)} UKRI opportunities")
    print(f"  - New grants found: {new_count}")
    print(f"  - Existing grants re-checked: {existing_count_in_listing}")
    print(f"  - Note: Django will skip unchanged grants based on hash_checksum comparison")
    return grants
    
  except Exception as e:
    error_msg = f"UKRI scraper failed: {str(e)}"
    print(error_msg)
    raise Exception(error_msg) from e

