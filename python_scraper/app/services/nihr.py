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
  # NIHR may block automated requests - try to establish session by visiting homepage first
  # This helps establish cookies and session state that may be required for subsequent requests
  try:
    print("Establishing session with NIHR homepage...")
    homepage_resp = session.get("https://www.nihr.ac.uk/", timeout=15)
    if homepage_resp.status_code == 200:
      print("  Session established successfully")
      # Store cookies from homepage
      if homepage_resp.cookies:
        print(f"  Received {len(homepage_resp.cookies)} cookies")
      time.sleep(2)  # Small delay to seem more human-like
    else:
      print(f"  Warning: Homepage returned status {homepage_resp.status_code}")
  except Exception as e:
    print(f"  Warning: Could not establish session: {e}")
    # Continue anyway - the fetch_with_retry function will handle retries
  
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
        # Add delay between requests to seem more human-like
        if page > 1:
          time.sleep(3)  # Longer delay between pages
        
        # Use browser-like headers with proper referer chain
        # For first page, use homepage as referer; for subsequent pages, use previous page
        if page == 1:
          referer_url = "https://www.nihr.ac.uk/"  # Refer to homepage for first page
        else:
          referer_url = f"{listing_url}?page={page - 2}" if page > 2 else listing_url
        resp = fetch_with_retry(session, url_to_fetch, referer=referer_url, timeout=30)
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
        
      except Exception as e:
        # Handle errors for this page
        print(f"  Error fetching page {page}: {e}")
        last_listing_error = str(e)
        # Continue to next page or break if it's the first page
        if page == 1:
          break
        page += 1
        continue
    
    pages_fetched = max(page - 1, 0)
    print(f"Found {len(all_opportunity_urls)} total NIHR opportunities across {pages_fetched} page(s)")
    
    # If no opportunities were found, check if it was due to an error
    if not all_opportunity_urls:
      if last_listing_error:
        error_msg = (
          f"NIHR listing fetch failed: {last_listing_error}\n\n"
          "The NIHR website appears to be blocking automated requests. This may be due to:\n"
          "- Bot protection (Cloudflare, etc.) requiring JavaScript/CAPTCHA\n"
          "- Geographic restrictions (if running from outside UK)\n"
          "- Rate limiting or IP-based blocking\n\n"
          "Possible solutions:\n"
          "1. Use the NIHR Open Data API: https://nihr.opendatasoft.com/\n"
          "2. Run the scraper from a UK-based server/VPN\n"
          "3. Implement browser automation (Selenium/Playwright) to handle JavaScript/CAPTCHA\n"
          "4. Contact NIHR to request API access or whitelist your IP"
        )
        print(error_msg)
        # Raise exception to indicate failure, not just empty results
        raise Exception(error_msg)
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
          
          # Extract structured sections from tabbed content
          # NIHR uses tabs with IDs like: tab-overview, tab-research-specification, etc.
          sections = {}
          summary_from_sections = None
          
          # Map tab IDs to section keys
          tab_mapping = {
              "tab-overview": "overview",
              "tab-research-specification": "research_specification",
              "tab-application-guidance": "application_guidance",
              "tab-application-process": "application_process",
              "tab-contact-details": "contact"
          }
          
          # Extract content from each tab using a single method: heading-based parsing
          tabs_found = []
          for tab_id, section_key in tab_mapping.items():
            # Find the actual tab content div, not the tab link
            # Tab content is typically in a div with id="tab-overview" etc.
            tab_el = detail_soup.select_one(f"div#{tab_id}, div[id='{tab_id}'], section#{tab_id}, [id='{tab_id}'].tab-pane")
            # Also try finding by class if ID doesn't work
            if not tab_el:
              tab_el = detail_soup.select_one(f".tab-pane[id='{tab_id}'], .tab-content #{tab_id}")
            # Last resort: find any element with this ID that's not a link
            if not tab_el:
              all_with_id = detail_soup.select(f"[id='{tab_id}']")
              for el in all_with_id:
                if el.name != 'a':  # Skip tab links
                  tab_el = el
                  break
            
            if tab_el:
              tabs_found.append(tab_id)
              
              # Extract all content from the tab div
              # Work directly with the found element
              # Remove navigation and UI elements first
              tab_work = BeautifulSoup(str(tab_el), "html.parser")
              tab_div = tab_work.find(id=tab_id) or tab_work.find("div") or tab_work
              
              if tab_div:
                # Remove navigation and UI elements
                for nav in tab_div.select("nav, .pagerer, button.btn, script, style, .social-share"):
                  nav.decompose()
                
                # Extract content with markdown formatting for headers
                # Process elements to convert HTML headers to markdown
                text_parts = []
                
                # Process all elements, converting headers to markdown
                for element in tab_div.descendants:
                  if hasattr(element, 'name'):
                    if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                      header_text = element.get_text(strip=True)
                      if header_text:
                        # Convert HTML headers to markdown
                        level = int(element.name[1])  # h1 -> 1, h2 -> 2, etc.
                        markdown_header = '#' * level + ' ' + header_text
                        text_parts.append(markdown_header)
                    elif element.name == 'p':
                      para_text = element.get_text(strip=True)
                      if para_text and len(para_text) > 2:
                        text_parts.append(para_text)
                    elif element.name in ['li']:
                      # Only process if parent is ul/ol (to avoid duplicates)
                      parent = element.parent
                      if parent and parent.name in ['ul', 'ol']:
                        li_text = element.get_text(strip=True)
                        if li_text and len(li_text) > 2:
                          text_parts.append('• ' + li_text)
                    elif element.name in ['ul', 'ol']:
                      # Process list items (already handled above via li)
                      pass
                
                # If structured extraction didn't yield much, fall back to simple text extraction
                if not text_parts or sum(len(p) for p in text_parts) < 50:
                  # Fallback: get all text and try to preserve structure
                  combined_text = tab_div.get_text(separator="\n", strip=True)
                  
                  # Try to detect and convert headers in plain text
                  if combined_text:
                    lines = []
                    for line in combined_text.split("\n"):
                      line = line.strip()
                      if not line:
                        continue
                      # Skip navigation patterns
                      skip_patterns = ["share", "download", "print", "previous section", "next section", "back to"]
                      if any(pattern in line.lower() for pattern in skip_patterns):
                        continue
                      # Check if line looks like a header (short, all caps, or ends with colon)
                      if (len(line) < 80 and 
                          (line.isupper() or line.endswith(':') or 
                           (len(line.split()) < 8 and line[0].isupper()))):
                        # Might be a header - convert to markdown
                        lines.append('## ' + line)
                      else:
                        lines.append(line)
                    combined_text = "\n".join(lines)
                else:
                  # Use structured extraction
                  combined_text = "\n\n".join(text_parts)
                
                # Clean up: remove excessive whitespace
                if combined_text:
                  # Remove excessive blank lines
                  combined_text = re.sub(r'\n{3,}', '\n\n', combined_text).strip()
                  
                  # Remove navigation text patterns
                  lines = []
                  skip_patterns = ["share", "download", "print", "previous section", "next section", "back to"]
                  for line in combined_text.split("\n"):
                    line = line.strip()
                    if (len(line) > 2 and 
                        not any(pattern in line.lower() for pattern in skip_patterns)):
                      lines.append(line)
                  
                  combined_text = "\n".join(lines).strip()
                  combined_text = re.sub(r'\n{3,}', '\n\n', combined_text).strip()
                
                # Save the entire tab content as one section
                if combined_text and len(combined_text) > 10:
                  sections[section_key] = combined_text
          
          # Debug: Print what tabs were found
          if tabs_found:
            print(f"  Found {len(tabs_found)} tabs: {tabs_found} for {href}")
          else:
            print(f"  No tabs found for {href}, falling back to main content parsing")
          
          # Only use fallback if NO tabs were found at all
          # If we found any tabs, only use those sections (some pages may only have 2-3 tabs)
          if not tabs_found and not sections:
            desc_el = (
                detail_soup.select_one("main") or
                detail_soup.select_one(".content") or
                detail_soup.select_one("article") or
                detail_soup.select_one("div[class*='description']")
            )
            
            if desc_el:
              current_section = None
              current_content = []
              
              # Process all elements using heading-based parsing only
              for element in desc_el.descendants:
                if hasattr(element, 'name') and element.name in ["h2", "h3"]:
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
                elif hasattr(element, 'name') and element.name in ["p", "div", "li", "ul", "ol"] and current_section:
                  text = element.get_text(strip=True)
                  if text and len(text) > 10:  # Skip very short text (likely navigation)
                    current_content.append(text)
              
              # Save last section
              if current_section and current_content:
                sections[current_section] = "\n".join(current_content).strip()
            
          # Build description from sections with proper ordering
          description = ""
          if sections:
            formatted_parts = []
            # Order matches NIHR site tab order
            section_order = ["overview", "research_specification", "application_guidance", "application_process", "contact"]
            
            for section_key in section_order:
              if section_key in sections and sections[section_key]:
                section_title = section_key.replace("_", " ").title()
                formatted_parts.append(f"## {section_title}\n\n{sections[section_key]}")
            
            # Add any remaining sections not in the standard order
            for section_key, section_content in sections.items():
              if section_key not in section_order and section_content:
                section_title = section_key.replace("_", " ").title()
                formatted_parts.append(f"## {section_title}\n\n{section_content}")
            
            description = "\n\n".join(formatted_parts)
          else:
            # Fallback: get all text from main content area
            desc_el = (
                detail_soup.select_one("main") or
                detail_soup.select_one(".content") or
                detail_soup.select_one("article")
            )
            description = desc_el.get_text("\n", strip=True) if desc_el else ""
          
          # Extract summary from meta description or first section
          summary_el = detail_soup.select_one("meta[name='description']")
          if summary_el and summary_el.get("content"):
            summary = summary_el["content"]
          elif sections.get("overview"):
            overview_text = sections["overview"]
            # Remove markdown headings from summary
            summary = re.sub(r'^#+\s+', '', overview_text, flags=re.MULTILINE)
            summary = summary[:200] + "..." if len(summary) > 200 else summary
          else:
            summary = description[:200] + "..." if len(description) > 200 else description
          
          # Extract opening and closing dates from the summary-list structure
          deadline_raw = None
          opening_date_raw = None
          page_text = detail_soup.get_text()  # Get page text once for use in multiple places
          
          # First, try to extract from the structured ul.summary-list format
          summary_list = detail_soup.select_one("ul.summary-list")
          if summary_list:
            list_items = summary_list.find_all("li", recursive=False)
            for li in list_items:
              # Find the label div
              label_div = li.select_one("div.label")
              if not label_div:
                continue
              
              label_text = label_div.get_text(strip=True).lower()
              
              # Find the value div
              value_div = li.select_one("div.value")
              if not value_div:
                continue
              
              # Check for opening date
              if "opening date" in label_text:
                # Try to get datetime attribute from time element first (most reliable)
                time_el = value_div.select_one("time[datetime]")
                if time_el:
                  opening_date_raw = time_el.get("datetime")
                else:
                  # Fallback to text content
                  opening_date_raw = value_div.get_text(strip=True)
              
              # Check for closing date
              elif "closing date" in label_text:
                # Try to get datetime attribute from time element first (most reliable)
                time_el = value_div.select_one("time[datetime]")
                if time_el:
                  deadline_raw = time_el.get("datetime")
                else:
                  # Fallback to text content
                  deadline_raw = value_div.get_text(strip=True)
          
          # Fallback to regex patterns if structured format not found
          if not deadline_raw or not opening_date_raw:
              # Only search for missing dates
              if not deadline_raw:
          deadline_patterns = [
              r"deadline[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
              r"closing[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
              r"closes?[:\s]+(\d{1,2}\s+\w+\s+\d{4})",
              r"(\d{1,2}\s+\w+\s+\d{4})",  # "31 December 2024"
          ]
          for pattern in deadline_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
              deadline_raw = match.group(1)
                      break
              
              if not opening_date_raw:
                  opening_patterns = [
                      r"opening[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                      r"opens?[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                      r"opening[:\s]+(\d{1,2}\s+\w+\s+\d{4})",
                      r"opens?[:\s]+(\d{1,2}\s+\w+\s+\d{4})",
                  ]
                  for pattern in opening_patterns:
                      match = re.search(pattern, page_text, re.IGNORECASE)
                      if match:
                          opening_date_raw = match.group(1)
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
          
          # Description is already formatted from sections above, but ensure proper ordering
          formatted_description = description
          if sections and not description:
            # Fallback: format description from sections if not already built
            formatted_parts = []
            section_order = ["overview", "research_specification", "application_guidance", "application_process", "contact"]
            
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
              "opening_date": parse_deadline(opening_date_raw) if opening_date_raw else None,
              "funding_amount": funding_amount,
              "status": "unknown",  # Status is computed from dates, not stored
              "raw_data": {
                  "listing_url": listing_url,
                  "scraped_url": href,
                  "sections": sections if sections else {}
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
          
          # Extract structured sections from tabbed content (same method as main flow)
          sections = {}
          
          # Map tab IDs to section keys
          tab_mapping = {
              "tab-overview": "overview",
              "tab-research-specification": "research_specification",
              "tab-application-guidance": "application_guidance",
              "tab-application-process": "application_process",
              "tab-contact-details": "contact"
          }
          
          # Extract content from each tab using heading-based parsing only
          for tab_id, section_key in tab_mapping.items():
            tab_el = detail_soup.select_one(f"#{tab_id}, [id*='{tab_id}'], [class*='{tab_id}']")
            if not tab_el:
              tab_el = detail_soup.select_one(f"div[id='{tab_id}'], section[id='{tab_id}']")
            
            if tab_el:
              # Create a copy to avoid modifying the original
              tab_copy = BeautifulSoup(str(tab_el), "html.parser")
              
              # Remove navigation and non-content elements
              for nav in tab_copy.select("nav, .pagerer, .social-share, button, .btn, script, style, .documents"):
                nav.decompose()
              
              # Find the main content area
              content_area = tab_copy
              main_content = tab_copy.select_one(".container, .content, .field--name-field-rich-text")
              if main_content:
                content_area = main_content
              
              # Extract text with structure preservation
              text_parts = []
              
              # Process headings first
              for heading in content_area.find_all(["h2", "h3", "h4", "h5"]):
                heading_text = heading.get_text(strip=True)
                if heading_text and len(heading_text) > 2:
                  text_parts.append(f"\n## {heading_text}\n")
              
              # Get paragraphs and list items
              for p in content_area.find_all(["p", "li"]):
                p_text = p.get_text(strip=True)
                if p_text and len(p_text) > 5:
                  if not any(p_text[:20] in part for part in text_parts):
                    text_parts.append(p_text)
              
              # Use structured content or fallback to all text
              if text_parts and len("\n\n".join(text_parts)) > 50:
                combined_text = "\n\n".join(text_parts).strip()
              else:
                combined_text = content_area.get_text(separator="\n", strip=True)
              
              # Clean up
              if combined_text:
                lines = []
                for line in combined_text.split("\n"):
                  line = line.strip()
                  if (len(line) > 5 and 
                      not line.lower().startswith("share") and 
                      "cookie" not in line.lower() and
                      "previous section" not in line.lower() and
                      "next section" not in line.lower() and
                      not line.startswith("Download") and
                      not line.startswith("Print")):
                    lines.append(line)
                combined_text = "\n\n".join(lines).strip()
              
              # Remove duplicates
              if combined_text:
                final_lines = []
                prev_line = None
                for line in combined_text.split("\n"):
                  line_stripped = line.strip()
                  if line_stripped and line_stripped != prev_line:
                    final_lines.append(line_stripped)
                    prev_line = line_stripped
                combined_text = "\n\n".join(final_lines).strip()
              
              if combined_text and len(combined_text) > 20:
                sections[section_key] = combined_text
          
          # If no tabs found, fall back to main content area with heading-based parsing
          if not sections:
            desc_el = (
                detail_soup.select_one("main") or
                detail_soup.select_one(".content") or
                detail_soup.select_one("article")
            )
            
            if desc_el:
              current_section = None
              current_content = []
              
              for element in desc_el.descendants:
                if hasattr(element, 'name') and element.name in ["h2", "h3"]:
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
                elif hasattr(element, 'name') and element.name in ["p", "div", "li"] and current_section:
                  text = element.get_text(strip=True)
                  if text and len(text) > 10:
                    current_content.append(text)
              
              if current_section and current_content:
                sections[current_section] = "\n".join(current_content).strip()
            
          # Build description from sections with proper ordering
          description = ""
          if sections:
            formatted_parts = []
            section_order = ["overview", "research_specification", "application_guidance", "application_process", "contact"]
            
            for section_key in section_order:
              if section_key in sections and sections[section_key]:
                section_title = section_key.replace("_", " ").title()
                formatted_parts.append(f"## {section_title}\n\n{sections[section_key]}")
            
            for section_key, section_content in sections.items():
              if section_key not in section_order and section_content:
                section_title = section_key.replace("_", " ").title()
                formatted_parts.append(f"## {section_title}\n\n{section_content}")
            
            description = "\n\n".join(formatted_parts)
          else:
            desc_el = (
                detail_soup.select_one("main") or
                detail_soup.select_one(".content") or
                detail_soup.select_one("article")
            )
            description = desc_el.get_text("\n", strip=True) if desc_el else ""
          
          formatted_description = description
          
          # Extract summary
          summary_el = detail_soup.select_one("meta[name='description']")
          if summary_el and summary_el.get("content"):
            summary = summary_el["content"]
          elif sections.get("overview"):
            overview_text = sections["overview"]
            summary = re.sub(r'^#+\s+', '', overview_text, flags=re.MULTILINE)
            summary = summary[:200] + "..." if len(summary) > 200 else summary
          else:
            summary = description[:200] + "..." if len(description) > 200 else description
          
          # Extract opening and closing dates from the summary-list structure
          deadline_raw = None
          opening_date_raw = None
          page_text = detail_soup.get_text()  # Get page text once for use in multiple places
          
          # First, try to extract from the structured ul.summary-list format
          summary_list = detail_soup.select_one("ul.summary-list")
          if summary_list:
            list_items = summary_list.find_all("li", recursive=False)
            for li in list_items:
              # Find the label div
              label_div = li.select_one("div.label")
              if not label_div:
                continue
              
              label_text = label_div.get_text(strip=True).lower()
              
              # Find the value div
              value_div = li.select_one("div.value")
              if not value_div:
                continue
              
              # Check for opening date
              if "opening date" in label_text:
                # Try to get datetime attribute from time element first (most reliable)
                time_el = value_div.select_one("time[datetime]")
                if time_el:
                  opening_date_raw = time_el.get("datetime")
                else:
                  # Fallback to text content
                  opening_date_raw = value_div.get_text(strip=True)
              
              # Check for closing date
              elif "closing date" in label_text:
                # Try to get datetime attribute from time element first (most reliable)
                time_el = value_div.select_one("time[datetime]")
                if time_el:
                  deadline_raw = time_el.get("datetime")
                else:
                  # Fallback to text content
                  deadline_raw = value_div.get_text(strip=True)
          
          # Fallback to regex patterns if structured format not found
          if not deadline_raw or not opening_date_raw:
              # Only search for missing dates
              if not deadline_raw:
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
          
              if not opening_date_raw:
                  opening_patterns = [
                      r"opening[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                      r"opens?[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                      r"opening[:\s]+(\d{1,2}\s+\w+\s+\d{4})",
                      r"opens?[:\s]+(\d{1,2}\s+\w+\s+\d{2,4})",
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
          ]
          for pattern in funding_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
              funding_amount = f"£{match.group(1) if match.groups() else match.group(0)}"
              break
          
          grant: Dict[str, Any] = {
              "source": "nihr",
              "title": title,
              "url": url,
              "summary": summary,
              "description": formatted_description,
              "deadline": parse_deadline(deadline_raw) if deadline_raw else None,
              "opening_date": parse_deadline(opening_date_raw) if opening_date_raw else None,
              "funding_amount": funding_amount,
              "status": "unknown",  # Status is computed from dates, not stored
              "raw_data": {
                  "listing_url": listing_url,
                  "scraped_url": url,
                  "sections": sections if sections else {}
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

