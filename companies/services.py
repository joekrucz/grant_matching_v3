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
        self.batch_size = 1  # Process 1 grant per API call for reliability
    
    def format_grant_for_batch(self, grant_data, index):
        """Format a single grant for batch prompt, including checklists if available."""
        deadline_str = grant_data.get('deadline', 'N/A')
        if deadline_str and deadline_str != 'N/A':
            try:
                from django.utils.dateparse import parse_datetime
                dt = parse_datetime(str(deadline_str))
                if dt:
                    deadline_str = dt.strftime('%d %B %Y')
            except:
                pass
        
        grant_text = f"""
Grant #{index + 1}:
- Title: {grant_data['title']}
- Source: {grant_data['source']}
- Summary: {grant_data.get('summary', 'N/A')[:200]}
- Description: {grant_data.get('description', 'N/A')[:500]}
- Funding: {grant_data.get('funding_amount', 'N/A')}
- Deadline: {deadline_str}
- Status: {grant_data.get('status', 'unknown')}
"""
        
        # Add eligibility checklist if available
        eligibility_checklist = grant_data.get('eligibility_checklist', {})
        eligibility_items = eligibility_checklist.get('checklist_items', [])
        if eligibility_items:
            grant_text += "\nEligibility Checklist:\n"
            for i, item in enumerate(eligibility_items, 1):
                grant_text += f"  {i}. {item}\n"
        else:
            grant_text += "\nEligibility Checklist: Not available (will need to extract from grant description)\n"
        
        # Add competitiveness checklist if available
        competitiveness_checklist = grant_data.get('competitiveness_checklist', {})
        competitiveness_items = competitiveness_checklist.get('checklist_items', [])
        if competitiveness_items:
            grant_text += "\nCompetitiveness Checklist:\n"
            for i, item in enumerate(competitiveness_items, 1):
                grant_text += f"  {i}. {item}\n"
        else:
            grant_text += "\nCompetitiveness Checklist: Not available (will need to extract from grant description)\n"
        
        return grant_text
    
    def match_grants_batch(self, project_description, grants_batch):
        """
        Match a batch of grants (1 at a time) against project.
        Returns list of match results.
        """
        # Since batch_size is 1, grants_batch will always have 1 grant
        grant = grants_batch[0]
        grant_text = self.format_grant_for_batch(grant, 0)
        
        prompt = f"""You are an expert grant matching assistant. Analyze how well a research project aligns with this funding opportunity.

PROJECT DESCRIPTION:
{project_description}

FUNDING OPPORTUNITY:
{grant_text}

You must:
1. If the grant has an "Eligibility Checklist" provided, you MUST use those EXACT items in the EXACT order shown. Copy the criterion text EXACTLY as provided - do not modify, rephrase, or summarize.
2. If the grant has a "Competitiveness Checklist" provided, you MUST use those EXACT items in the EXACT order shown. Copy the criterion text EXACTLY as provided - do not modify, rephrase, or summarize.
3. If checklists are not provided, extract eligibility criteria and competitiveness factors from the grant description.
4. For EACH checklist item (whether provided or extracted), evaluate if the company/project meets the criterion based ONLY on the PROJECT DESCRIPTION provided above.
5. Assign a status: "yes" (meets criterion), "no" (does not meet), or "don't know" (insufficient information in input sources).
6. Provide a brief reason for each status.
7. Calculate eligibility_score (0.0-1.0) based on percentage of "yes" answers in eligibility checklist.
8. Calculate competitiveness_score (0.0-1.0) based on percentage of "yes" answers in competitiveness checklist.
9. Provide an overall explanation (2-3 sentences).

CRITICAL REQUIREMENTS:
- If a grant provides checklists, you MUST copy the criterion text EXACTLY as shown - character for character, word for word. Do not modify, rephrase, or summarize the criterion text.
- Return evaluations in the SAME ORDER as the provided checklists.
- The "criterion" field in your response must match the original text EXACTLY.
- If checklists are not provided, extract ALL eligibility requirements and competitiveness factors from the grant description.
- For each checklist item, evaluate based ONLY on the provided PROJECT DESCRIPTION. If information is not available, use "don't know".
- The evaluation should be consistent: "yes" means the project clearly meets the criterion, "no" means it clearly does not, "don't know" means there's insufficient information to determine.
- Respond with a valid JSON object containing a single match result (not an array)

Format:
{{
    "grant_index": 0,
    "eligibility_score": 0.90,
    "competitiveness_score": 0.80,
    "eligibility_checklist": [
        {{"criterion": "Use the exact criterion text from the provided checklist", "status": "yes", "reason": "Brief reason based on project description"}},
        {{"criterion": "Another criterion from the checklist", "status": "don't know", "reason": "Insufficient information in project description"}},
        {{"criterion": "Third criterion", "status": "no", "reason": "Project does not meet this requirement"}}
    ],
    "competitiveness_checklist": [
        {{"criterion": "Use the exact criterion text from the provided checklist", "status": "yes", "reason": "Brief reason based on project description"}},
        {{"criterion": "Another criterion from the checklist", "status": "don't know", "reason": "Insufficient information in project description"}}
    ],
    "explanation": "This grant is highly relevant because..."
}}

IMPORTANT: 
- If the grant provides checklists, use the EXACT criterion text from those checklists. Do not modify or rephrase them.
- For each criterion, evaluate if the project meets it based on the PROJECT DESCRIPTION provided above.
- Status must be one of: "yes", "no", or "don't know"
- Return a single match object, not an array
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "You are a grant matching expert. Always respond with valid JSON. For the grant:\n1. If the grant provides an Eligibility Checklist, you MUST copy the criterion text EXACTLY as shown - do not modify, rephrase, or summarize. Use those exact items in the exact order.\n2. If the grant provides a Competitiveness Checklist, you MUST copy the criterion text EXACTLY as shown - do not modify, rephrase, or summarize. Use those exact items in the exact order.\n3. If checklists are not provided, extract eligibility criteria and competitiveness factors from the grant description.\n4. For each checklist item (provided or extracted), evaluate based ONLY on the provided project description and assign status: 'yes' (meets), 'no' (does not meet), or 'don't know' (insufficient information).\n5. The 'criterion' field in your response must match the original text EXACTLY if provided in the checklist.\n6. Calculate eligibility_score and competitiveness_score (0.0-1.0) based on percentage of 'yes' answers in each checklist.\n7. Provide a brief explanation. Return a single JSON object (not an array) with grant_index: 0."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower for consistent scoring
                response_format={"type": "json_object"},
                max_tokens=4000,  # Sufficient for single grant with detailed checklists and evaluations
            )
            
            # Get response content
            response_content = response.choices[0].message.content
            if not response_content:
                raise GrantMatchingError("Empty response from ChatGPT API")
            
            # Check if response was truncated (indicated by finish_reason)
            finish_reason = response.choices[0].finish_reason
            if finish_reason == 'length':
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"ChatGPT response was truncated (finish_reason=length). Response length: {len(response_content)}")
                # Try to parse what we have, but log a warning
                # The response might still be valid JSON if it was cut off mid-response
            
            try:
                result = json.loads(response_content)
            except json.JSONDecodeError as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"JSON decode error: {e}. Response length: {len(response_content)}. Finish reason: {finish_reason}")
                logger.error(f"First 500 chars: {response_content[:500]}")
                logger.error(f"Last 500 chars: {response_content[-500:]}")
                
                # If response was truncated, we need to retry with higher max_tokens
                if finish_reason == 'length':
                    raise GrantMatchingError(f"Response truncated - need higher max_tokens. Current: 16000")
                
                # Try to fix common JSON issues
                # Remove any trailing incomplete strings
                response_content_cleaned = response_content.rstrip()
                # Try to close any unclosed strings/objects
                if response_content_cleaned.count('{') > response_content_cleaned.count('}'):
                    # Missing closing braces
                    response_content_cleaned += '}' * (response_content_cleaned.count('{') - response_content_cleaned.count('}'))
                try:
                    result = json.loads(response_content_cleaned)
                    logger.warning("Successfully parsed JSON after cleanup")
                except json.JSONDecodeError:
                    raise GrantMatchingError(f"Failed to parse ChatGPT response as JSON: {str(e)}")
            
            # Handle both single match object and matches array (for backward compatibility)
            if 'matches' in result:
                matches = result.get('matches', [])
            else:
                # Single match object - wrap in array
                matches = [result]
            
            # Log first match to verify structure
            if matches:
                first_match = matches[0]
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Sample match result structure: {list(first_match.keys())}")
                if 'eligibility_score' not in first_match or 'competitiveness_score' not in first_match:
                    logger.warning(f"Match result missing component scores. Keys: {list(first_match.keys())}")
                if 'eligibility_checklist' not in first_match:
                    logger.warning(f"Match result missing eligibility_checklist. Keys: {list(first_match.keys())}")
                else:
                    logger.info(f"Eligibility checklist has {len(first_match.get('eligibility_checklist', []))} items")
                if 'competitiveness_checklist' not in first_match:
                    logger.warning(f"Match result missing competitiveness_checklist. Keys: {list(first_match.keys())}")
                else:
                    logger.info(f"Competitiveness checklist has {len(first_match.get('competitiveness_checklist', []))} items")
            
            return matches
            
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
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Starting to match {len(grants_data)} grants in {total_batches} batches of {self.batch_size}")
        
        for batch_num in range(0, len(grants_data), self.batch_size):
            batch = grants_data[batch_num:batch_num + self.batch_size]
            batch_num_display = (batch_num // self.batch_size) + 1
            logger.info(f"Processing batch {batch_num_display}/{total_batches} (grants {batch_num} to {min(batch_num + self.batch_size, len(grants_data)) - 1})")
            
            max_retries = 3
            batch_success = False
            for attempt in range(max_retries):
                try:
                    # Update progress before processing batch
                    if progress_callback:
                        progress_callback(batch_num, len(grants_data))
                    
                    logger.info(f"Batch {batch_num_display}, attempt {attempt + 1}/{max_retries}: Calling match_grants_batch...")
                    batch_results = self.match_grants_batch(project_description, batch)
                    logger.info(f"Batch {batch_num_display}: Got {len(batch_results)} results from match_grants_batch")
                    
                    # Adjust grant_index to match original position
                    for result in batch_results:
                        result['grant_index'] = batch_num + result['grant_index']
                    
                    all_results.extend(batch_results)
                    batch_success = True
                    logger.info(f"Batch {batch_num_display}: Successfully processed {len(batch)} grants. Total results so far: {len(all_results)}")
                    
                    # Update progress after successfully processing batch
                    grants_processed = min(batch_num + len(batch), len(grants_data))
                    if progress_callback:
                        progress_callback(grants_processed, len(grants_data))
                    
                    # Small delay between requests to respect rate limits
                    if batch_num + self.batch_size < len(grants_data):
                        logger.info(f"Batch {batch_num_display}: Waiting 0.5s before next grant...")
                        time.sleep(0.5)  # 0.5 second delay between grants
                    
                    break  # Success, exit retry loop
                    
                except RateLimitError as e:
                    logger.warning(f"Batch {batch_num_display}, attempt {attempt + 1}: Rate limit hit: {e}")
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) * 5  # 5s, 10s, 20s
                        logger.info(f"Waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Batch {batch_num_display}: Rate limit exceeded after {max_retries} retries")
                        raise GrantMatchingError(f"Rate limit exceeded after {max_retries} retries")
                
                except APIError as e:
                    logger.warning(f"Batch {batch_num_display}, attempt {attempt + 1}: API error: {e}")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in 2s...")
                        time.sleep(2)
                    else:
                        logger.error(f"Batch {batch_num_display}: API error after {max_retries} retries: {e}")
                        raise GrantMatchingError(f"API error after {max_retries} retries: {e}")
                
                except GrantMatchingError as e:
                    # If it's a truncation error, we should fail immediately rather than retry
                    if "truncated" in str(e).lower() or "max_tokens" in str(e).lower():
                        logger.error(f"Batch {batch_num_display}, attempt {attempt + 1}: Response truncation error: {e}")
                        raise  # Re-raise to fail the task
                    
                    # For other GrantMatchingError, retry
                    logger.warning(f"Batch {batch_num_display}, attempt {attempt + 1}: Grant matching error: {e}")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in 2s...")
                        time.sleep(2)
                    else:
                        logger.error(f"Batch {batch_num_display}: Grant matching error after {max_retries} retries: {e}")
                        raise
                
                except json.JSONDecodeError as e:
                    logger.warning(f"Batch {batch_num_display}, attempt {attempt + 1}: JSON decode error: {e}")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in 1s...")
                        time.sleep(1)
                    else:
                        # Last attempt failed, create placeholder results
                        logger.error(f"Batch {batch_num_display}: JSON decode failed after all retries. Creating placeholder results for failed batch")
                        for idx in range(len(batch)):
                            all_results.append({
                                'grant_index': batch_num + idx,
                                'eligibility_score': 0.0,
                                'competitiveness_score': 0.0,
                                'explanation': 'Error processing this grant - JSON decode failed',
                                'eligibility_checklist': [],
                                'competitiveness_checklist': [],
                                'alignment_points': [],
                                'concerns': ['Processing error'],
                            })
                        batch_success = True  # Mark as success so we continue to next batch
                        # Update progress even for failed batch
                        grants_processed = min(batch_num + len(batch), len(grants_data))
                        if progress_callback:
                            progress_callback(grants_processed, len(grants_data))
                        break
                
                except Exception as e:
                    # Catch any other unexpected exceptions
                    logger.error(f"Batch {batch_num_display}, attempt {attempt + 1}: Unexpected error: {e}", exc_info=True)
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in 2s...")
                        time.sleep(2)
                    else:
                        # Last attempt failed, create placeholder results and continue
                        logger.error(f"Batch {batch_num_display}: Unexpected error after {max_retries} retries. Creating placeholder results and continuing.")
                        for idx in range(len(batch)):
                            all_results.append({
                                'grant_index': batch_num + idx,
                                'eligibility_score': 0.0,
                                'competitiveness_score': 0.0,
                                'explanation': f'Error processing this grant: {str(e)[:200]}',
                                'eligibility_checklist': [],
                                'competitiveness_checklist': [],
                                'alignment_points': [],
                                'concerns': ['Processing error'],
                            })
                        batch_success = True  # Mark as success so we continue to next batch
                        # Update progress even for failed batch
                        grants_processed = min(batch_num + len(batch), len(grants_data))
                        if progress_callback:
                            progress_callback(grants_processed, len(grants_data))
                        break
            
            if not batch_success:
                logger.error(f"Batch {batch_num_display}: Failed after {max_retries} retries. Creating placeholder results and continuing to next batch.")
                # Create placeholder results for this batch and continue
                for idx in range(len(batch)):
                    all_results.append({
                        'grant_index': batch_num + idx,
                        'eligibility_score': 0.0,
                        'competitiveness_score': 0.0,
                        'explanation': 'Error processing this grant - batch failed after retries',
                        'eligibility_checklist': [],
                        'competitiveness_checklist': [],
                        'alignment_points': [],
                        'concerns': ['Processing error'],
                    })
                # Update progress
                grants_processed = min(batch_num + len(batch), len(grants_data))
                if progress_callback:
                    progress_callback(grants_processed, len(grants_data))
                # Continue to next batch instead of breaking
        
        logger.info(f"Completed matching. Processed {len(all_results)} results from {len(grants_data)} grants")
        return all_results

