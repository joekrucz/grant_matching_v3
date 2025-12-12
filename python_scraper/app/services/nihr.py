import time
import re
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

from app.utils.hashing import sha256_for_grant
from app.utils.normalisation import parse_deadline
from app.utils.http_client import create_session, fetch_with_retry


def scrape_nihr(existing_grants: Dict[str, Dict[str, Any]] = None) -> List[Dict[str, Any]]:
  """
  Scrape NIHR funding calls from https://www.nihr.ac.uk/researchers/funding-opportunities/
  
  Note: NIHR also provides an Open Data API at https://nihr.opendatasoft.com/
  Consider using the API for more reliable data access.
  
  Args:
    existing_grants: Dict of existing grants keyed by URL, to help optimize scraping.
                     Format: {url: {hash_checksum: "...", slug: "...", title: "..."}}
  """
  if existing_grants is None:
    existing_grants = {}
  
  grants: List[Dict[str, Any]] = []
  listing_url = "https://www.nihr.ac.uk/researchers/funding-opportunities/"
  
  session = create_session()
  # NIHR blocks some default clients; use a realistic browser User-Agent
  session.headers.update({
      "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      "Accept-Language": "en-GB,en;q=0.9",
  })
  
  existing_count = len(existing_grants)
  if existing_count > 0:
    print(f"Found {existing_count} existing NIHR grants in database")
  
  try:
    # NIHR lists funding opportunities with links to /funding/ pages
    # Look for links that point to specific funding opportunities
    seen_urls = set()
    all_opportunity_urls = []
    last_listing_error = None
    
    # Collect all opportunity URLs from all pages
    page = 1
    max_pages = 50  # Safety limit (there are 47 pages according to the site)
    
    while page <= max_pages:
      # NIHR uses ?page= parameter for pagination (page 1 is ?page=0, page 2 is ?page=1, etc.)
      if page == 1:
        url_to_fetch = listing_url
      else:
        url_to_fetch = f"{listing_url}?page={page - 1}"
      
        print(f"Fetching NIHR opportunities page {page} from {url_to_fetch}...")
      try:
        # Use browser-like headers to avoid 405
        headers = {
            "User-Agent": session.headers.get("User-Agent"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": session.headers.get("Accept-Language", "en-GB,en;q=0.9"),
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": listing_url,
        }
        resp = fetch_with_retry(session, url_to_fetch, timeout=30, headers=headers)
      except Exception as e:
        # Some NIHR pages return 405 to default clients; retry with direct session GET
        print(f"  Fetch_with_retry failed ({e}), retrying with direct session GET...")
        resp = session.get(url_to_fetch, timeout=30, headers=headers)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Method 1: Find links with /funding/ in the URL, or /node/ pages that might be grants
        funding_links = soup.select("a[href*='/funding/'], a[href*='/node/']")
        
        new_urls_on_page = 0
        for link in funding_links:
          href = link.get("href", "")
          if not href:
            continue
          if href.startswith("/"):
            href = f"https://www.nihr.ac.uk{href}"
          elif not href.startswith("http"):
            continue
          
          # Skip if it's the main funding opportunities page or pagination links
          if href == listing_url or "/funding-opportunities" in href or "?page=" in href:
            continue
          
          # For /node/ links, include them if they have numeric IDs (likely grant pages)
          # and are on the funding opportunities page
          if "/node/" in href and "/funding/" not in href:
            # Check if it's a numeric node ID (like /node/74786)
            node_match = re.search(r'/node/(\d+)', href)
            if node_match:
              # It's a numeric node ID, likely a grant page - include it
              # Try to get title from nearby heading or link context
              parent = link.find_parent(["article", "div", "li", "section", "main"])
              if parent:
                heading = parent.select_one("h2, h3, h4")
                if heading:
                  heading_text = heading.get_text(strip=True)
                  # Use heading if it looks like a grant title
                  if len(heading_text) > 15 and "filter" not in heading_text.lower():
                    # We'll use this heading text as the title
                    pass
            else:
              # Not a numeric node ID, skip it
              continue
          
          # Skip if we've seen this URL
          if href in seen_urls:
            continue
          seen_urls.add(href)
          
          # Get title from link text or nearby heading
          title = link.get_text(strip=True)
          
          # For /node/ links, the link text is often empty, so look for nearby heading
          if not title or len(title) < 10 or ("/node/" in href and "/funding/" not in href):
            # Try to find a nearby heading
            parent = link.find_parent(["article", "div", "li", "section", "main"])
            if parent:
              heading = parent.select_one("h2, h3, h4")
              if heading:
                heading_text = heading.get_text(strip=True)
                if len(heading_text) > 10:
                  title = heading_text
              # If still no title, check siblings
              if (not title or len(title) < 10) and parent:
                # Look for headings in the same parent
                all_headings = parent.select("h2, h3, h4")
                for h in all_headings:
                  h_text = h.get_text(strip=True)
                  if len(h_text) > 15 and "filter" not in h_text.lower() and "funding opportunities" not in h_text.lower():
                    title = h_text
                    break
          
          if title and len(title) > 10 and title.lower() not in ["find a funding opportunity", "our funding programmes", "funding opportunities", "next page", "current page"]:
            # Check if this grant has "Open" status by looking at the parent element
            parent = link.find_parent(["article", "div", "li", "section", "main"])
            status = "unknown"
            if parent:
              # Look for status indicators in the parent element
              parent_text = parent.get_text()
              # Check for status: open, status:closed, or status badges
              if re.search(r"status[:\s]*open", parent_text, re.IGNORECASE):
                status = "open"
              elif re.search(r"status[:\s]*closed", parent_text, re.IGNORECASE):
                status = "closed"
              else:
                # Look for status badge elements
                status_badge = parent.select_one('[class*="status"], [class*="badge"]')
                if status_badge:
                  badge_text = status_badge.get_text(strip=True).lower()
                  if "open" in badge_text:
                    status = "open"
                  elif "closed" in badge_text:
                    status = "closed"
            
            # Only include grants with "Open" status
            if status == "open":
              all_opportunity_urls.append((title, href))
              new_urls_on_page += 1
        
        # Method 2: Find headings that might be funding opportunities and look for associated links
        headings = soup.select("h2, h3")
        for heading in headings:
          heading_text = heading.get_text(strip=True)
          # Skip generic headings
          if heading_text.lower() in ["filter funding opportunities", "funding opportunities", "current page"]:
            continue
          
          # Look for a link near this heading (check for both /funding/ and /node/ links)
          parent = heading.find_parent(["article", "div", "li", "section"])
          if parent:
            link_el = parent.select_one("a[href*='/funding/'], a[href*='/node/']")
            if link_el:
              href = link_el.get("href", "")
              if href.startswith("/"):
                href = f"https://www.nihr.ac.uk{href}"
              elif not href.startswith("http"):
                continue
              
              # For /node/ links, make sure they're near grant-like headings
              if "/node/" in href and "/funding/" not in href:
                if len(heading_text) < 20 or "filter" in heading_text.lower():
                  continue
              
              if href not in seen_urls and href != listing_url and "?page=" not in href:
                seen_urls.add(href)
                # Use heading text as title if it's better than link text
                link_text = link_el.get_text(strip=True)
                title = heading_text if len(heading_text) > len(link_text) else link_text
                if title and len(title) > 10:
                  # Check if this grant has "Open" status
                  status = "unknown"
                  if parent:
                    parent_text = parent.get_text()
                    if re.search(r"status[:\s]*open", parent_text, re.IGNORECASE):
                      status = "open"
                    elif re.search(r"status[:\s]*closed", parent_text, re.IGNORECASE):
                      status = "closed"
                    else:
                      status_badge = parent.select_one('[class*="status"], [class*="badge"]')
                      if status_badge:
                        badge_text = status_badge.get_text(strip=True).lower()
                        if "open" in badge_text:
                          status = "open"
                        elif "closed" in badge_text:
                          status = "closed"
                  
                  # Only include grants with "Open" status
                  if status == "open":
                    all_opportunity_urls.append((title, href))
                    new_urls_on_page += 1
        
        if new_urls_on_page == 0 and page > 1:
          # No new opportunities found on this page (and it's not the first page), so we've reached the end
          print(f"  Page {page}: No new opportunities found, stopping pagination.")
          break
        elif new_urls_on_page > 0:
          print(f"  Page {page}: Found {new_urls_on_page} new opportunities (total: {len(all_opportunity_urls)})")
        else: # page == 1 and new_urls_on_page == 0
          print(f"  Page {page}: No opportunities found on the first page. Check selectors or URL.")
          break
        
        # Check if there's a next page
        next_page_link = soup.select_one("a[href*='?page=']")
        if not next_page_link or page >= max_pages:
          # No next page link found or reached max pages
          if page < max_pages:
            print(f"  Reached end of pagination at page {page}")
          break
        
        page += 1
        time.sleep(1)  # Throttle between pages
        
    
    pages_fetched = max(page - 1, 0)
    print(f"Found {len(all_opportunity_urls)} total NIHR opportunities across {pages_fetched} page(s)")
    
    # If no opportunities were found, exit early with context to avoid undefined variables
    if not all_opportunity_urls:
      if last_listing_error:
        print(f"NIHR listing fetch failed: {last_listing_error}")
      else:
        print("NIHR listing returned no opportunities.")
      return grants
    
    # Process the funding opportunity URLs we found
    if all_opportunity_urls:
      print(f"Processing {len(all_opportunity_urls)} NIHR funding opportunities...")
      new_count = 0
      existing_count_in_listing = 0
      
      for idx, (title, href) in enumerate(all_opportunity_urls, 1):
        if idx % 5 == 0:
          print(f"  Processed {idx}/{len(all_opportunity_urls)} opportunities... (new: {new_count}, existing: {existing_count_in_listing})")
        
        # Check if this grant already exists
        is_existing = href in existing_grants
        if is_existing:
          existing_count_in_listing += 1
        else:
          new_count += 1
        
        time.sleep(1)  # Throttle
        try:
          detail_resp = fetch_with_retry(session, href, referer=listing_url, timeout=30)
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
                if any(word in heading_text for word in ["overview", "summary", "introduction", "about"]):
                  current_section = "overview"
                elif any(word in heading_text for word in ["eligibility", "who can apply", "who is eligible"]):
                  current_section = "eligibility"
                elif any(word in heading_text for word in ["funding", "budget", "cost", "financial"]):
                  current_section = "funding"
                elif any(word in heading_text for word in ["application", "how to apply", "apply", "submission"]):
                  current_section = "how_to_apply"
                elif any(word in heading_text for word in ["deadline", "closing", "dates", "timeline", "schedule"]):
                  current_section = "dates"
                elif any(word in heading_text for word in ["assessment", "evaluation", "review", "criteria"]):
                  current_section = "assessment"
                elif any(word in heading_text for word in ["contact", "enquiries", "questions"]):
                  current_section = "contact"
                elif any(word in heading_text for word in ["terms", "conditions", "requirements"]):
                  current_section = "terms"
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
              # Try to identify sections by common NIHR page patterns
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
          
          # Try to extract deadline
          deadline_raw = None
          deadline_patterns = [
              r"deadline[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
              r"closing[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
              r"closes?[:\s]+(\d{1,2}\s+\w+\s+\d{4})",
              r"(\d{1,2}\s+\w+\s+\d{4})",  # "31 December 2024"
          ]
          page_text = detail_soup.get_text()
          for pattern in deadline_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
              deadline_raw = match.group(1)
              break
          
          # Try to extract funding amount
          funding_amount = None
          funding_patterns = [
              r"£[\d,]+(?:\.\d{2})?(?:\s(?:million|billion))?",
              r"funding[:\s]+(£[\d,]+(?:\.\d{2})?(?:\s(?:million|billion))?)",
              r"up to\s+(£[\d,]+(?:\.\d{2})?(?:\s(?:million|billion))?)",
              r"maximum[:\s]+(£[\d,]+(?:\.\d{2})?(?:\s(?:million|billion))?)",
          ]
          for pattern in funding_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
              funding_amount = match.group(0) if not match.groups() else match.group(1)
              break
          
          # Format description with section headings for better readability
          formatted_description = description
          if sections:
            # Build formatted description with clear section headings
            formatted_parts = []
            section_order = ["overview", "eligibility", "funding", "how_to_apply", "dates", "assessment", "contact", "terms"]
            
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
              "source": "nihr",
              "title": title,
              "url": href,
              "summary": summary,
              "description": formatted_description,
              "deadline": parse_deadline(deadline_raw) if deadline_raw else None,
              "funding_amount": funding_amount,
              "status": "open",
              "raw_data": {
                  "listing_url": listing_url,
                  "scraped_url": href,
                  "sections": sections if sections else None
              },
          }
          grant["hash_checksum"] = sha256_for_grant(grant)
          grants.append(grant)
        except Exception as e:
          print(f"Error scraping NIHR grant {href}: {e}")
          continue
    
    # Fallback: Try multiple selectors - NIHR site structure may vary
    elif not all_opportunity_urls:
      # Try multiple selectors - NIHR site structure may vary
      # Look for grant listings in various possible structures
      grant_cards = (
          soup.select("article") or
          soup.select(".grant-opportunity") or
          soup.select(".funding-opportunity") or
          soup.select("[class*='opportunity']") or
          soup.select("[class*='grant']") or
          soup.select("div[class*='card']") or
          []
      )
      
      if grant_cards:
        # Process grant cards found
        print(f"Found {len(grant_cards)} grant cards")
      for card in grant_cards:
        title_el = card.select_one("h2, h3, .title, [class*='title']")
        link_el = card.select_one("a")
        
        if not link_el:
          continue
        
        title = title_el.get_text(strip=True) if title_el else link_el.get_text(strip=True)
        if not title:
          continue
        
        url = link_el.get("href", "")
        if url.startswith("/"):
          url = f"https://www.nihr.ac.uk{url}"
        elif not url.startswith("http"):
          continue
        
        time.sleep(1)  # Throttle between requests
        try:
          detail_resp = fetch_with_retry(session, url, referer=listing_url, timeout=30)
          detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
          
          desc_el = (
              detail_soup.select_one("main") or
              detail_soup.select_one(".content") or
              detail_soup.select_one("article")
          )
          description = desc_el.get_text("\n", strip=True) if desc_el else ""
          
          # Extract structured sections (same logic as above)
          sections = {}
          summary_from_sections = None
          
          if desc_el:
            # Look for headings (h2, h3) to identify sections
            headings = desc_el.find_all(["h2", "h3"])
            current_section = None
            current_content = []
            
            for element in desc_el.descendants:
              if element.name in ["h2", "h3"]:
                if current_section and current_content:
                  sections[current_section] = "\n".join(current_content).strip()
                heading_text = element.get_text(strip=True).lower()
                current_section = None
                
                if any(word in heading_text for word in ["overview", "summary", "introduction", "about"]):
                  current_section = "overview"
                elif any(word in heading_text for word in ["eligibility", "who can apply"]):
                  current_section = "eligibility"
                elif any(word in heading_text for word in ["funding", "budget", "cost"]):
                  current_section = "funding"
                elif any(word in heading_text for word in ["application", "how to apply", "apply"]):
                  current_section = "how_to_apply"
                elif any(word in heading_text for word in ["deadline", "closing", "dates"]):
                  current_section = "dates"
                elif any(word in heading_text for word in ["assessment", "evaluation"]):
                  current_section = "assessment"
                elif any(word in heading_text for word in ["contact", "enquiries"]):
                  current_section = "contact"
                else:
                  current_section = heading_text.replace(" ", "_").replace("-", "_")[:50]
                current_content = []
              elif element.name in ["p", "div", "li"] and current_section:
                text = element.get_text(strip=True)
                if text and len(text) > 10:
                  current_content.append(text)
            
            if current_section and current_content:
              sections[current_section] = "\n".join(current_content).strip()
            
            if not sections and description:
              paragraphs = [p.strip() for p in description.split("\n") if p.strip() and len(p.strip()) > 20]
              if paragraphs:
                sections["overview"] = "\n\n".join(paragraphs[:3])
                if len(paragraphs) > 3:
                  sections["additional_information"] = "\n\n".join(paragraphs[3:])
                summary_from_sections = paragraphs[0][:200] + "..." if len(paragraphs[0]) > 200 else paragraphs[0]
          
          # Format description with sections
          formatted_description = description
          if sections:
            formatted_parts = []
            section_order = ["overview", "eligibility", "funding", "how_to_apply", "dates", "assessment", "contact"]
            for section_key in section_order:
              if section_key in sections:
                section_title = section_key.replace("_", " ").title()
                formatted_parts.append(f"## {section_title}\n\n{sections[section_key]}")
            for section_key, section_content in sections.items():
              if section_key not in section_order:
                section_title = section_key.replace("_", " ").title()
                formatted_parts.append(f"## {section_title}\n\n{section_content}")
            if formatted_parts:
              formatted_description = "\n\n".join(formatted_parts)
          
          # Extract deadline and funding amount (same logic as above)
          deadline_raw = None
          funding_amount = None
          page_text = detail_soup.get_text()
          
          deadline_patterns = [
              r"deadline[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
              r"closing[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
              r"(\d{1,2}\s+\w+\s+\d{4})",
          ]
          for pattern in deadline_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
              deadline_raw = match.group(1)
              break
          
          funding_patterns = [
              r"£[\d,]+",
              r"funding[:\s]+£?([\d,]+)",
              r"up to £?([\d,]+)",
          ]
          for pattern in funding_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
              funding_amount = f"£{match.group(1) if match.groups() else match.group(0)}"
              break
          
          # Get summary from sections or description
          summary = summary_from_sections if summary_from_sections else (description[:200] + "..." if len(description) > 200 else description)
          
          grant: Dict[str, Any] = {
              "source": "nihr",
              "title": title,
              "url": url,
              "summary": summary,
              "description": formatted_description,
              "deadline": parse_deadline(deadline_raw) if deadline_raw else None,
              "funding_amount": funding_amount,
              "status": "open",
              "raw_data": {
                  "listing_url": listing_url,
                  "scraped_url": url,
                  "sections": sections if sections else None
              },
          }
          grant["hash_checksum"] = sha256_for_grant(grant)
          grants.append(grant)
        except Exception as e:
          print(f"Error scraping NIHR grant {url}: {e}")
          continue
    
    print(f"Successfully scraped {len(grants)} NIHR grants")
    if all_opportunity_urls:
      print(f"  - New grants found: {new_count}")
      print(f"  - Existing grants re-checked: {existing_count_in_listing}")
    print(f"  - Note: Django will skip unchanged grants based on hash_checksum comparison")
    return grants
    
  except Exception as e:
    error_msg = f"NIHR scraper failed: {str(e)}"
    print(error_msg)
    raise Exception(error_msg) from e

