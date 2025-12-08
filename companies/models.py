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
        Extract and return only account filings with made up to dates.
        
        Returns:
            list: List of dicts with account filing info including made_up_to date
        """
        if not self.filing_history or not self.filing_history.get('items'):
            return []
        
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
            if not description and filing.get('description_values'):
                desc_values = filing.get('description_values', {})
                description = desc_values.get('description', '')
            
            # Extract "made up to" date from description
            made_up_to_date = None
            if description:
                # Pattern: "made up to 31 December 2024" or "made-up to 31/12/2024" etc.
                patterns = [
                    r'made[\s-]up to[\s:]+(\d{1,2}[\s/]+(?:January|February|March|April|May|June|July|August|September|October|November|December|\d{1,2})[\s/]+\d{2,4})',
                    r'made[\s-]up to[\s:]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
                    r'period ending[\s:]+(\d{1,2}[\s/]+(?:January|February|March|April|May|June|July|August|September|October|November|December|\d{1,2})[\s/]+\d{2,4})',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, description, re.IGNORECASE)
                    if match:
                        made_up_to_date = match.group(1).strip()
                        break
            
            account_filings.append({
                'filing_date': filing_date,
                'description': description,
                'made_up_to_date': made_up_to_date,
                'type': filing.get('type', ''),
                'subcategory': filing.get('subcategory', ''),
            })
        
        # Sort by filing date (most recent first)
        account_filings.sort(key=lambda x: x['filing_date'] or '', reverse=True)
        
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

