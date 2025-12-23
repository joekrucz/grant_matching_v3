"""
Companies House API service and Grant Matching service.
"""
import json
import time
import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from openai import OpenAI, RateLimitError, APIError


class CompaniesHouseError(Exception):
    """Custom exception for Companies House API errors."""
    pass


class ThreeSixtyGivingError(Exception):
    """Custom exception for 360Giving API errors."""
    pass


class GrantMatchingError(Exception):
    """Custom exception for grant matching errors."""
    pass


class CompaniesHouseService:
    """Service to interact with Companies House API."""
    
    BASE_URL = "https://api.company-information.service.gov.uk"
    
    @classmethod
    def search_companies(cls, query, items_per_page=20):
        """
        Search companies by name using Companies House API.
        
        Args:
            query: Company name to search for
            items_per_page: Number of results to return (max 100, default 20)
            
        Returns:
            list: List of company search results with company_number, title, etc.
            
        Raises:
            CompaniesHouseError: If API request fails
        """
        api_key = settings.COMPANIES_HOUSE_API_KEY
        if not api_key:
            raise CompaniesHouseError("COMPANIES_HOUSE_API_KEY not configured")
        
        if not query or len(query.strip()) < 2:
            return []
        
        url = f"{cls.BASE_URL}/search/companies"
        from requests.auth import HTTPBasicAuth
        
        params = {
            'q': query.strip(),
            'items_per_page': min(items_per_page, 100)  # API max is 100
        }
        
        try:
            response = requests.get(
                url,
                auth=HTTPBasicAuth(api_key, ''),
                params=params,
                timeout=10
            )
            
            if response.status_code == 401:
                raise CompaniesHouseError("Invalid API key")
            elif response.status_code != 200:
                raise CompaniesHouseError(f"API error: {response.status_code} - {response.text}")
            
            data = response.json()
            items = data.get('items', [])
            
            # Format results for easier use
            results = []
            for item in items[:items_per_page]:  # Limit to requested number
                results.append({
                    'company_number': item.get('company_number', ''),
                    'title': item.get('title', ''),
                    'company_status': item.get('company_status', ''),
                    'company_type': item.get('company_type', ''),
                    'address_snippet': item.get('address_snippet', ''),
                    'date_of_creation': item.get('date_of_creation', ''),
                })
            
            return results
        except requests.exceptions.RequestException as e:
            raise CompaniesHouseError(f"Search request failed: {str(e)}")
    
    @classmethod
    def fetch_company(cls, company_number):
        """
        Fetch company data from Companies House API.
        
        Args:
            company_number: Companies House company number
            
        Returns:
            dict: Company data from API
            
        Raises:
            CompaniesHouseError: If API request fails
        """
        api_key = settings.COMPANIES_HOUSE_API_KEY
        if not api_key:
            raise CompaniesHouseError("COMPANIES_HOUSE_API_KEY not configured")
        
        url = f"{cls.BASE_URL}/company/{company_number}"
        # Companies House API uses basic auth with API key as username and empty password
        from requests.auth import HTTPBasicAuth
        
        try:
            response = requests.get(url, auth=HTTPBasicAuth(api_key, ''), timeout=10)
            
            if response.status_code == 404:
                raise CompaniesHouseError(f"Company {company_number} not found")
            elif response.status_code == 401:
                raise CompaniesHouseError("Invalid API key")
            elif response.status_code != 200:
                raise CompaniesHouseError(f"API error: {response.status_code} - {response.text}")
            
            return response.json()
        except requests.exceptions.RequestException as e:
            raise CompaniesHouseError(f"Request failed: {str(e)}")
    
    @classmethod
    def fetch_filing_history(cls, company_number, items_per_page=100):
        """
        Fetch filing history from Companies House API.
        
        Args:
            company_number: Companies House company number
            items_per_page: Number of items per page (max 100, default 100)
            
        Returns:
            dict: Filing history data from API with 'items' list and pagination info
            
        Raises:
            CompaniesHouseError: If API request fails
        """
        api_key = settings.COMPANIES_HOUSE_API_KEY
        if not api_key:
            raise CompaniesHouseError("COMPANIES_HOUSE_API_KEY not configured")
        
        url = f"{cls.BASE_URL}/company/{company_number}/filing-history"
        from requests.auth import HTTPBasicAuth
        
        all_items = []
        start_index = 0
        items_per_page = min(items_per_page, 100)  # API max is 100
        
        try:
            while True:
                params = {
                    'items_per_page': items_per_page,
                    'start_index': start_index
                }
                response = requests.get(
                    url, 
                    auth=HTTPBasicAuth(api_key, ''), 
                    params=params,
                    timeout=10
                )
                
                if response.status_code == 404:
                    # Company not found or no filing history
                    break
                elif response.status_code == 401:
                    raise CompaniesHouseError("Invalid API key")
                elif response.status_code != 200:
                    raise CompaniesHouseError(f"API error: {response.status_code} - {response.text}")
                
                data = response.json()
                items = data.get('items', [])
                all_items.extend(items)
                
                # Check if there are more pages
                total_count = data.get('total_count', 0)
                if start_index + len(items) >= total_count or len(items) < items_per_page:
                    break
                
                start_index += items_per_page
                # Small delay to respect rate limits
                time.sleep(0.5)
            
            return {
                'items': all_items,
                'total_count': len(all_items),
                'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S')
            }
        except requests.exceptions.RequestException as e:
            raise CompaniesHouseError(f"Filing history request failed: {str(e)}")
    
    @staticmethod
    def normalize_company_data(api_response, filing_history=None):
        """
        Normalize Companies House API response to model fields.
        
        Args:
            api_response: Raw API response dict
            filing_history: Optional filing history data dict
            
        Returns:
            dict: Normalized company data
        """
        address = {}
        if 'registered_office_address' in api_response:
            addr = api_response['registered_office_address']
            address = {
                'address_line_1': addr.get('address_line_1', ''),
                'address_line_2': addr.get('address_line_2', ''),
                'locality': addr.get('locality', ''),
                'postal_code': addr.get('postal_code', ''),
                'country': addr.get('country', ''),
            }
        
        sic_codes = api_response.get('sic_codes', [])
        sic_codes_str = ', '.join(sic_codes) if sic_codes else ''
        
        normalized = {
            'company_number': api_response.get('company_number', ''),
            'name': api_response.get('company_name', ''),
            'company_type': api_response.get('company_type', ''),
            'status': api_response.get('company_status', ''),
            'sic_codes': sic_codes_str,
            'address': address,
            'date_of_creation': api_response.get('date_of_creation', ''),
            'raw_data': api_response,
        }
        
        # Add filing history if provided
        if filing_history:
            normalized['filing_history'] = filing_history
        
        return normalized


class ThreeSixtyGivingService:
    """Service to interact with the 360Giving API."""

    BASE_URL = "https://api.threesixtygiving.org/api/v1"
    RATE_LIMIT_DELAY = 0.6  # API allows 2 req/s

    @classmethod
    def org_id_from_company_number(cls, company_number):
        """
        Build a 360Giving Org ID from a Companies House number.

        The API expects the GB-COH-{number} format, zero-padded to 8 digits.
        """
        if not company_number:
            raise ThreeSixtyGivingError("Company number is required to build Org ID")

        # Do not double-prefix if an Org ID was already provided
        if str(company_number).startswith("GB-COH-"):
            return str(company_number)

        clean_number = str(company_number).strip()
        padded_number = clean_number.zfill(8)
        return f"GB-COH-{padded_number}"

    @classmethod
    def fetch_grants_received(cls, company_number, limit=100):
        """
        Fetch grants received by an organisation from the 360Giving API.

        Args:
            company_number: Companies House company number
            limit: Page size for API pagination (max 100)

        Returns:
            dict: {
                "org_id": "GB-COH-00000000",
                "count": int,
                "grants": [...],
                "fetched_at": iso_timestamp,
                "source_url": str
            }

        Raises:
            ThreeSixtyGivingError: If API request fails
        """
        org_id = cls.org_id_from_company_number(company_number)
        page_limit = min(limit, 100)
        url = f"{cls.BASE_URL}/org/{org_id}/grants_received/"
        params = {"limit": page_limit, "offset": 0}

        grants = []
        count = None
        source_url = url

        try:
            while True:
                response = requests.get(url, params=params, timeout=10)

                if response.status_code == 404:
                    raise ThreeSixtyGivingError(f"Organisation {org_id} not found in 360Giving")
                if response.status_code == 429:
                    # Back off and retry respecting the 2 rps guideline
                    time.sleep(1.2)
                    continue
                if response.status_code >= 400:
                    raise ThreeSixtyGivingError(
                        f"360Giving API error: {response.status_code} - {response.text}"
                    )

                data = response.json()
                if count is None:
                    count = data.get("count")

                page_grants = data.get("results") or data.get("grants") or data.get("data") or []
                # Normalize each grant to a simpler structure for templates/UI
                for grant in page_grants:
                    grants.append(cls._normalize_grant(grant))

                next_url = data.get("next")
                if not next_url:
                    break

                # Support both absolute and relative next URLs
                if next_url.startswith("http"):
                    url = next_url
                    params = {}
                else:
                    url = f"{cls.BASE_URL}{next_url}"
                    params = {}

                time.sleep(cls.RATE_LIMIT_DELAY)

            return {
                "org_id": org_id,
                "count": count if count is not None else len(grants),
                "grants": cls._sort_grants(grants),
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "source_url": source_url,
            }
        except requests.exceptions.RequestException as exc:
            raise ThreeSixtyGivingError(f"360Giving request failed: {str(exc)}")

    @staticmethod
    def _normalize_grant(grant):
        """
        Flatten 360Giving grant payload to the fields we display.
        """
        data = grant.get("data", {}) if isinstance(grant, dict) else {}

        # Funder: take first fundingOrganization name if present
        funder_name = None
        funders = data.get("fundingOrganization") or []
        if isinstance(funders, list) and funders:
            funder_name = funders[0].get("name")

        # Normalize award date to YYYY-MM-DD if parseable
        award_date_raw = data.get("awardDate")
        award_date_clean = ThreeSixtyGivingService._format_date(award_date_raw)

        return {
            "id": grant.get("grant_id") or data.get("id"),
            "title": data.get("title"),
            "description": ThreeSixtyGivingService._clean_text(data.get("description")),
            "amountAwarded": data.get("amountAwarded"),
            "awardDate": award_date_clean,
            "funder": funder_name,
            "raw": grant,
        }

    @staticmethod
    def _sort_grants(grants):
        """
        Sort grants by awardDate descending when available.
        """
        def parse_date(g):
            from datetime import datetime
            val = g.get("awardDate")
            if not val:
                return None
            # Try ISO first
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(val, fmt)
                except Exception:
                    continue
            return None

        return sorted(grants, key=lambda g: parse_date(g) or "", reverse=True)

    @staticmethod
    def _format_date(date_val):
        """
        Return YYYY-MM-DD if the string looks like an ISO datetime/date, else original.
        """
        if not date_val or not isinstance(date_val, str):
            return date_val
        # If already just a date
        if len(date_val) == 10 and date_val[4] == '-' and date_val[7] == '-':
            return date_val
        # Try to parse common ISO formats
        from datetime import datetime
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ"):
            try:
                return datetime.strptime(date_val, fmt).strftime("%Y-%m-%d")
            except Exception:
                continue
        return date_val

    @staticmethod
    def _clean_text(text_val):
        """
        Trim leading/trailing whitespace and collapse leading tabs/spaces.
        """
        if not text_val or not isinstance(text_val, str):
            return text_val
        return text_val.strip()


class ChatGPTMatchingService:
    """Service to match grants using ChatGPT API."""
    
    def __init__(self):
        api_key = getattr(settings, 'OPENAI_API_KEY', None)
        if not api_key:
            raise GrantMatchingError("OPENAI_API_KEY not configured")
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4o-mini"  # Cost-effective model
        self.batch_size = 10  # Process 10 grants per API call
    
    def format_grant_for_batch(self, grant_data, index):
        """Format a single grant for batch prompt."""
        deadline_str = grant_data.get('deadline', 'N/A')
        if deadline_str and deadline_str != 'N/A':
            try:
                from django.utils.dateparse import parse_datetime
                dt = parse_datetime(str(deadline_str))
                if dt:
                    deadline_str = dt.strftime('%d %B %Y')
            except:
                pass
        
        return f"""
Grant #{index + 1}:
- Title: {grant_data['title']}
- Source: {grant_data['source']}
- Summary: {grant_data.get('summary', 'N/A')[:200]}
- Description: {grant_data.get('description', 'N/A')[:500]}
- Funding: {grant_data.get('funding_amount', 'N/A')}
- Deadline: {deadline_str}
- Status: {grant_data.get('status', 'unknown')}
"""
    
    def match_grants_batch(self, project_description, grants_batch):
        """
        Match a batch of grants (10 at a time) against project.
        Returns list of match results.
        """
        grants_text = "\n".join([
            self.format_grant_for_batch(grant, idx) 
            for idx, grant in enumerate(grants_batch)
        ])
        
        prompt = f"""You are an expert grant matching assistant. Analyze how well a research project aligns with {len(grants_batch)} funding opportunities.

PROJECT DESCRIPTION:
{project_description}

FUNDING OPPORTUNITIES:
{grants_text}

For EACH grant, provide:
1. Match score: A float from 0.0 to 1.0 (1.0 = perfect match, 0.0 = no match)
2. Explanation: 2-3 sentences explaining the match quality
3. Top 3 alignment points: What matches well
4. Top 2 concerns: Potential issues or mismatches

IMPORTANT: Respond with a valid JSON object containing an array called "matches" with exactly {len(grants_batch)} items.

Format:
{{
    "matches": [
        {{
            "grant_index": 0,
            "score": 0.85,
            "explanation": "This grant is highly relevant because...",
            "alignment_points": ["Both focus on AI", "TRL levels align", "Deadline is feasible"],
            "concerns": ["May need additional partners", "Budget might be tight"]
        }},
        {{
            "grant_index": 1,
            "score": 0.45,
            "explanation": "...",
            "alignment_points": [...],
            "concerns": [...]
        }},
        ...
    ]
}}
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "You are a grant matching expert. Always respond with valid JSON. Be precise with scores."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower for consistent scoring
                response_format={"type": "json_object"},
                max_tokens=4000,  # Enough for 10 grants with explanations
            )
            
            result = json.loads(response.choices[0].message.content)
            return result.get('matches', [])
            
        except (RateLimitError, APIError) as e:
            # Will be handled by retry logic
            raise
    
    def match_all_grants(self, project_description, grants_data, progress_callback=None):
        """
        Match all grants in batches with retry logic.
        
        Args:
            project_description: Project text to match against
            grants_data: List of grant dicts
            progress_callback: Optional function(current, total) for progress updates
        
        Returns:
            List of match results with grant_index, score, explanation, etc.
        """
        all_results = []
        total_batches = (len(grants_data) + self.batch_size - 1) // self.batch_size
        
        for batch_num in range(0, len(grants_data), self.batch_size):
            batch = grants_data[batch_num:batch_num + self.batch_size]
            batch_num_display = (batch_num // self.batch_size) + 1
            
            if progress_callback:
                progress_callback(batch_num, len(grants_data))
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    batch_results = self.match_grants_batch(project_description, batch)
                    
                    # Adjust grant_index to match original position
                    for result in batch_results:
                        result['grant_index'] = batch_num + result['grant_index']
                    
                    all_results.extend(batch_results)
                    
                    # Small delay between batches to respect rate limits
                    if batch_num + self.batch_size < len(grants_data):
                        time.sleep(1.5)  # 1.5 second delay between batches
                    
                    break  # Success, exit retry loop
                    
                except RateLimitError:
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) * 5  # 5s, 10s, 20s
                        print(f"Rate limit hit. Waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                    else:
                        raise GrantMatchingError(f"Rate limit exceeded after {max_retries} retries")
                
                except APIError as e:
                    if attempt < max_retries - 1:
                        print(f"API error: {e}. Retrying...")
                        time.sleep(2)
                    else:
                        raise GrantMatchingError(f"API error after {max_retries} retries: {e}")
                
                except json.JSONDecodeError as e:
                    print(f"JSON decode error: {e}. Retrying...")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                    else:
                        # Last attempt failed, create placeholder results
                        print("Creating placeholder results for failed batch")
                        for idx in range(len(batch)):
                            all_results.append({
                                'grant_index': batch_num + idx,
                                'score': 0.0,
                                'explanation': 'Error processing this grant',
                                'alignment_points': [],
                                'concerns': ['Processing error'],
                            })
        
        return all_results

