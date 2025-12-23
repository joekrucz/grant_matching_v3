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
    
    company_number = models.CharField(max_length=20, unique=True, db_index=True, blank=True, null=True)
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


class FundingSearch(models.Model):
    """Funding search criteria for a company."""
    
    MATCHING_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('error', 'Error'),
    ]
    
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='funding_searches')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='funding_searches')
    name = models.CharField(max_length=255)
    notes = models.TextField(blank=True, null=True)
    trl_level = models.CharField(max_length=255, choices=TRL_LEVELS, blank=True, null=True)
    
    # Matching fields
    project_description = models.TextField(blank=True, null=True)  # Text input or extracted from file
    uploaded_file = models.FileField(upload_to='funding_searches/%Y/%m/', blank=True, null=True)
    file_type = models.CharField(max_length=50, blank=True, null=True)  # 'pdf', 'docx', 'txt', 'text'
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
    match_score = models.FloatField(db_index=True)  # 0.0 to 1.0
    match_reasons = models.JSONField(default=dict)  # e.g., {"explanation": "...", "alignment_points": [], "concerns": []}
    matched_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'grant_match_results'
        unique_together = [['funding_search', 'grant']]
        ordering = ['-match_score']
        indexes = [
            models.Index(fields=['funding_search', '-match_score']),
        ]
    
    def __str__(self):
        return f"{self.funding_search.name} - {self.grant.title} ({self.match_score:.2f})"

