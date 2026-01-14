"""
Company, FundingSearch, CompanyGrant, and GrantMatchWorkpackage models.
"""
import json
from django.db import models
from django.conf import settings
from grants.models import Grant


TRL_LEVELS = [
    ("TRL 1 - Basic principles observed", "TRL 1 - Basic principles observed"),
    ("TRL 2 - Technology concept formulated", "TRL 2 - Technology concept formulated"),
    ("TRL 3 - Experimental proof of concept", "TRL 3 - Experimental proof of concept"),
    ("TRL 4 - Technology validated in lab", "TRL 4 - Technology validated in lab"),
    ("TRL 5 - Technology validated in relevant environment", "TRL 5 - Technology validated in relevant environment"),
    ("TRL 6 - Technology demonstrated in relevant environment", "TRL 6 - Technology demonstrated in relevant environment"),
    ("TRL 7 - System prototype demonstration in operational environment", "TRL 7 - System prototype demonstration in operational environment"),
    ("TRL 8 - System complete and qualified", "TRL 8 - System complete and qualified"),
    ("TRL 9 - Actual system proven in operational environment", "TRL 9 - Actual system proven in operational environment"),
]


class Company(models.Model):
    """Company model from Companies House or manually entered."""
    
    REGISTRATION_STATUS_CHOICES = [
        ('registered', 'Registered'),
        ('unregistered', 'Not Yet Registered'),
    ]
    
    company_number = models.CharField(max_length=50, unique=True, db_index=True, blank=True, null=True)
    name = models.CharField(max_length=500)
    is_registered = models.BooleanField(default=True, db_index=True)  # True if registered with Companies House
    registration_status = models.CharField(
        max_length=20, 
        choices=REGISTRATION_STATUS_CHOICES, 
        default='registered',
        db_index=True
    )
    company_type = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=100, blank=True, null=True)
    sic_codes = models.TextField(blank=True, null=True)  # Can be comma-separated or JSON
    address = models.JSONField(default=dict, blank=True)
    date_of_creation = models.DateField(blank=True, null=True)
    filing_history = models.JSONField(default=dict, blank=True)  # Stores filing history from Companies House
    grants_received_360 = models.JSONField(default=dict, blank=True)  # Grants received via 360Giving
    website = models.URLField(blank=True, null=True)
    raw_data = models.JSONField(default=dict, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='companies')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'companies'
        indexes = [
            models.Index(fields=['company_number']),
            models.Index(fields=['is_registered']),
            models.Index(fields=['registration_status']),
        ]
        verbose_name_plural = 'companies'
    
    def __str__(self):
        if self.company_number:
            return f"{self.name} ({self.company_number})"
        return f"{self.name} (Unregistered)"
    
    def sic_codes_array(self):
        """Return array of SIC codes, handling both string and array formats."""
        if not self.sic_codes:
            return []
        
        try:
            # Try to parse as JSON array
            codes = json.loads(self.sic_codes)
            if isinstance(codes, list):
                return codes
        except (json.JSONDecodeError, TypeError):
            pass
        
        # Treat as comma-separated string
        if isinstance(self.sic_codes, str):
            return [code.strip() for code in self.sic_codes.split(',') if code.strip()]
        
        return []
    
    def sic_codes_with_descriptions(self):
        """Return list of dicts with SIC code and description."""
        from companies.sic_codes import get_sic_description
        
        codes = self.sic_codes_array()
        return [
            {
                'code': code,
                'description': get_sic_description(code)
            }
            for code in codes
        ]
    
    def formatted_address(self):
        """Return formatted address string from JSONField."""
        if not self.address or not isinstance(self.address, dict):
            return ''
        
        parts = []
        if self.address.get('address_line_1'):
            parts.append(self.address['address_line_1'])
        if self.address.get('address_line_2'):
            parts.append(self.address['address_line_2'])
        if self.address.get('locality'):
            parts.append(self.address['locality'])
        if self.address.get('postal_code'):
            parts.append(self.address['postal_code'])
        if self.address.get('country'):
            parts.append(self.address['country'])
        
        return ', '.join(parts)
    
    def get_account_filings(self):
        """
        Extract and return only account filings with enhanced information.
        
        Returns:
            list: List of dicts with account filing info including:
                - financial_year: Derived from made_up_date
                - made_up_to_date: Date accounts made up to
                - account_type: Type of accounts (micro-entity, small, medium, large, full)
                - filing_status: On time/late with days
                - document_link: Link to view document
        """
        if not self.filing_history or not self.filing_history.get('items'):
            return []
        
        from datetime import datetime, timedelta
        import re
        
        account_filings = []
        
        for filing in self.filing_history['items']:
            # Filter for account filings
            category = filing.get('category', '').lower()
            if category != 'accounts':
                continue
            
            # Extract filing date
            filing_date = filing.get('date') or filing.get('filing_date')
            
            # Extract description
            description = filing.get('description', '')
            desc_values = filing.get('description_values', {})
            links = filing.get('links', {})
            
            # Get description from description_values if not in main description field
            if not description and desc_values:
                description = desc_values.get('description', '')
            
            # Extract "made up to" date - check description_values first (Companies House API structure)
            # According to Companies House API docs, the field is 'made_up_date' in description_values
            made_up_to_date = None
            made_up_date_obj = None
            
            # Method 1: Check if made_up_date is directly in description_values (Companies House API standard)
            if desc_values and 'made_up_date' in desc_values:
                made_up_to_date = desc_values.get('made_up_date')
            # Method 2: Check for made_up_to_date (alternative field name)
            elif desc_values and 'made_up_to_date' in desc_values:
                made_up_to_date = desc_values.get('made_up_to_date')
            # Method 3: Check for period_end_on (alternative field name)
            elif desc_values and 'period_end_on' in desc_values:
                made_up_to_date = desc_values.get('period_end_on')
            # Method 4: Extract from description text using regex (fallback)
            elif description:
                # Pattern: "made up to 31 December 2024" or "made-up to 31/12/2024" etc.
                patterns = [
                    r'made[\s-]up to[\s:]+(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})',
                    r'made[\s-]up to[\s:]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
                    r'period ending[\s:]+(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})',
                    r'accounts? for[\s]+(?:the\s+)?(?:period\s+)?(?:ending|to)[\s:]+(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})',
                    r'(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})',  # Generic date pattern
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, description, re.IGNORECASE)
                    if match:
                        made_up_to_date = match.group(1).strip()
                        break
            
            # Parse made_up_date for calculations
            made_up_date_obj = None
            made_up_to_date_formatted = made_up_to_date
            
            if made_up_to_date:
                try:
                    # Try parsing ISO format (YYYY-MM-DD)
                    if '-' in made_up_to_date and len(made_up_to_date) == 10:
                        made_up_date_obj = datetime.strptime(made_up_to_date, '%Y-%m-%d').date()
                        # Format as "Mar 31, 2024"
                        made_up_to_date_formatted = made_up_date_obj.strftime('%b %d, %Y')
                    # Try parsing other formats
                    else:
                        # Try common date formats
                        for fmt in ['%d %B %Y', '%d/%m/%Y', '%d-%m-%Y', '%B %d, %Y']:
                            try:
                                made_up_date_obj = datetime.strptime(made_up_to_date, fmt).date()
                                made_up_to_date_formatted = made_up_date_obj.strftime('%b %d, %Y')
                                break
                            except ValueError:
                                continue
                except (ValueError, AttributeError):
                    made_up_date_obj = None
            
            # Calculate financial year (e.g., "2023-24" or "FY 2024")
            financial_year = None
            if made_up_date_obj:
                year = made_up_date_obj.year
                # UK financial year typically runs April to March
                # If date is Jan-Mar, it's the end of previous financial year
                if made_up_date_obj.month <= 3:
                    financial_year = f"{year - 1}-{str(year)[2:]}"
                else:
                    financial_year = f"{year}-{str(year + 1)[2:]}"
            
            # Extract account type
            account_type = desc_values.get('account_type', '').title() if desc_values else None
            if not account_type:
                # Try to extract from description
                if 'micro-entity' in description.lower() or 'microentity' in description.lower():
                    account_type = 'Micro-entity'
                elif 'small' in description.lower():
                    account_type = 'Small'
                elif 'medium' in description.lower():
                    account_type = 'Medium'
                elif 'large' in description.lower():
                    account_type = 'Large'
                elif 'full' in description.lower():
                    account_type = 'Full'
            
            # Calculate filing status (due date is typically made_up_date + 9 months for UK companies)
            filing_status = None
            filing_status_days = None
            if made_up_date_obj and filing_date:
                try:
                    # Parse filing date
                    filing_date_obj = datetime.strptime(filing_date, '%Y-%m-%d').date()
                    
                    # Calculate due date (9 months after made_up_date)
                    due_date = made_up_date_obj + timedelta(days=273)  # ~9 months
                    
                    # Calculate days difference
                    days_diff = (filing_date_obj - due_date).days
                    
                    if days_diff <= 0:
                        filing_status = 'On Time'
                        filing_status_days = abs(days_diff)
                    else:
                        filing_status = 'Late'
                        filing_status_days = days_diff
                except (ValueError, AttributeError):
                    filing_status = None
                    filing_status_days = None
            
            # Extract document link
            document_link = links.get('document_metadata') or links.get('self')
            
            account_filings.append({
                'filing_date': filing_date,
                'description': description,
                'made_up_to_date': made_up_to_date_formatted,  # Formatted date string
                'made_up_date_obj': made_up_date_obj,  # For sorting
                'financial_year': financial_year,
                'account_type': account_type or 'Unknown',
                'filing_status': filing_status,
                'filing_status_days': filing_status_days,
                'document_link': document_link,
                'type': filing.get('type', ''),
                'subcategory': filing.get('subcategory', ''),
            })
        
        # Sort by made_up_date (most recent first), fallback to filing_date
        account_filings.sort(
            key=lambda x: (
                x['made_up_date_obj'] if x['made_up_date_obj'] else datetime.min.date(),
                x['filing_date'] or ''
            ),
            reverse=True
        )
        
        return account_filings


class FundingSearchFile(models.Model):
    """Files uploaded for a funding search (e.g., project descriptions, proposals)."""

    funding_search = models.ForeignKey('FundingSearch', on_delete=models.CASCADE, related_name='uploaded_files')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='funding_search_files')
    file = models.FileField(upload_to='funding_searches/%Y/%m/')
    original_name = models.CharField(max_length=255, blank=True, null=True)
    file_type = models.CharField(max_length=50, blank=True, null=True)  # 'pdf', 'docx', 'txt', 'text'
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'funding_search_files'
        ordering = ['-created_at']

    def __str__(self):
        return self.original_name or self.file.name


class FundingSearch(models.Model):
    """Funding search criteria for a company."""
    
    MATCHING_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('error', 'Error'),
        ('cancelled', 'Cancelled'),
    ]
    
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='funding_searches')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='funding_searches')
    name = models.CharField(max_length=255)
    notes = models.TextField(blank=True, null=True)
    trl_level = models.CharField(max_length=255, choices=TRL_LEVELS, blank=True, null=True)  # Legacy single TRL level (deprecated)
    trl_levels = models.JSONField(default=list, blank=True)  # Multiple TRL levels stored as list
    let_system_decide_trl = models.BooleanField(default=False)  # If True, let AI assess TRL level during matching
    
    # Matching fields
    project_description = models.TextField(blank=True, null=True)  # Text input or extracted from file
    uploaded_file = models.FileField(upload_to='funding_searches/%Y/%m/', blank=True, null=True)
    file_type = models.CharField(max_length=50, blank=True, null=True)  # 'pdf', 'docx', 'txt', 'text'
    
    # Company data selections for matching
    use_company_website = models.BooleanField(default=False)  # Whether to use company website as a source
    use_company_grant_history = models.BooleanField(default=False)  # Whether to use company grant history (360Giving) as a source
    
    # Grant source selection for matching
    selected_grant_sources = models.JSONField(default=list, blank=True)  # List of grant source codes to match against (e.g., ['ukri', 'nihr'])
    exclude_closed_competitions = models.BooleanField(default=True)  # If True, exclude closed competitions from matching
    
    # Checklist assessment configuration
    assess_exclusions = models.BooleanField(
        default=True,
        help_text="If True, assess exclusions checklist (recommended: assess first)"
    )
    assess_eligibility = models.BooleanField(
        default=True,
        help_text="If True, assess eligibility checklist (recommended: assess second)"
    )
    assess_competitiveness = models.BooleanField(
        default=True,
        help_text="If True, assess competitiveness checklist (recommended: assess last)"
    )
    # Assessment order (optional - for future use if we want to change order)
    checklist_assessment_order = models.JSONField(
        default=list,
        blank=True,
        help_text="Order of checklist assessment: ['exclusions', 'eligibility', 'competitiveness']"
    )
    
    # Pre-flight checks result (quality of input material before matching)
    preflight_result = models.JSONField(
        default=dict,
        blank=True,
        help_text="Pre-flight quality assessment for this funding search (coverage, clarity, completeness, etc.)"
    )
    
    # Link to questionnaire used
    questionnaire = models.ForeignKey(
        'FundingQuestionnaire',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='funding_searches',
        help_text="Questionnaire used to populate this funding search"
    )
    
    last_matched_at = models.DateTimeField(blank=True, null=True)
    matching_status = models.CharField(max_length=50, default='pending', choices=MATCHING_STATUS_CHOICES, db_index=True)
    matching_error = models.TextField(blank=True, null=True)  # Store error message if matching fails
    matching_progress = models.JSONField(default=dict, blank=True)  # Store progress: {'current': 0, 'total': 0, 'percentage': 0}
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'funding_searches'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['matching_status']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.company.name})"
    
    def get_all_trl_levels(self):
        """
        Get all TRL levels, combining the new trl_levels list with the legacy trl_level field.
        Returns a list of unique TRL level values.
        """
        trl_levels = list(self.trl_levels) if self.trl_levels else []
        if self.trl_level and self.trl_level not in trl_levels:
            trl_levels.append(self.trl_level)
        return trl_levels
    
    def compile_input_sources_text(self):
        """
        Compile text from all available input sources for matching.
        Returns combined text from:
        - Company registration details (always included - registration status, company number, type, SIC codes, address)
        - Company website (always included if available - scraped content)
        - Company grant history (always included if available - grants received via 360Giving)
        - Questionnaire context (if questionnaire is linked - includes company info, project details, funding requirements, etc.)
        - Project description (if exists - for backward compatibility)
        - Uploaded file (if exists - extracted text)
        """
        def extract_text_from_file(file, file_type):
            """Extract text from uploaded file."""
            if file_type == 'pdf':
                try:
                    import PyPDF2
                    pdf_reader = PyPDF2.PdfReader(file)
                    text = ""
                    for page in pdf_reader.pages:
                        text += page.extract_text() + "\n"
                    return text.strip()
                except Exception as e:
                    raise Exception(f"Error reading PDF: {str(e)}")
            
            elif file_type == 'docx':
                try:
                    from docx import Document
                    doc = Document(file)
                    text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
                    return text.strip()
                except Exception as e:
                    raise Exception(f"Error reading DOCX: {str(e)}")
            
            elif file_type == 'txt':
                try:
                    file.seek(0)  # Reset file pointer
                    text = file.read().decode('utf-8')
                    return text.strip()
                except UnicodeDecodeError:
                    try:
                        file.seek(0)
                        text = file.read().decode('latin-1')
                        return text.strip()
                    except Exception as e:
                        raise Exception(f"Error reading text file: {str(e)}")
            
            else:
                raise Exception(f"Unsupported file type: {file_type}")
        
        text_parts = []
        
        # Add company registration details (always included for eligibility checks)
        company_info = []
        company_info.append(f"Company Name: {self.company.name}")
        
        if self.company.company_number:
            company_info.append(f"Company Number: {self.company.company_number}")
        
        if self.company.registration_status:
            company_info.append(f"Registration Status: {self.company.get_registration_status_display()}")
            if self.company.is_registered:
                company_info.append("UK Registered: Yes")
            else:
                company_info.append("UK Registered: No")
        
        if self.company.company_type:
            company_info.append(f"Company Type: {self.company.company_type}")
        
        if self.company.status:
            company_info.append(f"Company Status: {self.company.status}")
        
        if self.company.date_of_creation:
            company_info.append(f"Date of Creation: {self.company.date_of_creation}")
        
        # Add SIC codes with descriptions
        sic_codes = self.company.sic_codes_with_descriptions()
        if sic_codes:
            sic_info = []
            for sic in sic_codes:
                sic_info.append(f"  - {sic['code']}: {sic['description']}")
            company_info.append(f"SIC Codes:\n" + "\n".join(sic_info))
        
        # Add formatted address
        formatted_address = self.company.formatted_address()
        if formatted_address:
            company_info.append(f"Registered Address: {formatted_address}")
        
        if company_info:
            text_parts.append("Company Registration Details:\n" + "\n".join(company_info) + "\n")
        
        # Add company website (always included if available)
        if self.company.website:
            try:
                # SECURITY: Validate URL to prevent SSRF attacks
                from .security import validate_url_for_ssrf
                is_valid, error_msg = validate_url_for_ssrf(self.company.website)
                if not is_valid:
                    text_parts.append(f"Company Website: {self.company.website} (URL validation failed: {error_msg})\n")
                else:
                    import requests
                    from bs4 import BeautifulSoup
                    from urllib.parse import urljoin, urlparse
                    
                    # Fetch website content
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                    # SECURITY: Disable redirects to prevent SSRF via redirects
                    response = requests.get(self.company.website, headers=headers, timeout=10, allow_redirects=False)
                    response.raise_for_status()
                    
                    # Parse HTML and extract text
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Remove script and style elements
                    for script in soup(["script", "style", "nav", "footer", "header"]):
                        script.decompose()
                    
                    # Get text content
                    website_text = soup.get_text()
                    
                    # Clean up whitespace
                    lines = (line.strip() for line in website_text.splitlines())
                    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                    website_text = ' '.join(chunk for chunk in chunks if chunk)
                    
                    # Limit to reasonable length (first 5000 characters)
                    if len(website_text) > 5000:
                        website_text = website_text[:5000] + "... (truncated)"
                    
                    if website_text:
                        text_parts.append(f"Company Website: {self.company.website}\n{website_text}\n")
                    else:
                        text_parts.append(f"Company Website: {self.company.website} (no text content found)\n")
            except Exception as e:
                # If scraping fails, just include the URL
                text_parts.append(f"Company Website: {self.company.website} (scraping failed: {str(e)})\n")
        
        # Add company grant history (always included if available)
        if self.company.grants_received_360:
            grants_data = self.company.grants_received_360
            grants = grants_data.get('grants', [])
            
            if grants:
                grant_history_text = []
                grant_history_text.append(f"Company Grant History (360Giving): {grants_data.get('count', len(grants))} grant(s) received\n")
                
                for grant in grants:
                    grant_info = []
                    if grant.get('title'):
                        grant_info.append(f"Title: {grant['title']}")
                    if grant.get('description'):
                        grant_info.append(f"Description: {grant['description']}")
                    if grant.get('amountAwarded'):
                        grant_info.append(f"Amount Awarded: £{grant['amountAwarded']}")
                    if grant.get('awardDate'):
                        grant_info.append(f"Award Date: {grant['awardDate']}")
                    if grant.get('funder'):
                        grant_info.append(f"Funder: {grant['funder']}")
                    if grant.get('recipientOrganization', {}).get('name'):
                        grant_info.append(f"Recipient: {grant['recipientOrganization']['name']}")
                    
                    if grant_info:
                        grant_history_text.append("\n".join(grant_info))
                        grant_history_text.append("")  # Empty line between grants
                
                if grant_history_text:
                    text_parts.append("\n".join(grant_history_text).strip())
            else:
                text_parts.append("Company Grant History: No grants found in 360Giving database\n")
        
        # Add questionnaire context if available (add early for better matching context)
        if self.questionnaire and self.questionnaire.questionnaire_data:
            data = self.questionnaire.questionnaire_data
            questionnaire_context = []
            
            # Company information
            if data.get('company_stage'):
                questionnaire_context.append(f"Company Stage: {data['company_stage']}")
            if data.get('company_size'):
                questionnaire_context.append(f"Company Size: {data['company_size']}")
            if data.get('primary_sector'):
                questionnaire_context.append(f"Primary Sector: {data['primary_sector']}")
            if data.get('company_location'):
                loc = data['company_location']
                location_parts = []
                if loc.get('city'):
                    location_parts.append(loc['city'])
                if loc.get('region'):
                    location_parts.append(loc['region'])
                if loc.get('country'):
                    location_parts.append(loc['country'])
                if location_parts:
                    questionnaire_context.append(f"Company Location: {', '.join(location_parts)}")
            
            # Project information
            if data.get('project_name'):
                questionnaire_context.append(f"Project Name: {data['project_name']}")
            if data.get('problem_statement'):
                questionnaire_context.append(f"Problem Statement: {data['problem_statement']}")
            if data.get('project_types'):
                questionnaire_context.append(f"Project Types: {', '.join(data['project_types'])}")
            if data.get('target_market'):
                questionnaire_context.append(f"Target Market: {data['target_market']}")
            if data.get('project_impact'):
                questionnaire_context.append(f"Project Impact: {data['project_impact']}")
            
            # Funding requirements
            if data.get('funding_amount_needed'):
                questionnaire_context.append(f"Funding Amount Needed: {data['funding_amount_needed']}")
            if data.get('funding_timeline'):
                questionnaire_context.append(f"Funding Timeline: {data['funding_timeline']}")
            if data.get('funding_purposes'):
                questionnaire_context.append(f"Funding Purposes: {', '.join(data['funding_purposes'])}")
            
            # Eligibility and requirements
            if data.get('organization_type'):
                questionnaire_context.append(f"Organization Type: {data['organization_type']}")
            if data.get('geographic_eligibility'):
                questionnaire_context.append(f"Geographic Eligibility: {data['geographic_eligibility']}")
            if data.get('collaboration_requirements'):
                questionnaire_context.append(f"Collaboration Requirements: {data['collaboration_requirements']}")
            if data.get('previous_grant_experience'):
                questionnaire_context.append(f"Previous Grant Experience: {data['previous_grant_experience']}")
            
            # Strengths
            if data.get('key_strengths'):
                questionnaire_context.append(f"Key Strengths: {', '.join(data['key_strengths'])}")
            
            if questionnaire_context:
                text_parts.append(f"Questionnaire Context:\n" + "\n".join(questionnaire_context) + "\n")
        
        # Add project description if it exists (for backward compatibility)
        if self.project_description:
            text_parts.append(f"Project Description:\n{self.project_description}\n")
        
        # Add uploaded files if exists (extract text from all files)
        for uploaded_file in self.uploaded_files.all():
            if uploaded_file.file_type:
                try:
                    with uploaded_file.file.open('rb') as f:
                        extracted_text = extract_text_from_file(f, uploaded_file.file_type)
                    
                    if extracted_text:
                        file_name = uploaded_file.original_name or uploaded_file.file.name
                        text_parts.append(f"Uploaded File: {file_name}\n{extracted_text}\n")
                except Exception as e:
                    # If extraction fails, just include the filename
                    file_name = uploaded_file.original_name or uploaded_file.file.name
                    text_parts.append(f"Uploaded File: {file_name} (text extraction failed: {str(e)})\n")
        
        # Legacy: Add old uploaded_file if exists (for backward compatibility)
        if self.uploaded_file and self.file_type:
            try:
                with self.uploaded_file.open('rb') as f:
                    extracted_text = extract_text_from_file(f, self.file_type)
                
                if extracted_text:
                    text_parts.append(f"Uploaded File: {self.uploaded_file.name}\n{extracted_text}\n")
            except Exception as e:
                # If extraction fails, just include the filename
                text_parts.append(f"Uploaded File: {self.uploaded_file.name} (text extraction failed: {str(e)})\n")
        
        
        # Combine all text parts
        combined_text = "\n\n---\n\n".join(text_parts)
        return combined_text.strip()


class CompanyGrant(models.Model):
    """Many-to-many relationship between Company and Grant."""
    
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='company_grants')
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name='company_grants')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'company_grants'
        unique_together = [['company', 'grant']]
    
    def __str__(self):
        return f"{self.company.name} - {self.grant.title}"


class GrantMatchWorkpackage(models.Model):
    """Workpackage for matching a company with a grant."""
    
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='grant_match_workpackages')
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name='grant_match_workpackages')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='grant_match_workpackages')
    notes = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=100, default='draft', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'grant_match_workpackages'
        unique_together = [['company', 'grant']]
        indexes = [
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.company.name} - {self.grant.title} ({self.status})"


class GrantMatchResult(models.Model):
    """Stores matching results between a FundingSearch and Grant."""
    
    funding_search = models.ForeignKey(FundingSearch, on_delete=models.CASCADE, related_name='match_results')
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name='match_results')
    match_score = models.FloatField(db_index=True)  # 0.0 to 1.0 - Overall score (average of enabled component scores)
    eligibility_score = models.FloatField(null=True, blank=True, db_index=True)  # 0.0 to 1.0 - How well the project meets eligibility criteria
    competitiveness_score = models.FloatField(null=True, blank=True, db_index=True)  # 0.0 to 1.0 - How competitive the project is for this grant
    exclusions_score = models.FloatField(null=True, blank=True, db_index=True)  # 0.0 to 1.0 - How well project avoids exclusions (higher = fewer exclusions apply)
    match_reasons = models.JSONField(default=dict)  # e.g., {"explanation": "...", "alignment_points": [], "concerns": [], "certainty": 0.85}
    matched_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'grant_match_results'
        unique_together = [['funding_search', 'grant']]
        ordering = ['-match_score']
        indexes = [
            models.Index(fields=['funding_search', '-match_score']),
        ]
    
    def save(self, *args, **kwargs):
        """
        Calculate overall match_score based on which checklists were assessed.
        Matches the logic in tasks.py to ensure consistency.
        
        Rules:
        1. If exclusions_score < 1.0 (any "yes" in exclusions checklist), set overall score to 0 (disqualifying)
        2. Otherwise, only recalculate if funding_search is loaded and we need to adjust based on assessment settings
        3. The main score calculation happens in tasks.py - this method mainly handles exclusions disqualification
        
        Note: We avoid loading funding_search here to prevent extra queries. The score should already
        be set correctly from tasks.py. This method primarily ensures exclusions are disqualifying.
        Note: exclusions_score = (no_count / decided_count), so if score < 1.0, there's at least one "yes"
        """
        # Check if project is excluded first (this doesn't require funding_search)
        # exclusions_score < 1.0 means at least one "yes" (exclusion applies)
        if self.exclusions_score is not None and self.exclusions_score < 1.0:
            # Project is excluded - disqualifying, set score to 0
            self.match_score = 0.0
            super().save(*args, **kwargs)
            return
        
        # Only recalculate if funding_search is already loaded (to avoid extra queries)
        # and if match_score needs to be calculated
        if hasattr(self, 'funding_search') and self.funding_search and self.match_score is None:
            # Calculate overall score using multiplicative approach
            # Eligibility acts as a base multiplier (paramount importance)
            # Formula: eligibility_score × (0.3 + 0.7 × competitiveness_score)
            # This ensures eligibility is foundational - if eligibility is 0%, overall is 0%
            # If eligibility is 100%, competitiveness can boost the score up to 100%
            if self.funding_search.assess_eligibility and self.funding_search.assess_competitiveness:
                # Both assessed: multiplicative (eligibility as base)
                if self.eligibility_score is not None and self.competitiveness_score is not None:
                    self.match_score = self.eligibility_score * (0.3 + 0.7 * self.competitiveness_score)
                elif self.eligibility_score is not None:
                    # Only eligibility available
                    self.match_score = self.eligibility_score
                elif self.competitiveness_score is not None:
                    # Only competitiveness available (shouldn't happen, but handle gracefully)
                    self.match_score = self.competitiveness_score
                else:
                    self.match_score = 0.0
            elif self.funding_search.assess_eligibility and self.eligibility_score is not None:
                # Only eligibility assessed
                self.match_score = self.eligibility_score
            elif self.funding_search.assess_competitiveness and self.competitiveness_score is not None:
                # Only competitiveness assessed
                self.match_score = self.competitiveness_score
            else:
                self.match_score = 0.0
        elif self.match_score is None:
            # Fallback: if no match_score set, default to 0
            self.match_score = 0.0
        
        super().save(*args, **kwargs)
    
    def calculate_certainty(self):
        """
        Calculate certainty metric based on proportion of checklist items that were decided.
        Returns a float between 0.0 and 1.0.
        """
        match_reasons = self.match_reasons or {}
        
        total_items = 0
        decided_items = 0
        
        # Count eligibility checklist items
        eligibility_checklist = match_reasons.get('eligibility_checklist', [])
        for item in eligibility_checklist:
            total_items += 1
            if item.get('status') in ['yes', 'no']:
                decided_items += 1
        
        # Count competitiveness checklist items
        competitiveness_checklist = match_reasons.get('competitiveness_checklist', [])
        for item in competitiveness_checklist:
            total_items += 1
            if item.get('status') in ['yes', 'no']:
                decided_items += 1
        
        # Exclusions checklist is NOT included in certainty calculation
        
        if total_items == 0:
            return 1.0  # No checklists = 100% certain (no uncertainty)
        
        return decided_items / total_items
    
    def __str__(self):
        return f"{self.funding_search.name} - {self.grant.title} ({self.match_score:.2f})"


class FundingQuestionnaire(models.Model):
    """Reusable questionnaire template for funding searches."""
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='funding_questionnaires'
    )
    name = models.CharField(
        max_length=255,
        help_text="Name for this questionnaire (e.g., 'AI Startup Q1 2025')"
    )
    
    # Questionnaire answers stored as JSON
    questionnaire_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Stores all questionnaire answers"
    )
    
    # Metadata
    is_default = models.BooleanField(
        default=False,
        help_text="If True, this is the default questionnaire for new funding searches"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        db_table = 'funding_questionnaires'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['user', '-updated_at']),
            models.Index(fields=['user', 'is_default']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.user.email})"
    
    def apply_to_funding_search(self, funding_search):
        """
        Apply questionnaire data to a funding search.
        Auto-populates relevant fields.
        """
        from django.utils import timezone
        from grants.models import GRANT_SOURCES
        
        data = self.questionnaire_data
        
        # Update project description
        if data.get('project_description'):
            funding_search.project_description = data['project_description']
        
        # Update TRL levels (validate against TRL_LEVELS)
        if data.get('trl_levels'):
            valid_trl_values = [choice[0] for choice in TRL_LEVELS]
            validated_trl_levels = [
                level for level in data['trl_levels']
                if level in valid_trl_values
            ]
            funding_search.trl_levels = validated_trl_levels
        
        # Handle let_system_decide_trl flag
        if data.get('let_system_decide_trl'):
            funding_search.let_system_decide_trl = True
        
        # Update grant sources preference (validate against GRANT_SOURCES)
        if data.get('grant_sources_preference'):
            valid_source_codes = [source[0] for source in GRANT_SOURCES]
            validated_sources = [
                source for source in data['grant_sources_preference']
                if source in valid_source_codes and source != 'all'
            ]
            # If 'all' was selected, leave empty list to match all sources
            if 'all' in data['grant_sources_preference']:
                funding_search.selected_grant_sources = []
            else:
                funding_search.selected_grant_sources = validated_sources
        
        # Update notes with additional context
        if data.get('additional_information'):
            if funding_search.notes:
                funding_search.notes += f"\n\nQuestionnaire Context: {data['additional_information']}"
            else:
                funding_search.notes = f"Questionnaire Context: {data['additional_information']}"
        
        funding_search.save()
        
        # Update last used timestamp
        self.last_used_at = timezone.now()
        self.save(update_fields=['last_used_at'])

