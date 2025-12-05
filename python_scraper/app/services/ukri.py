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
        
        # Extract description
        desc_el = (
            detail_soup.select_one("main") or
            detail_soup.select_one(".content") or
            detail_soup.select_one("article") or
            detail_soup.select_one("div[class*='description']")
        )
        description = desc_el.get_text("\n", strip=True) if desc_el else ""
        
        # Extract summary from meta description or first paragraph
        summary_el = detail_soup.select_one("meta[name='description']")
        summary = summary_el["content"] if summary_el and summary_el.get("content") else (description[:200] + "..." if len(description) > 200 else description)
        
        # Extract deadline
        deadline_raw = None
        deadline_patterns = [
            r"deadline[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"closing[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"(\d{1,2}\s+\w+\s+\d{2,4})",
            r"closes?\s+(\d{1,2}\s+\w+\s+\d{2,4})",
        ]
        page_text = detail_soup.get_text()
        for pattern in deadline_patterns:
          match = re.search(pattern, page_text, re.IGNORECASE)
          if match:
            deadline_raw = match.group(1)
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
        
        grant: Dict[str, Any] = {
            "source": "ukri",
            "title": title,
            "url": url,
            "summary": summary,
            "description": description,
            "deadline": parse_deadline(deadline_raw) if deadline_raw else None,
            "funding_amount": funding_amount,
            "status": "open",
            "raw_data": {"listing_url": base_url, "scraped_url": url},
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

