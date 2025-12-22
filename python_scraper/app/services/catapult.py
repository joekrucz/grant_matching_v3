import time
import re
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

from app.utils.hashing import sha256_for_grant
from app.utils.normalisation import parse_deadline
from app.utils.http_client import create_session, fetch_with_retry

# Try to import Selenium, but make it optional
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False


def scrape_catapult(existing_grants: Dict[str, Dict[str, Any]] = None) -> List[Dict[str, Any]]:
  """
  Scrape Catapult network funding calls from https://cp.catapult.org.uk/open-calls/
  
  Args:
    existing_grants: Dict of existing grants keyed by URL, to help optimize scraping.
                     Format: {url: {hash_checksum: "...", slug: "...", title: "..."}}
  """
  if existing_grants is None:
    existing_grants = {}
  
  grants: List[Dict[str, Any]] = []
  listing_url = "https://cp.catapult.org.uk/open-calls/"
  
  session = create_session()
  
  existing_count = len(existing_grants)
  if existing_count > 0:
    print(f"Found {existing_count} existing Catapult grants in database")
  
  try:
    # Use a set to track unique grants by URL to avoid duplicates
    seen_urls = set()
    all_grant_data = []  # Store (h2, url, title) tuples
    
    # Fetch grants from all pages with pagination
    page = 1
    max_pages = 20  # Safety limit
    pagination_pattern = None  # Will be determined after first page
    
    while page <= max_pages:
      # Try different pagination URL patterns
      if page == 1:
        url = listing_url
      else:
        # Try the pattern that worked, or use the correct Catapult pattern
        if pagination_pattern:
          url = pagination_pattern.format(page=page)
        else:
          # Catapult uses ?_paged= pattern
          url = f"{listing_url}?_paged={page}"
      
      try:
        print(f"Fetching Catapult opportunities page {page} from {url}...")
        resp = fetch_with_retry(session, url, timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Catapult structure: h2 elements inside <a> tags contain grant titles
        grant_links = soup.select("a h2")
        
        new_grants_on_page = 0
        for h2 in grant_links:
          link_el = h2.find_parent("a")
          if not link_el:
            continue
          
          href = link_el.get("href", "")
          if not href or "/opportunity/" not in href:
            continue
          
          # Normalize URL
          if href.startswith("/"):
            href = f"https://cp.catapult.org.uk{href}"
          elif not href.startswith("http"):
            continue
          
          # Skip if we've already seen this URL
          if href in seen_urls:
            continue
          
          title = h2.get_text(strip=True)
          # Remove "Closed:" prefix if present
          if title.startswith("Closed:"):
            title = title.replace("Closed:", "").strip()
          
          seen_urls.add(href)
          all_grant_data.append((h2, href, title))
          new_grants_on_page += 1
        
        if new_grants_on_page > 0:
          print(f"  Page {page}: Found {new_grants_on_page} new grants (total: {len(all_grant_data)})")
          
          # On first successful page, try to detect pagination pattern from links
          if page == 1 and not pagination_pattern:
            pagination_links = soup.select("a[href*='page'], a[href*='paged'], .pagination a, .page-numbers a")
            for link in pagination_links:
              href = link.get("href", "")
              if "_paged=" in href:
                # Catapult uses ?_paged= pattern
                pagination_pattern = f"{listing_url}?_paged={{page}}"
                break
              elif "?page=" in href or "?paged=" in href:
                # Fallback to other patterns if _paged not found
                if "?page=" in href:
                  pagination_pattern = f"{listing_url}?page={{page}}"
                  break
                elif "?paged=" in href:
                  pagination_pattern = f"{listing_url}?paged={{page}}"
                  break
              elif "/page/" in href:
                pagination_pattern = f"{listing_url}page/{{page}}/"
                break
            # If no pattern detected, use the default Catapult pattern
            if not pagination_pattern:
              pagination_pattern = f"{listing_url}?_paged={{page}}"
          
          # Check if there's a next page
          next_page_link = soup.select_one("a[href*='_paged='], a[href*='page='], a[href*='paged='], .pagination a, .page-numbers a")
          if next_page_link:
            # Check if it's actually a "next" link or just another page number
            link_text = next_page_link.get_text(strip=True).lower()
            link_href = next_page_link.get("href", "")
            # If it's a number higher than current page, or says "next", continue
            if "next" in link_text or (link_text.isdigit() and int(link_text) > page):
              page += 1
              time.sleep(1)  # Throttle between pages
            elif page > 1:
              # No clear next page indicator, but we got grants, so try one more page
              page += 1
              time.sleep(1)
            else:
              # First page, continue to second page
              page += 1
              time.sleep(1)
          else:
            # No next page link found
            if page > 1:
              print(f"  Reached end of pagination at page {page}")
              break
            # On first page, try second page anyway
            page += 1
            time.sleep(1)
        else:
          # No new grants found on this page
          if page == 1:
            print(f"  Page {page}: No grants found on the first page. Check selectors or URL.")
            break
          else:
            print(f"  Page {page}: No new grants found, reached end of pagination")
            break
      except Exception as e:
        print(f"  Error fetching page {page}: {e}")
        if page == 1:
          # If first page fails, raise the error
          raise
        # Otherwise, stop pagination
        break
    
    print(f"Total unique grants found: {len(all_grant_data)}")
    
    new_count = 0
    existing_count_in_listing = 0
    
    if all_grant_data:
      grant_links = [data[0] for data in all_grant_data]  # Extract h2 elements
      # Process grant links (h2 inside <a> tags)
      print(f"Processing {len(grant_links)} grant links")
      for idx, (h2, url, title) in enumerate(zip(grant_links, [data[1] for data in all_grant_data], [data[2] for data in all_grant_data]), 1):
        # Use the pre-extracted data
        if not title or not url:
          continue
        
        # Check if this grant already exists
        is_existing = url in existing_grants
        if is_existing:
          existing_count_in_listing += 1
        else:
          new_count += 1
        
        if idx % 5 == 0:
          print(f"  Processed {idx}/{len(grant_links)} grants... (new: {new_count}, existing: {existing_count_in_listing})")
        
        # Get description from next sibling div
        description = ""
        next_sibling = h2.find_next_sibling("div")
        if next_sibling:
          description = next_sibling.get_text("\n", strip=True)
        
        # Extract deadline from the listing page text (format: "Open call closes: Thursday 4 December 2025 5:00pm")
        deadline_raw = None
        link_el = h2.find_parent("a")
        parent_text = link_el.get_text() if link_el else ""
        deadline_patterns = [
            r"open call closes?[:\s]+([A-Za-z]+\s+\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            r"closes?[:\s]+([A-Za-z]+\s+\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            r"deadline[:\s]+([A-Za-z]+\s+\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        ]
        for pattern in deadline_patterns:
          match = re.search(pattern, parent_text, re.IGNORECASE)
          if match:
            deadline_raw = match.group(1)
            break
        
        # Try to fetch detail page for more info
        try:
          time.sleep(1)  # Throttle
          detail_resp = fetch_with_retry(session, url, referer=listing_url, timeout=30)
          detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
          
          # Get full description from detail page if available
          detail_desc_el = (
              detail_soup.select_one("main") or
              detail_soup.select_one(".content") or
              detail_soup.select_one("article") or
              detail_soup.select_one("div[class*='description']")
          )
          if detail_desc_el:
            full_description = detail_desc_el.get_text("\n", strip=True)
            if len(full_description) > len(description):
              description = full_description
          
          # Extract structured sections from detail page with dynamic tab detection
          sections = {}
          summary_from_tab = None
          
          def normalize_key(text: str) -> str:
            """Normalize text to a consistent section key."""
            return text.lower().strip().replace(" ", "_").replace("-", "_").replace(":", "").replace("?", "")
          
          def detect_tabs(soup: BeautifulSoup) -> Dict[str, Any]:
            """
            Dynamically detect all available tabs on the page.
            Returns a dict mapping normalized section keys to tab elements, including tab numbers.
            """
            detected_tabs = {}
            
            # Strategy 0: Kadence tabs (specific to Catapult)
            kadence_tabs = soup.select_one(".wp-block-kadence-tabs, .kt-tabs-wrap")
            if kadence_tabs:
              # Find tab titles in the title list
              tab_title_items = kadence_tabs.select(".kt-tabs-title-list .kt-title-item, .kt-title-item")
              tab_content_wrap = kadence_tabs.select_one(".kt-tabs-content-wrap")
              
              for title_item in tab_title_items:
                # Get tab label from the title text span
                title_text_span = title_item.select_one(".kt-title-text")
                if title_text_span:
                  tab_label = title_text_span.get_text(strip=True)
                else:
                  # Fallback to link text
                  link = title_item.select_one("a")
                  if link:
                    tab_label = link.get_text(strip=True)
                  else:
                    continue
                
                # Get tab number from data-tab attribute
                tab_number = None
                link = title_item.select_one("a")
                if link:
                  data_tab = link.get("data-tab", "")
                  if data_tab:
                    try:
                      tab_number = int(data_tab)
                    except ValueError:
                      pass
                
                # Get tab ID from the title item or link
                tab_id = title_item.get("id", "")
                if not tab_id:
                  if link:
                    link_href = link.get("href", "")
                    if "#" in link_href:
                      tab_id = link_href.split("#")[-1]
                    else:
                      tab_id = link.get("id", "")
                
                # Find the corresponding content panel
                content_panel = None
                if tab_id:
                  # Try to find panel by ID
                  content_panel = soup.find(id=tab_id)
                  if not content_panel and tab_content_wrap:
                    # Try to find within content wrap
                    content_panel = tab_content_wrap.find(id=tab_id)
                
                # If not found by ID, try to find by data-tab attribute
                if not content_panel:
                  if link:
                    data_tab = link.get("data-tab", "")
                    if data_tab and tab_content_wrap:
                      # Find panel with matching data-tab or index
                      panels = tab_content_wrap.find_all(["div", "section"], class_=lambda x: x and "kt-tab-content" in " ".join(x))
                      try:
                        panel_index = int(data_tab) - 1
                        if 0 <= panel_index < len(panels):
                          content_panel = panels[panel_index]
                      except (ValueError, IndexError):
                        pass
                
                # If still not found, try to find by class pattern (kt-inner-tab-{number} or wp-block-kadence-tab)
                if not content_panel and tab_content_wrap:
                  # Look for wp-block-kadence-tab divs (these are the actual tab panels)
                  if tab_number:
                    # Try to find by tab number in class
                    panel_class_pattern = f"kt-inner-tab-{tab_number}"
                    content_panel = tab_content_wrap.select_one(f".{panel_class_pattern}, [class*='{panel_class_pattern}']")
                  
                  # Also try finding wp-block-kadence-tab divs
                  if not content_panel:
                    all_tab_panels = tab_content_wrap.find_all("div", class_=lambda x: x and ("wp-block-kadence-tab" in " ".join(x) or "kt-tab-inner-content" in " ".join(x)))
                    if all_tab_panels:
                      # Match by order if we have tab_number, otherwise use index
                      if tab_number:
                        # Find panel with matching tab number
                        for panel in all_tab_panels:
                          panel_classes = " ".join(str(c) for c in panel.get("class", []))
                          if f"kt-inner-tab-{tab_number}" in panel_classes:
                            content_panel = panel
                            break
                      if not content_panel:
                        # Fallback to index matching
                        title_index = tab_title_items.index(title_item)
                        if 0 <= title_index < len(all_tab_panels):
                          content_panel = all_tab_panels[title_index]
                
                # Fallback: get all content panels and match by order
                if not content_panel and tab_content_wrap:
                  # Look for divs with kt-inner-content classes (these are the actual content panels)
                  all_panels = tab_content_wrap.find_all("div", class_=lambda x: x and ("kt-inner-content" in " ".join(x) or "kt_inner_content" in " ".join(x)))
                  if not all_panels:
                    # If no specific classes, get all direct children divs
                    all_panels = [child for child in tab_content_wrap.children if hasattr(child, 'name') and child.name == 'div']
                  title_index = tab_title_items.index(title_item)
                  if 0 <= title_index < len(all_panels):
                    content_panel = all_panels[title_index]
                    # Try to extract tab number from class if not already set
                    if not tab_number and content_panel:
                      classes = content_panel.get("class", [])
                      class_str = " ".join(str(c) for c in classes)
                      if "kt-inner-tab" in class_str:
                        try:
                          # Pattern 1: "kt-inner-tab-1"
                          if "kt-inner-tab-" in class_str:
                            parts = class_str.split("kt-inner-tab-")
                            for part in parts[1:]:  # Check all occurrences
                              num_part = part.split("-")[0].split(" ")[0]
                              if num_part.isdigit():
                                tab_number = int(num_part)
                                break
                          # Pattern 2: "kt-inner-tabbfaddd-31" (extract number after last dash)
                          if not tab_number:
                            match = re.search(r'kt-inner-tab[^-]*-(\d+)', class_str)
                            if match:
                              tab_number = int(match.group(1))
                        except (ValueError, IndexError, AttributeError):
                          pass
                
                # Only add if we have both a valid label (not a class name) and content panel
                if content_panel and tab_label and tab_label.strip():
                  # Validate that tab_label is not a class name
                  # Class names typically don't have spaces and are lowercase with underscores/hyphens
                  # Real tab titles should have readable text
                  if " " in tab_label or tab_label[0].isupper() or len(tab_label) > 3:
                    section_key = normalize_key(tab_label)
                    # Make sure we're not using a class name as the key
                    if section_key not in ["kt_inner_content", "kt_inner_content_inner", "kt_tab_content"]:
                      detected_tabs[section_key] = {
                        "element": content_panel,
                        "label": tab_label,
                        "id": tab_id,
                        "tab_number": tab_number
                      }
            
            # Strategy 1: Look for elements with role="tabpanel"
            tab_panels = soup.find_all(attrs={"role": "tabpanel"})
            for panel in tab_panels:
              # Get tab label from aria-labelledby or aria-label
              tab_label = None
              aria_labelledby = panel.get("aria-labelledby")
              if aria_labelledby:
                label_el = soup.find(id=aria_labelledby)
                if label_el:
                  tab_label = label_el.get_text(strip=True)
              if not tab_label:
                tab_label = panel.get("aria-label", "")
              if not tab_label:
                # Try to get from id
                panel_id = panel.get("id", "")
                if panel_id:
                  tab_label = panel_id.replace("tab-", "").replace("-", " ").replace("_", " ")
              
              if tab_label:
                section_key = normalize_key(tab_label)
                detected_tabs[section_key] = {
                  "element": panel,
                  "label": tab_label,
                  "id": panel.get("id", "")
                }
            
            # Strategy 2: Look for common tab container classes (only if Kadence tabs weren't found)
            # Skip this strategy if we already found tabs via Kadence (Strategy 0)
            if not detected_tabs:
              tab_selectors = [
                ".kt-tab-inner-content",
                ".tab-content",
                ".tab-pane",
                "[class*='tab-panel']",
                "[class*='tab-content']",
                "[class*='tab-inner']"
              ]
              
              for selector in tab_selectors:
                tab_elements = soup.select(selector)
                for tab_el in tab_elements:
                  # Try to identify tab by various attributes
                  tab_id = tab_el.get("id", "")
                  
                  # Get label from id or first heading (NOT from class names)
                  tab_label = None
                  if tab_id and "tab-" in tab_id:
                    # Extract label from id (e.g., "tab-overview" -> "overview")
                    tab_label = tab_id.replace("tab-", "").replace("tab_", "").replace("-", " ").replace("_", " ")
                  
                  # Prioritize: use first heading in the tab
                  first_heading = tab_el.find(["h1", "h2", "h3", "h4", "h5", "h6"])
                  if first_heading:
                    heading_text = first_heading.get_text(strip=True)
                    if heading_text and len(heading_text) > 2:
                      tab_label = heading_text
                  
                  # Validate that tab_label is not a class name
                  if tab_label:
                    # Filter out class-name-like labels (all lowercase with underscores, no spaces)
                    normalized = tab_label.lower().replace(" ", "").replace("-", "_")
                    if normalized in ["kt_inner_content", "kt_inner_content_inner", "kt_tab_content", "inner_content"]:
                      tab_label = None
                    # Also check if it looks like a class name (all lowercase, underscores/hyphens only)
                    elif not " " in tab_label and tab_label.islower() and (tab_label.count("_") > 0 or tab_label.count("-") > 0):
                      tab_label = None
                  
                  if tab_label:
                    section_key = normalize_key(tab_label)
                    # Only add if we haven't seen this tab already and it's not a class name
                    if section_key not in detected_tabs and section_key not in ["kt_inner_content", "kt_inner_content_inner"]:
                      detected_tabs[section_key] = {
                        "element": tab_el,
                        "label": tab_label,
                        "id": tab_id
                      }
            
            # Strategy 3: Look for tab navigation links and match to panels
            tab_nav_links = soup.select("a[role='tab'], button[role='tab'], .tab-link, [class*='tab-link'], [class*='tab-button']")
            for nav_link in tab_nav_links:
              link_text = nav_link.get_text(strip=True)
              if not link_text:
                continue
              
              # Find associated panel
              link_href = nav_link.get("href", "")
              link_aria_controls = nav_link.get("aria-controls", "")
              
              # Try to find panel by href fragment or aria-controls
              panel = None
              if link_href and "#" in link_href:
                panel_id = link_href.split("#")[-1]
                panel = soup.find(id=panel_id)
              elif link_aria_controls:
                panel = soup.find(id=link_aria_controls)
              
              if panel:
                section_key = normalize_key(link_text)
                if section_key not in detected_tabs:
                  detected_tabs[section_key] = {
                    "element": panel,
                    "label": link_text,
                    "id": panel.get("id", "")
                  }
            
            return detected_tabs
          
          # Detect all tabs on the page
          detected_tabs = detect_tabs(detail_soup)
          print(f"  Detected {len(detected_tabs)} tabs: {list(detected_tabs.keys())}")
          
          # Extract content directly from tab panels
          # Find all wp-block-kadence-tab divs (these are the tab panels)
          print(f"  Extracting content from tab panels...")
          
          # Helper function to extract tab number from classes
          def extract_tab_number(classes):
            """Extract tab number from a list of classes."""
            if isinstance(classes, list):
              class_list = [str(c) for c in classes]
            else:
              class_list = [str(classes)]
            
            print(f"      Extracting tab number from classes: {class_list}")
            
            for cls in class_list:
              if "kt-inner-tab-" in cls:
                # Pattern 1: "kt-inner-tab-1" (simple number)
                parts = cls.split("kt-inner-tab-")
                if len(parts) > 1:
                  remainder = parts[1]
                  print(f"        Found 'kt-inner-tab-' in '{cls}', remainder: '{remainder}'")
                  # Try simple number first (e.g., "1")
                  if remainder and remainder[0].isdigit():
                    num_part = ""
                    for char in remainder:
                      if char.isdigit():
                        num_part += char
                      else:
                        break
                    if num_part:
                      tab_num = int(num_part)
                      print(f"        Extracted tab number: {tab_num} (simple pattern)")
                      return tab_num
                  
                  # Try hash-number pattern (e.g., "bfaddd-31")
                  match = re.search(r'(\d+)', remainder)
                  if match:
                    tab_num = int(match.group(1))
                    print(f"        Extracted tab number: {tab_num} (hash pattern)")
                    return tab_num
            print(f"      Could not extract tab number")
            return None
          
          # Find all tab panels directly
          # Look for divs with wp-block-kadence-tab class
          tab_panels = detail_soup.find_all("div", class_=lambda x: x and "wp-block-kadence-tab" in " ".join(x))
          print(f"  Found {len(tab_panels)} tab panels with 'wp-block-kadence-tab' class")
          
          # If none found, try alternative selector
          if not tab_panels:
            tab_panels = detail_soup.select("div.wp-block-kadence-tab")
            print(f"  Found {len(tab_panels)} tab panels using selector")
          
          # Debug: print classes of first few panels
          for i, panel in enumerate(tab_panels[:3]):
            panel_classes = panel.get("class", [])
            print(f"    Panel {i+1} classes: {panel_classes}")
          
          # Group sections by tab
          sections_by_tab = {}  # {tab_key: {sections: [{title, content}], tab_info: {...}}}
          
          # Process each tab panel
          for tab_panel in tab_panels:
            # Extract tab number from the tab panel's classes
            tab_panel_classes = tab_panel.get("class", [])
            tab_number = extract_tab_number(tab_panel_classes)
            
            if tab_number is None:
              print(f"    Warning: Could not extract tab number from panel classes: {tab_panel_classes}")
              continue
            
            # Find the corresponding tab info from detected_tabs
            parent_tab_key = None
            for tab_key, tab_info in detected_tabs.items():
              if tab_info.get("tab_number") == tab_number:
                parent_tab_key = tab_key
                break
            
            # If no matching tab found, create a generic key
            if not parent_tab_key:
              parent_tab_key = f"tab_{tab_number}"
              print(f"    Warning: No detected tab found for tab number {tab_number}, using '{parent_tab_key}'")
            
            # Find all cpc-title-content sections within this tab panel
            # Search within the kt-tab-inner-content-inner div
            inner_content = tab_panel.select_one(".kt-tab-inner-content-inner")
            search_root = inner_content if inner_content else tab_panel
            
            # Find all divs with cpc-title-content class
            all_cpc_divs = search_root.find_all("div")
            # Filter to get only the outer divs (not the inner wrapper)
            cpc_content_sections = []
            for div in all_cpc_divs:
              div_classes = div.get("class", [])
              if not div_classes:
                continue
              class_list = [str(c) for c in div_classes]
              class_str = " ".join(class_list)
              # Include if it has cpc-title-content but NOT cpc-title-content__inner
              if "cpc-title-content" in class_str and "cpc-title-content__inner" not in class_str:
                cpc_content_sections.append(div)
            
            print(f"    Tab {tab_number} ('{parent_tab_key}'): Found {len(cpc_content_sections)} cpc-title-content sections")
            
            # Debug if no sections found
            if len(cpc_content_sections) == 0:
              print(f"      Debug: Checking tab panel content...")
              if inner_content:
                all_divs_in_tab = inner_content.find_all("div")
                print(f"      Found {len(all_divs_in_tab)} divs in kt-tab-inner-content-inner")
                for i, div in enumerate(all_divs_in_tab[:10]):
                  div_classes = div.get("class", [])
                  if div_classes:
                    print(f"        Div {i+1} classes: {div_classes}")
            
            # Extract content from each cpc-title-content section in this tab
            for cpc_section in cpc_content_sections:
              # Look for title - it's an h2 with class cpc-title-content__title
              title_el = cpc_section.find("h2", class_=lambda x: x and "cpc-title-content__title" in " ".join(x))
              if not title_el:
                # Try alternative selector
                title_el = cpc_section.select_one("h2.cpc-title-content__title, .cpc-title-content__title")
              
              if not title_el:
                continue
              
              section_title = title_el.get_text(strip=True)
              section_key = normalize_key(section_title)
              
              # Look for content items div
              content_items = cpc_section.find("div", class_=lambda x: x and "cpc-title-content__items" in " ".join(x))
              if not content_items:
                # Try alternative selector
                content_items = cpc_section.select_one(".cpc-title-content__items")
              
              if not content_items:
                # If no items div found, try to get content from the inner div
                inner_div = cpc_section.find("div", class_=lambda x: x and "cpc-title-content__inner" in " ".join(x))
                if inner_div:
                  content_items = inner_div
                else:
                  # Last resort: use section itself
                  content_items = cpc_section
              
              # Extract content from this section
              content_copy = BeautifulSoup(str(content_items), "html.parser")
              
              # Remove navigation and non-content elements
              for nav in content_copy.select("nav, .pagerer, .social-share, button, .btn, script, style, .documents, .tab-nav, [class*='tab-list'], .kt-tabs-title-list"):
                nav.decompose()
              
              # Remove button blocks that are just links
              for button_block in content_copy.select(".wp-block-temper-blocks-button, .wp-block-button"):
                button_block.decompose()
              
              # Remove the section title if it's still in the content
              title_in_content = content_copy.find("h2", class_=lambda x: x and "cpc-title-content__title" in " ".join(x))
              if title_in_content:
                title_in_content.decompose()
              
              # Extract content with markdown formatting
              text_parts = []
              processed_elements = set()
              
              # Process all elements, converting headers to markdown
              for element in content_copy.descendants:
                if not hasattr(element, 'name') or id(element) in processed_elements:
                  continue
                
                if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                  header_text = element.get_text(strip=True)
                  if header_text:
                    # Convert HTML headers to markdown
                    level = int(element.name[1])  # h1 -> 1, h2 -> 2, etc.
                    markdown_header = '#' * level + ' ' + header_text
                    text_parts.append(markdown_header)
                    processed_elements.add(id(element))
                elif element.name == 'p':
                  para_text = element.get_text(strip=True)
                  if para_text and len(para_text) > 5:
                    text_parts.append(para_text)
                    processed_elements.add(id(element))
                elif element.name in ['li']:
                  # Only process if parent is ul/ol (to avoid duplicates)
                  parent = element.parent
                  if parent and parent.name in ['ul', 'ol'] and id(element) not in processed_elements:
                    li_text = element.get_text(strip=True)
                    if li_text and len(li_text) > 2:
                      text_parts.append('• ' + li_text)
                      processed_elements.add(id(element))
                elif element.name in ['ul', 'ol']:
                  # Process list items (already handled above via li)
                  pass
                elif element.name in ['div']:
                  # Check if div contains substantial content and hasn't been processed via children
                  div_text = element.get_text(strip=True)
                  if div_text and len(div_text) > 20:
                    # Only add if it's not already captured by child elements
                    children_processed = any(id(child) in processed_elements for child in element.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li']))
                    if not children_processed:
                      # Check if it's meaningful content (not just navigation)
                      if not any(skip in div_text.lower()[:50] for skip in ['skip', 'navigation', 'menu', 'cookie']):
                        text_parts.append(div_text)
                        processed_elements.add(id(element))
              
              # Combine all parts
              if text_parts:
                full_text = "\n\n".join(text_parts).strip()
              else:
                # Fallback: get all text if structured extraction didn't work
                full_text = content_copy.get_text(separator="\n", strip=True)
              
              # Clean up: remove duplicates while preserving order
              if full_text:
                lines = full_text.split("\n")
                seen_lines = set()
                unique_lines = []
                for line in lines:
                  line_stripped = line.strip()
                  if line_stripped and line_stripped not in seen_lines and len(line_stripped) > 2:
                    seen_lines.add(line_stripped)
                    unique_lines.append(line)
                full_text = "\n".join(unique_lines).strip()
            
              # Store the section with original title
              section_data = {
                "title": section_title,  # Original title for display
                "content": full_text if full_text and len(full_text) > 10 else ""
              }
              
              # Group by tab
              if parent_tab_key not in sections_by_tab:
                # Get tab info from detected_tabs or create a default
                if parent_tab_key in detected_tabs:
                  sections_by_tab[parent_tab_key] = {
                    "tab_info": detected_tabs[parent_tab_key],
                    "sections": []
                  }
                else:
                  sections_by_tab[parent_tab_key] = {
                    "tab_info": {"label": parent_tab_key.replace("_", " ").title(), "tab_number": tab_number},
                    "sections": []
                  }
              
              sections_by_tab[parent_tab_key]["sections"].append(section_data)
              print(f"      - Section '{section_title}': {len(section_data['content'])} characters")
              
              # Also store flat for summary extraction
              sections[section_key] = section_data
              
              # Use first section as summary if available
              if not summary_from_tab and section_key in ["overview", "summary"]:
                summary_from_tab = section_data["content"][:500] if len(section_data["content"]) > 500 else section_data["content"]
              elif not summary_from_tab and not sections.get("overview"):
                summary_from_tab = section_data["content"][:500] if len(section_data["content"]) > 500 else section_data["content"]
          
          # Convert sections_by_tab to the final sections structure
          # If we have tabs with sections, use the nested structure
          if sections_by_tab:
            # Store as nested structure: each tab contains its sections
            for tab_key, tab_data in sections_by_tab.items():
              tab_info = tab_data["tab_info"]
              tab_sections = tab_data["sections"]
              
              # Create a combined content for the tab (all sections within it)
              # But we'll store it as a nested structure
              sections[tab_key] = {
                "title": tab_info.get("label", tab_key.replace("_", " ").title()),
                "content": "",  # Will be empty, sections are nested
                "sections": tab_sections,  # Nested sections
                "is_tab": True
              }
              print(f"  Tab '{tab_key}': {len(tab_sections)} sections")
          
          # If we detected tabs but no cpc-content sections were found, still create empty sections for tabs
          elif detected_tabs and not sections:
            print(f"  No cpc-title-content sections found, creating empty sections for detected tabs...")
            for section_key, tab_info in detected_tabs.items():
              sections[section_key] = {
                "title": tab_info.get("label", section_key.replace("_", " ").title()),
                "content": "",
                "sections": [],
                "is_tab": True
              }
              print(f"    - {section_key}: Empty tab created")
          
          # If no tab sections found, extract from main page content
          if not sections:
            print(f"  No tabs found, extracting content from main page...")
            if detail_desc_el:
              # Look for headings (h2, h3) to identify sections
              headings = detail_desc_el.find_all(["h2", "h3"])
              current_section = None
              current_content = []
              
              for element in detail_desc_el.descendants:
                if element.name in ["h2", "h3"]:
                  # Save previous section
                  if current_section and current_content:
                    sections[current_section] = "\n".join(current_content).strip()
                  # Start new section
                  heading_text = element.get_text(strip=True).lower()
                  current_section = None
                  if "overview" in heading_text or "summary" in heading_text:
                    current_section = "overview"
                  elif "challenge" in heading_text:
                    current_section = "challenge"
                  elif "ipec" in heading_text:
                    current_section = "ipec"
                  elif "date" in heading_text or "timeline" in heading_text:
                    current_section = "dates"
                  elif "apply" in heading_text or "application" in heading_text:
                    current_section = "how_to_apply"
                  elif "eligibility" in heading_text:
                    current_section = "eligibility"
                  elif "funding" in heading_text:
                    current_section = "funding"
                  else:
                    current_section = "other"
                  current_content = []
                elif element.name in ["p", "div", "li"] and current_section:
                  text = element.get_text(strip=True)
                  if text:
                    current_content.append(text)
              
              # Save last section
              if current_section and current_content:
                sections[current_section] = "\n".join(current_content).strip()
                
                # If we got sections from headings, use markdown formatting
                if sections:
                  formatted_sections = {}
                  for sec_key, sec_content in sections.items():
                    # Convert to markdown if needed
                    formatted_sections[sec_key] = sec_content
                  sections = formatted_sections
                  print(f"  Extracted {len(sections)} sections from page headings")
          
          # If we still have no sections, use the full description as overview
          if not sections:
            if description:
              sections["overview"] = description
              summary_from_tab = description[:500] if len(description) > 500 else description
              print(f"  Using full description as overview ({len(description)} characters)")
            elif detail_desc_el:
              # Last resort: extract all text from main content area with markdown formatting
              content_copy = BeautifulSoup(str(detail_desc_el), "html.parser")
              # Remove navigation
              for nav in content_copy.select("nav, .pagerer, .social-share, button, .btn, script, style, .documents, .tab-nav, [class*='tab-list']"):
                nav.decompose()
              
              text_parts = []
              for element in content_copy.descendants:
                if not hasattr(element, 'name'):
                  continue
                if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                  header_text = element.get_text(strip=True)
                  if header_text:
                    level = int(element.name[1])
                    markdown_header = '#' * level + ' ' + header_text
                    text_parts.append(markdown_header)
                elif element.name == 'p':
                  para_text = element.get_text(strip=True)
                  if para_text and len(para_text) > 5:
                    text_parts.append(para_text)
                elif element.name in ['li']:
                  parent = element.parent
                  if parent and parent.name in ['ul', 'ol']:
                    li_text = element.get_text(strip=True)
                    if li_text and len(li_text) > 2:
                      text_parts.append('• ' + li_text)
              
              if text_parts:
                full_text = "\n\n".join(text_parts).strip()
                sections["overview"] = full_text
                summary_from_tab = full_text[:500] if len(full_text) > 500 else full_text
                print(f"  Extracted overview from page content ({len(full_text)} characters)")
          
          # Extract funding amount from detail page
          funding_amount = None
          page_text = detail_soup.get_text()
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
        except Exception as e:
          print(f"Error fetching detail page for {url}: {e}")
          # Continue with data from listing page
        
        # Use Summary from tab if available, otherwise use description summary
        final_summary = summary_from_tab if summary_from_tab else (description[:200] + "..." if len(description) > 200 else description)
        
        # Format description with section headings for better readability
        formatted_description = description
        if sections:
          # Build formatted description with clear section headings
          formatted_parts = []
          section_order = ["overview", "challenge", "eligibility", "ipec", "funding", "dates", "how_to_apply", "other"]
          
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
            "source": "catapult",
            "title": title,
            "url": url,
            "summary": final_summary,
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
    
    print(f"Successfully scraped {len(grants)} Catapult opportunities")
    if all_grant_data:
      print(f"  - New grants found: {new_count}")
      print(f"  - Existing grants re-checked: {existing_count_in_listing}")
    print(f"  - Note: Django will skip unchanged grants based on hash_checksum comparison")
    return grants

  except Exception as e:
    error_msg = f"Catapult scraper failed: {str(e)}"
    print(error_msg)
    raise Exception(error_msg) from e

