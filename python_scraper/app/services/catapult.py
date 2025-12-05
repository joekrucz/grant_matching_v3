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
    
    # For open calls, use Selenium if available to handle JavaScript pagination
    # For closed calls, use regular requests
    selenium_worked = False
    if SELENIUM_AVAILABLE:
      print("Using Selenium for JavaScript pagination...")
      try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(30)
        
        # Fetch open calls with pagination
        print("Fetching open Catapult opportunities with Selenium...")
        driver.get("https://cp.catapult.org.uk/open-calls/?status=open")
        time.sleep(2)  # Wait for JavaScript to load
        
        # Get page 1 grants
        soup = BeautifulSoup(driver.page_source, "html.parser")
        grant_links = soup.select("a h2")
        for h2 in grant_links:
          link_el = h2.find_parent("a")
          if link_el and "/opportunity/" in link_el.get("href", ""):
            href = link_el.get("href", "")
            if href.startswith("/"):
              href = f"https://cp.catapult.org.uk{href}"
            title = h2.get_text(strip=True)
            if not title.startswith("Closed:") and href not in seen_urls:
              seen_urls.add(href)
              all_grant_data.append((h2, href, title))
        
        print(f"  Page 1: Found {len(all_grant_data)} grants")
        
        # Try to navigate to page 2 using FacetWP pagination
        try:
          # Wait for FacetWP to load
          WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a h2"))
          )
          
          # Look for page 2 link in pagination
          page2_selectors = [
            "a[href*='paged=2']",
            ".facetwp-pager a[href*='2']",
            ".page-numbers a[href*='2']",
            "a:contains('2')",
          ]
          
          page2_link = None
          for selector in page2_selectors:
            try:
              if ":contains" in selector:
                # Use XPath for text contains
                page2_link = driver.find_element(By.XPATH, "//a[contains(text(), '2')]")
              else:
                page2_link = driver.find_element(By.CSS_SELECTOR, selector)
              if page2_link:
                break
            except:
              continue
          
          if page2_link:
            # Scroll to element and click
            driver.execute_script("arguments[0].scrollIntoView(true);", page2_link)
            time.sleep(1)
            page2_link.click()
            time.sleep(4)  # Wait for FacetWP to load page 2 content
            
            soup2 = BeautifulSoup(driver.page_source, "html.parser")
            grant_links2 = soup2.select("a h2")
            page2_count = 0
            for h2 in grant_links2:
              link_el = h2.find_parent("a")
              if link_el and "/opportunity/" in link_el.get("href", ""):
                href = link_el.get("href", "")
                if href.startswith("/"):
                  href = f"https://cp.catapult.org.uk{href}"
                title = h2.get_text(strip=True)
                if not title.startswith("Closed:") and href not in seen_urls:
                  seen_urls.add(href)
                  all_grant_data.append((h2, href, title))
                  page2_count += 1
            
            print(f"  Page 2: Found {page2_count} new grants")
          else:
            print("  Could not find page 2 link")
        except Exception as e:
          print(f"  Could not navigate to page 2: {e}")
        
        driver.quit()
        selenium_worked = True
      except Exception as e:
        print(f"Selenium failed, falling back to requests: {e}")
        selenium_worked = False
    
    # Fallback to regular requests if Selenium not available or failed
    # Only fetch open grants if we didn't get 7 from Selenium
    open_grant_count = len(all_grant_data)  # Count all grants found so far
    if not selenium_worked or open_grant_count < 7:
      # Check both open and closed calls, with pagination
      statuses = ["open", "closed"]
      
      for status in statuses:
        # Skip open if we already got 7+ grants from Selenium
        if status == "open":
          open_count = len([d for d in all_grant_data])
          if open_count >= 7:
            continue  # Already got open grants with Selenium
        
        print(f"Fetching {status} Catapult opportunities...")
        page = 1
        max_pages = 5  # Limit to prevent infinite loops
        
        while page <= max_pages:
          # Try different pagination URL patterns
          pagination_urls = [
            f"https://cp.catapult.org.uk/open-calls/?status={status}&paged={page}",
            f"https://cp.catapult.org.uk/open-calls/?status={status}&page={page}",
            f"https://cp.catapult.org.uk/open-calls/page/{page}/?status={status}" if page > 1 else f"https://cp.catapult.org.uk/open-calls/?status={status}",
          ]
          
          page_found = False
          for url in pagination_urls:
            try:
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
                # Skip "Closed:" prefix if present (we'll handle status separately)
                if title.startswith("Closed:"):
                  title = title.replace("Closed:", "").strip()
                
                seen_urls.add(href)
                all_grant_data.append((h2, href, title))
                new_grants_on_page += 1
              
              if new_grants_on_page > 0:
                print(f"  Page {page}: Found {new_grants_on_page} new grants")
                page_found = True
                break  # Found grants on this URL pattern, move to next page
              elif page == 1:
                # On first page, try next URL pattern
                continue
              else:
                # No new grants, might be end of pagination
                break
            except Exception as e:
              # Try next URL pattern
              continue
          
          if not page_found and page > 1:
            # No grants found on this page, stop pagination
            break
          
          page += 1
    
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
          
          # Extract Summary section from tab content (if available)
          summary_from_tab = None
          # Look for Summary tab content - it's in a div with kt-tab-inner-content and kt-inner-tab-1 classes
          summary_tab_content = detail_soup.select_one(
              ".kt-tab-inner-content.kt-inner-tab-1, "
              "[class*='kt-tab-inner-content'][class*='kt-inner-tab-1']"
          )
          if summary_tab_content:
            # Get the text content
            summary_text = summary_tab_content.get_text("\n", strip=True)
            # Remove "Overview" heading if present at the start
            if summary_text.startswith("Overview"):
              summary_text = summary_text.replace("Overview", "", 1).strip()
            # Stop at next major section (Challenge, IPEC, etc.) if present
            for section in ["Challenge", "IPEC", "Dates", "How to apply"]:
              if section in summary_text:
                summary_text = summary_text.split(section)[0].strip()
                break
            summary_from_tab = summary_text
          
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
        
        grant: Dict[str, Any] = {
            "source": "catapult",
            "title": title,
            "url": url,
            "summary": final_summary,
            "description": description,
            "deadline": parse_deadline(deadline_raw) if deadline_raw else None,
            "funding_amount": funding_amount,
            "status": "open",
            "raw_data": {"listing_url": listing_url, "scraped_url": url},
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

