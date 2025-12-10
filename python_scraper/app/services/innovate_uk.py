import time
import re
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

from app.utils.hashing import sha256_for_grant
from app.utils.normalisation import parse_deadline
from app.utils.http_client import create_session, fetch_with_retry


def scrape_innovate_uk(existing_grants: Dict[str, Dict[str, Any]] = None) -> List[Dict[str, Any]]:
  """
  Scrape Innovate UK funding competitions from https://apply-for-innovation-funding.service.gov.uk/competition/search
  
  Args:
    existing_grants: Dict of existing grants keyed by URL, to help optimize scraping.
                     Format: {url: {hash_checksum: "...", slug: "...", title: "..."}}
  """
  if existing_grants is None:
    existing_grants = {}
  
  grants: List[Dict[str, Any]] = []
  base_url = "https://apply-for-innovation-funding.service.gov.uk/competition/search"
  
  session = create_session()
  
  existing_count = len(existing_grants)
  if existing_count > 0:
    print(f"Found {existing_count} existing Innovate UK grants in database")
  
  try:
    # Collect all competition URLs
    seen_urls = set()
    all_competition_urls = []
    page = 1
    max_pages = 50  # Safety limit
    
    while page <= max_pages:
      # The search page uses pagination - check if there's a page parameter
      if page == 1:
        url = base_url
      else:
        url = f"{base_url}?page={page}"
      
      try:
        print(f"Fetching Innovate UK competitions page {page} from {url}...")
        resp = fetch_with_retry(session, url, timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Find competition links - they typically link to /competition/ pages
        # Look for links that contain '/competition/' in the href
        competition_links = soup.select("a[href*='/competition/']")
        
        new_urls_on_page = 0
        for link in competition_links:
          href = link.get("href", "")
          if not href:
            continue
          
          # Normalize URL
          if href.startswith("/"):
            href = f"https://apply-for-innovation-funding.service.gov.uk{href}"
          elif not href.startswith("http"):
            continue
          
          # Skip if it's the search page itself or pagination
          if "/competition/search" in href or "?page=" in href:
            continue
          
          # Only include actual competition detail pages
          if "/competition/" not in href or href == base_url:
            continue
          
          if href not in seen_urls:
            seen_urls.add(href)
            # Try to get title from link text or nearby heading
            title = link.get_text(strip=True)
            if not title or len(title) < 5:
              # Try to find a heading nearby
              parent = link.find_parent(["article", "div", "li", "section", "h2", "h3"])
              if parent:
                heading = parent.find(["h2", "h3", "h4"])
                if heading:
                  title = heading.get_text(strip=True)
            
            if title and len(title) > 5:
              all_competition_urls.append((title, href))
              new_urls_on_page += 1
        
        if new_urls_on_page > 0:
          print(f"  Page {page}: Found {new_urls_on_page} new competitions (total: {len(all_competition_urls)})")
          page += 1
          time.sleep(1)  # Throttle between pages
        else:
          # No competitions found on this page, we've reached the end
          print(f"  Page {page}: No competitions found, reached end of pagination")
          break
      except Exception as e:
        print(f"Error fetching page {page} ({url}): {e}")
        if page == 1 and len(all_competition_urls) > 0:
          page += 1
          continue
        else:
          break
    
    print(f"Found {len(all_competition_urls)} total Innovate UK competitions across {page - 1} page(s)")
    
    # Process all collected competition URLs
    print(f"Processing {len(all_competition_urls)} Innovate UK competitions...")
    new_count = 0
    existing_count_in_listing = 0
    
    for idx, (title, url) in enumerate(all_competition_urls, 1):
      if idx % 10 == 0:
        print(f"  Processing competition {idx}/{len(all_competition_urls)} (new: {new_count}, existing: {existing_count_in_listing})")
      
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
            detail_soup.select_one("div[class*='description']") or
            detail_soup.select_one("div[class*='competition']")
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
              elif any(word in heading_text for word in ["deadline", "closing", "dates", "timeline", "schedule", "key dates", "opens", "closes"]):
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
              if text and len(text) > 10:  # Skip very short text
                current_content.append(text)
          
          # Save last section
          if current_section and current_content:
            sections[current_section] = "\n".join(current_content).strip()
          
          # If no sections found via headings, try to split by common patterns
          if not sections and description:
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
        
        # Extract deadline - look for "Opens:" and "Closes:" patterns
        deadline_raw = None
        page_text = detail_soup.get_text()
        
        # Look for "Closes:" or "Closes on:" patterns
        deadline_patterns = [
            r"closes?[:\s]+(\d{1,2}\s+\w+\s+\d{2,4})",
            r"closing[:\s]+(\d{1,2}\s+\w+\s+\d{2,4})",
            r"deadline[:\s]+(\d{1,2}\s+\w+\s+\d{2,4})",
            r"closes?[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"closing[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"deadline[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        ]
        
        for pattern in deadline_patterns:
          match = re.search(pattern, page_text, re.IGNORECASE)
          if match:
            deadline_raw = match.group(1)
            break
        
        # Also check for structured date elements
        if not deadline_raw:
          # Look for date elements in the page
          date_elements = detail_soup.select("time, [datetime], .date, .deadline")
          for date_el in date_elements:
            date_text = date_el.get("datetime") or date_el.get_text(strip=True)
            if date_text and ("close" in date_el.get_text().lower() or "deadline" in date_el.get_text().lower()):
              deadline_raw = date_text
              break
        
        # Extract funding amount
        funding_amount = None
        funding_patterns = [
            r"£[\d,]+",
            r"funding[:\s]+£?([\d,]+)",
            r"up to £?([\d,]+)",
            r"maximum[:\s]+£?([\d,]+)",
            r"share of up to £?([\d,]+)",
            r"a share of up to £?([\d,]+)",
        ]
        for pattern in funding_patterns:
          match = re.search(pattern, page_text, re.IGNORECASE)
          if match:
            funding_amount = f"£{match.group(1) if match.groups() else match.group(0).replace('£', '')}"
            break
        
        # Determine status - look for "Open now", "Closing soon", "Closed" indicators
        status = "unknown"
        status_text = page_text.lower()
        if "open now" in status_text or "opened:" in status_text:
          status = "open"
        elif "closing soon" in status_text:
          status = "open"
        elif "closed" in status_text and "closing" not in status_text:
          status = "closed"
        
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
            "source": "innovate_uk",
            "title": title,
            "url": url,
            "summary": summary,
            "description": formatted_description,
            "deadline": parse_deadline(deadline_raw) if deadline_raw else None,
            "funding_amount": funding_amount,
            "status": status,
            "raw_data": {
                "listing_url": base_url,
                "scraped_url": url,
                "sections": sections if sections else None
            },
        }
        grant["hash_checksum"] = sha256_for_grant(grant)
        grants.append(grant)
        
        if idx % 10 == 0:
          print(f"  Processed {idx}/{len(all_competition_urls)} competitions...")
      except Exception as e:
        print(f"Error scraping Innovate UK competition {url}: {e}")
        continue
    
    print(f"Successfully scraped {len(grants)} Innovate UK competitions")
    print(f"  - New grants found: {new_count}")
    print(f"  - Existing grants re-checked: {existing_count_in_listing}")
    print(f"  - Note: Django will skip unchanged grants based on hash_checksum comparison")
    return grants
    
  except Exception as e:
    error_msg = f"Innovate UK scraper failed: {str(e)}"
    print(error_msg)
    raise Exception(error_msg) from e

