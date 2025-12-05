"""
HTTP client utilities for making browser-like requests.
"""
import time
from typing import Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def create_session() -> requests.Session:
    """
    Creates a requests Session with browser-like headers and retry logic.
    """
    session = requests.Session()
    
    # Browser-like headers to avoid 403 errors
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    })
    
    # Retry strategy for transient errors
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session


def fetch_with_retry(
    session: requests.Session,
    url: str,
    referer: Optional[str] = None,
    timeout: int = 30,
    max_retries: int = 3
) -> requests.Response:
    """
    Fetches a URL with retry logic and proper error handling.
    
    Args:
        session: requests.Session instance
        url: URL to fetch
        referer: Optional referer header
        timeout: Request timeout in seconds
        max_retries: Maximum number of retries
        
    Returns:
        requests.Response object
        
    Raises:
        requests.exceptions.HTTPError: If the request fails after retries
    """
    headers = {}
    if referer:
        headers["Referer"] = referer
    
    for attempt in range(max_retries):
        try:
            response = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                # For 403, try with a delay and different approach
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # Exponential backoff: 2s, 4s, 6s
                    print(f"Got 403 Forbidden for {url}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    # Try visiting the homepage first to establish session
                    if attempt == 1:
                        try:
                            base_url = "/".join(url.split("/")[:3])
                            session.get(base_url, timeout=10)
                            time.sleep(1)
                        except:
                            pass
                    continue
                else:
                    raise Exception(f"403 Forbidden after {max_retries} attempts. The website may be blocking automated requests. URL: {url}")
            else:
                raise
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                print(f"Request error for {url}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
                continue
            else:
                raise Exception(f"Request failed after {max_retries} attempts: {str(e)}")
    
    raise Exception(f"Failed to fetch {url} after {max_retries} attempts")

