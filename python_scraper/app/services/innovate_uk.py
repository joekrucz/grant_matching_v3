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
    # Pagination: first page is base URL, second page is ?page=1 (0-based index in param)
    page = 0
    max_pages = 50  # Safety limit
    
    while page < max_pages:
      url = base_url if page == 0 else f"{base_url}?page={page}"
      
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
        
        # Detect explicit "next" pagination even if no new URLs were added (e.g., duplicates filtered)
        def has_next_page(soup: BeautifulSoup) -> bool:
          selectors = [
              "a[rel='next']",
              "a[href*='page='][aria-label*='Next']",
              ".pagination a.next",
              ".govuk-pagination__link--next",
              ".moj-pagination__link--next",
          ]
          for sel in selectors:
            if soup.select_one(sel):
              return True
          # Fallback: any link whose text contains "next" (case-insensitive)
          for link in soup.find_all("a"):
            text = link.get_text(strip=True).lower()
            if "next" in text:
              return True
          return False

        has_next = has_next_page(soup)
        
        if new_urls_on_page > 0 or has_next:
          print(f"  Page {page}: Found {new_urls_on_page} new competitions (total: {len(all_competition_urls)})")
          page += 1
          time.sleep(1)  # Throttle between pages
        else:
          # No competitions found on this page and no next link, end pagination
          print(f"  Page {page}: No competitions found and no next link, reached end of pagination")
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
        
        # Extract structured sections prioritizing the known tab structure
        sections: Dict[str, str] = {}
        summary_from_sections = None
        
        def normalize_key(text: str) -> str:
          return text.lower().strip().replace(" ", "_").replace("-", "_")
        
        desired_tabs = [
            ("summary", ["summary", "overview"]),
            ("eligibility", ["eligibility", "who_can_apply", "who_can_apply?"]),
            ("scope", ["scope"]),
            ("dates", ["dates", "key_dates", "timeline"]),
            ("how_to_apply", ["how_to_apply", "how_to_apply?", "apply", "how-to-apply"]),
            ("supporting_information", ["supporting_information", "supporting_info"]),
        ]
        # Tab IDs in the order they appear on the page
        tab_ids = ["summary", "eligibility", "scope", "dates", "how-to-apply", "supporting-information"]
        print(f"  Looking for tab panels with IDs: {tab_ids}")
        
        def extract_by_anchor_ids(soup: BeautifulSoup) -> Dict[str, str]:
          """
          Extract content from each tab panel section.
          
          Process:
          1. Find all <section class="govuk-tabs__panel" id="..."> elements
          2. Map each section's ID to its element
          3. For each expected tab_id, get the corresponding section
          4. Extract text content from that section only
          """
          tab_sections: Dict[str, str] = {}
          
          # Step 1: Find all tab panel sections
          all_tab_panels = soup.find_all("section", class_="govuk-tabs__panel")
          print(f"  Found {len(all_tab_panels)} tab panel sections")
          
          # Step 2: Create a mapping of tab_id to section element
          tab_id_to_section = {}
          for panel in all_tab_panels:
            panel_id = panel.get("id", "")
            if panel_id:
              tab_id_to_section[panel_id] = panel
              print(f"    - Panel with id='{panel_id}'")
          
          # Step 3: Extract content for each expected tab in order
          for tab_id in tab_ids:
            print(f"\n  Processing tab_id: '{tab_id}'")
            
            # Step 3a: Find the section element for this tab_id
            section = tab_id_to_section.get(tab_id)
            if not section:
              # Fallback: try direct lookup
              section = soup.select_one(f"section.govuk-tabs__panel[id='{tab_id}']")
            
            if not section:
              print(f"    ✗ Could not find tab panel with id='{tab_id}'")
              continue
            
            print(f"    ✓ Found section element (tag={section.name}, id={section.get('id')})")
            
            # Step 3b: Extract text content from this section with markdown formatting
            # Strategy: Process the grid layout structure (govuk-grid-row) to extract headings and content
            # Remove any tab-related elements first
            section_copy = BeautifulSoup(str(section), "html.parser")
            
            # Remove tab navigation if it exists
            for nav in section_copy.find_all(class_=lambda x: x and ("govuk-tabs__list" in " ".join(x) or "govuk-tabs__title" in " ".join(x))):
              nav.decompose()
            
            # Remove navigation and UI elements
            for nav in section_copy.select("nav, button, script, style, .govuk-tabs__list"):
              nav.decompose()
            
            # Extract content with markdown formatting
            # Innovate UK uses a grid layout: each row has a heading (left column) and content (right column)
            text_parts = []
            processed_elements = set()
            
            # Find all grid rows in the section
            grid_rows = section_copy.select(".govuk-grid-row")
            
            for row in grid_rows:
              # Get the heading from the left column (govuk-grid-column-one-third)
              heading_col = row.select_one(".govuk-grid-column-one-third")
              heading_text = None
              if heading_col:
                heading_el = heading_col.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                if heading_el:
                  heading_text = heading_el.get_text(strip=True)
                  # Skip generic section titles
                  line_lower = heading_text.lower()
                  section_title_variants = [
                    tab_id.replace("-", " "),
                    normalize_key(tab_id).replace("_", " ")
                  ]
                  if not any(line_lower == variant or line_lower.startswith(variant + " ") for variant in section_title_variants):
                    # Convert to markdown header (h2 -> ##)
                    level = int(heading_el.name[1])
                    markdown_header = '#' * level + ' ' + heading_text
                    text_parts.append(markdown_header)
              
              # Get the content from the right column (govuk-grid-column-two-thirds)
              content_col = row.select_one(".govuk-grid-column-two-thirds")
              if content_col:
                # Find the wysiwyg-styles div which contains the actual content
                content_div = content_col.select_one(".wysiwyg-styles, .govuk-body")
                if not content_div:
                  content_div = content_col
                
                # Process content elements in order
                for element in content_div.children:
                  if not hasattr(element, 'name') or id(element) in processed_elements:
                    continue
                  
                  if element.name == 'p':
                    para_text = element.get_text(strip=True)
                    if para_text and len(para_text) > 5:
                      text_parts.append(para_text)
                      processed_elements.add(id(element))
                  elif element.name in ['ul', 'ol']:
                    # Process list items
                    for li in element.find_all('li', recursive=False):
                      li_text = li.get_text(strip=True)
                      if li_text and len(li_text) > 2:
                        text_parts.append('• ' + li_text)
                        processed_elements.add(id(li))
                    processed_elements.add(id(element))
                  elif element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                    # Additional headings within content
                    header_text = element.get_text(strip=True)
                    if header_text:
                      level = int(element.name[1])
                      markdown_header = '#' * level + ' ' + header_text
                      text_parts.append(markdown_header)
                      processed_elements.add(id(element))
                  elif element.name == 'div':
                    # Check if div has direct content (not already processed via children)
                    direct_text = element.get_text(strip=True)
                    if direct_text and len(direct_text) > 10:
                      # Check if children were already processed
                      children_tags = element.find_all(['p', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                      children_processed = any(id(child) in processed_elements for child in children_tags)
                      if not children_processed:
                        # Process this div's content recursively
                        for child in element.children:
                          if hasattr(child, 'name'):
                            if child.name == 'p':
                              para_text = child.get_text(strip=True)
                              if para_text and len(para_text) > 5:
                                text_parts.append(para_text)
                                processed_elements.add(id(child))
                            elif child.name in ['ul', 'ol']:
                              for li in child.find_all('li', recursive=False):
                                li_text = li.get_text(strip=True)
                                if li_text and len(li_text) > 2:
                                  text_parts.append('• ' + li_text)
                                  processed_elements.add(id(li))
                              processed_elements.add(id(child))
            
            # Combine all parts
            if text_parts:
              full_text = "\n\n".join(text_parts).strip()
            else:
              # Fallback: get all text if structured extraction didn't work
              full_text = section_copy.get_text("\n", strip=True)
            
            # Clean up: remove duplicates while preserving order
            if full_text:
              lines = []
              seen = set()
              for line in full_text.split("\n"):
                line = line.strip()
                if line and len(line) > 5:
                  # Skip if it's just the section title
                  line_lower = line.lower()
                  section_title_variants = [
                    tab_id.replace("-", " "),
                    normalize_key(tab_id).replace("_", " ")
                  ]
                  is_title = any(line_lower == variant or line_lower.startswith(variant + " ") for variant in section_title_variants)
                  if not is_title:
                    # Check for duplicates (case-insensitive, but preserve markdown headers)
                    if line.startswith('#'):
                      # Always include markdown headers
                      lines.append(line)
                    elif line_lower not in seen:
                      seen.add(line_lower)
                      lines.append(line)
            
              # Remove excessive blank lines
              cleaned_text = "\n".join(lines).strip()
              cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text).strip()
            else:
              cleaned_text = ""
            
            key = normalize_key(tab_id)
            if cleaned_text:
              tab_sections[key] = cleaned_text
              print(f"    ✓ Extracted '{tab_id}': {len(tab_sections[key])} chars")
              print(f"      Preview: {tab_sections[key][:100]}...")
            else:
              print(f"    ✗ No content extracted for section '{tab_id}'")
          
          return tab_sections
        
        def extract_tabs_from_panels(soup: BeautifulSoup) -> Dict[str, str]:
          tab_sections: Dict[str, str] = {}
          panels = soup.select("[role='tabpanel'], .govuk-tabs__panel, .ifs-tabs__panel, .tabs__panel")
          if not panels:
            return tab_sections
          
          for panel in panels:
            heading_el = panel.find(["h2", "h3"])
            heading_text = heading_el.get_text(strip=True) if heading_el else ""
            key = None
            norm_heading = normalize_key(heading_text)
            for desired_key, aliases in desired_tabs:
              if norm_heading in aliases:
                key = desired_key
                break
            if not key:
              labelled_by = panel.get("aria-labelledby")
              if labelled_by:
                label_el = soup.select_one(f"#{labelled_by}")
                if label_el:
                  label_text = label_el.get_text(strip=True)
                  norm_label = normalize_key(label_text)
                  for desired_key, aliases in desired_tabs:
                    if norm_label in aliases:
                      key = desired_key
                      break
            if not key:
              data_tab = panel.get("data-tab") or panel.get("data-title")
              if data_tab:
                norm_tab = normalize_key(data_tab)
                for desired_key, aliases in desired_tabs:
                  if norm_tab in aliases:
                    key = desired_key
                    break
            if not key:
              continue
            content_text = panel.get_text("\n", strip=True)
            if content_text:
              tab_sections[key] = content_text
          return tab_sections
        
        # 1) Try to extract using anchor IDs (tabs with hash links) - STRATEGY 1 ONLY
        sections = extract_by_anchor_ids(detail_soup)
        
        # 2) If still empty, try explicit tab panels - DISABLED FOR TESTING
        # if not sections:
        #   sections = extract_tabs_from_panels(detail_soup)
        
        # 3) Fallback to heading-based parsing if nothing found - DISABLED FOR TESTING
        # if not sections and desc_el:
        #   headings = desc_el.find_all(["h2", "h3"])
        #   current_section = None
        #   current_content = []
        #   
        #   for element in desc_el.descendants:
        #     if element.name in ["h2", "h3"]:
        #       if current_section and current_content:
        #         sections[current_section] = "\n".join(current_content).strip()
        #       heading_text = element.get_text(strip=True).lower()
        #       current_section = None
        #       
        #       if any(word in heading_text for word in ["summary", "overview", "introduction", "about", "background"]):
        #         current_section = "summary"
        #       elif any(word in heading_text for word in ["eligibility", "who can apply", "who is eligible", "who should apply"]):
        #         current_section = "eligibility"
        #       elif any(word in heading_text for word in ["scope", "aims", "objectives"]):
        #         current_section = "scope"
        #       elif any(word in heading_text for word in ["funding", "budget", "cost", "financial", "value"]):
        #         current_section = "funding"
        #       elif any(word in heading_text for word in ["application", "how to apply", "apply", "submission", "submitting"]):
        #         current_section = "how_to_apply"
        #       elif any(word in heading_text for word in ["deadline", "closing", "dates", "timeline", "schedule", "key dates", "opens", "closes"]):
        #         current_section = "dates"
        #       elif any(word in heading_text for word in ["supporting information", "supporting", "guidance"]):
        #         current_section = "supporting_information"
        #       else:
        #         current_section = heading_text.replace(" ", "_").replace("-", "_")[:50]
        #       current_content = []
        #     elif element.name in ["p", "div", "li", "ul", "ol"] and current_section:
        #       text = element.get_text(strip=True)
        #       if text and len(text) > 10:
        #         current_content.append(text)
        #   
        #   if current_section and current_content:
        #     sections[current_section] = "\n".join(current_content).strip()
        #   
        #   if not sections and description:
        #     paragraphs = [p.strip() for p in description.split("\n") if p.strip() and len(p.strip()) > 20]
        #     if paragraphs:
        #       sections["summary"] = "\n\n".join(paragraphs[:3])
        #       if len(paragraphs) > 3:
        #         sections["supporting_information"] = "\n\n".join(paragraphs[3:])
        #       summary_from_sections = paragraphs[0][:200] + "..." if len(paragraphs[0]) > 200 else paragraphs[0]
        
        # Extract summary from meta description or first section
        summary_el = detail_soup.select_one("meta[name='description']")
        if summary_el and summary_el.get("content"):
          summary = summary_el["content"]
        elif sections.get("summary"):
          summary = sections["summary"][:200] + "..." if len(sections["summary"]) > 200 else sections["summary"]
        elif summary_from_sections:
          summary = summary_from_sections
        elif sections.get("overview"):
          overview_text = sections["overview"]
          summary = overview_text[:200] + "..." if len(overview_text) > 200 else overview_text
        else:
          summary = description[:200] + "..." if len(description) > 200 else description
        
        # Add summary to sections if it exists and isn't already there
        # This ensures summary appears in expandable sections in the UI
        if summary and "summary" not in sections:
          sections["summary"] = summary
        
        # Extract deadline - prioritize structured HTML format above tabs
        deadline_raw = None
        opening_date_raw = None
        page_text = detail_soup.get_text()  # Get page text once for use in multiple places
        
        # First, try to extract from the structured govuk-list format above the tabs
        # This is the most reliable source: <ul class="govuk-list"> with "Competition opens:" and "Competition closes:"
        govuk_list = detail_soup.select_one("ul.govuk-list")
        if govuk_list:
          list_items = govuk_list.find_all("li", recursive=False)
          for li in list_items:
            li_text = li.get_text(strip=True)
            
            # Check for "Competition opens:" pattern
            if "competition opens" in li_text.lower():
              # Look for span tag first (most reliable)
              span = li.find("span")
              if span:
                opening_date_raw = span.get_text(strip=True)
              else:
                # Extract text after "Competition opens:"
                opens_match = re.search(r"competition opens:?\s*(.+)", li_text, re.IGNORECASE)
                if opens_match:
                  opening_date_raw = opens_match.group(1).strip()
            
            # Check for "Competition closes:" pattern
            if "competition closes" in li_text.lower():
              # Look for span tag first (if present)
              span = li.find("span")
              if span:
                deadline_raw = span.get_text(strip=True)
              else:
                # Get text after the strong tag
                strong = li.find("strong")
                if strong:
                  # Get all text content after the strong tag
                  # This handles both direct text nodes and nested elements
                  parts = []
                  for sibling in strong.next_siblings:
                    if hasattr(sibling, 'get_text'):
                      text = sibling.get_text(strip=True)
                      if text:
                        parts.append(text)
                    elif isinstance(sibling, str):
                      text = sibling.strip()
                      if text:
                        parts.append(text)
                  if parts:
                    deadline_raw = ' '.join(parts).strip()
                
                # Fallback: extract from full text using regex
                if not deadline_raw or len(deadline_raw) < 5:
                  closes_match = re.search(r"competition closes:?\s*(.+)", li_text, re.IGNORECASE)
                  if closes_match:
                    deadline_raw = closes_match.group(1).strip()
        
        # Fallback to regex patterns if structured format not found
        if not deadline_raw:
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
        
        # Status is now computed from dates, not determined here
        
        # Format description with section headings for better readability
        formatted_description = description
        if sections:
          # Build formatted description with clear section headings
          formatted_parts = []
          # Order matches Innovate UK site tab order
          section_order = [
              "summary",              # Tab 1: Summary
              "eligibility",          # Tab 2: Eligibility
              "scope",                # Tab 3: Scope
              "dates",                # Tab 4: Dates
              "how_to_apply",         # Tab 5: How to apply
              "supporting_information", # Tab 6: Supporting information
              "funding",              # Additional sections (if present)
              "assessment",
              "contact",
              "terms",
          ]
          
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
            "opening_date": parse_deadline(opening_date_raw) if opening_date_raw else None,
            "funding_amount": funding_amount,
            "status": "unknown",  # Status is computed from dates, not stored
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

