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
    # Legacy single notes field (kept for backwards compatibility)
    notes = models.TextField(blank=True, null=True)
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


class CompanyNote(models.Model):
    """Individual notes attached to a company."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='company_notes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='company_notes')
    title = models.CharField(max_length=255, blank=True, null=True)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'company_notes'
        ordering = ['-created_at']

    def __str__(self):
        base = self.title or (self.body[:50] + '...' if len(self.body) > 50 else self.body)
        return f"{self.company.name} - {base}"


class CompanyFile(models.Model):
    """Files uploaded for a company (e.g., supporting docs)."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='files')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='company_files')
    file = models.FileField(upload_to='company_files/%Y/%m/')
    original_name = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'company_files'
        ordering = ['-created_at']

    def __str__(self):
        return self.original_name or self.file.name


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
    selected_company_files = models.ManyToManyField('CompanyFile', blank=True, related_name='funding_searches')
    selected_company_notes = models.ManyToManyField('CompanyNote', blank=True, related_name='funding_searches')
    use_company_website = models.BooleanField(default=False)  # Whether to use company website as a source
    
    # Grant source selection for matching
    selected_grant_sources = models.JSONField(default=list, blank=True)  # List of grant source codes to match against (e.g., ['ukri', 'nihr'])
    
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
        Compile text from all selected input sources for matching.
        Returns combined text from:
        - Selected company files (extracted text)
        - Selected company notes (body text)
        - Company website (if selected - includes URL)
        - Uploaded file (if exists - extracted text)
        - Project description (if exists - for backward compatibility)
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
        
        # Add project description if it exists (for backward compatibility)
        if self.project_description:
            text_parts.append(f"Project Description:\n{self.project_description}\n")
        
        # Add selected company notes
        selected_notes = self.selected_company_notes.all()
        if selected_notes:
            notes_text = "\n\n".join([
                f"Note: {note.title or 'Untitled'}\n{note.body}"
                for note in selected_notes
            ])
            text_parts.append(f"Company Notes:\n{notes_text}\n")
        
        # Add selected company files (extract text)
        selected_files = self.selected_company_files.all()
        for company_file in selected_files:
            try:
                file = company_file.file
                file_name = company_file.original_name or file.name
                
                # Determine file type
                file_name_lower = file_name.lower()
                if file_name_lower.endswith('.pdf'):
                    file_type = 'pdf'
                elif file_name_lower.endswith('.docx'):
                    file_type = 'docx'
                elif file_name_lower.endswith('.txt'):
                    file_type = 'txt'
                else:
                    file_type = 'txt'  # Default
                
                # Extract text from file
                with file.open('rb') as f:
                    extracted_text = extract_text_from_file(f, file_type)
                
                if extracted_text:
                    text_parts.append(f"Company File: {file_name}\n{extracted_text}\n")
            except Exception as e:
                # If extraction fails, just include the filename
                file_name = company_file.original_name or (company_file.file.name if company_file.file else 'Unknown')
                text_parts.append(f"Company File: {file_name} (text extraction failed: {str(e)})\n")
        
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
        
        # Add company website if selected (scrape content)
        if self.use_company_website and self.company.website:
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
    match_score = models.FloatField(db_index=True)  # 0.0 to 1.0 - Overall score (average of eligibility and competitiveness)
    eligibility_score = models.FloatField(null=True, blank=True, db_index=True)  # 0.0 to 1.0 - How well the project meets eligibility criteria
    competitiveness_score = models.FloatField(null=True, blank=True, db_index=True)  # 0.0 to 1.0 - How competitive the project is for this grant
    match_reasons = models.JSONField(default=dict)  # e.g., {"explanation": "...", "alignment_points": [], "concerns": []}
    matched_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'grant_match_results'
        unique_together = [['funding_search', 'grant']]
        ordering = ['-match_score']
        indexes = [
            models.Index(fields=['funding_search', '-match_score']),
        ]
    
    def save(self, *args, **kwargs):
        # Calculate overall match_score as average of eligibility and competitiveness if both are provided
        if self.eligibility_score is not None and self.competitiveness_score is not None:
            self.match_score = (self.eligibility_score + self.competitiveness_score) / 2.0
        elif self.match_score is None:
            # Fallback: if no component scores and no match_score set, default to 0
            self.match_score = 0.0
        # If only one component score is provided, keep the existing match_score (don't recalculate)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.funding_search.name} - {self.grant.title} ({self.match_score:.2f})"

