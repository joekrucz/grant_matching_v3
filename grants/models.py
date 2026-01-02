"""
Grant and ScrapeLog models.
"""
import hashlib
import json
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify


GRANT_SOURCES = [
    ('ukri', 'UKRI'),
    ('nihr', 'NIHR'),
    ('catapult', 'Catapult'),
    ('innovate_uk', 'Innovate UK'),
]

GRANT_STATUSES = [
    ('open', 'Open'),
    ('closed', 'Closed'),
    ('unknown', 'Unknown'),
]

SCRAPE_STATUSES = [
    ('running', 'Running'),
    ('success', 'Success'),
    ('error', 'Error'),
    ('cancelled', 'Cancelled'),
]


class Grant(models.Model):
    """Grant model representing a funding opportunity."""
    
    title = models.CharField(max_length=500, db_index=True)
    slug = models.SlugField(max_length=500, unique=True, db_index=True)
    source = models.CharField(max_length=50, choices=GRANT_SOURCES, db_index=True)
    summary = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    url = models.URLField(blank=True, null=True)
    funding_amount = models.CharField(max_length=255, blank=True, null=True)
    deadline = models.DateTimeField(blank=True, null=True, db_index=True)
    opening_date = models.DateTimeField(blank=True, null=True, db_index=True)
    status = models.CharField(max_length=50, choices=GRANT_STATUSES, default='unknown', db_index=True)
    raw_data = models.JSONField(default=dict, blank=True)
    eligibility_checklist = models.JSONField(default=dict, blank=True, null=True)
    competitiveness_checklist = models.JSONField(default=dict, blank=True, null=True)
    exclusions_checklist = models.JSONField(default=dict, blank=True, null=True)
    scraped_at = models.DateTimeField(blank=True, null=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_changed_at = models.DateTimeField(blank=True, null=True)
    hash_checksum = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'grants'
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['hash_checksum']),
            models.Index(fields=['source', 'deadline']),
        ]
        unique_together = [['slug', 'source']]
    
    def __str__(self):
        return f"{self.title} ({self.source})"
    
    def get_computed_status(self):
        """
        Calculate grant status based on opening_date and deadline.
        Returns: 'open', 'closed', or 'unknown'
        """
        now = timezone.now()
        
        # If we have a deadline
        if self.deadline:
            if self.deadline < now:
                return 'closed'
            # Deadline is in the future
            # Check if it's opened yet
            if self.opening_date:
                if self.opening_date <= now:
                    return 'open'
                else:
                    # Opening date is in the future
                    return 'open'  # Consider it open if deadline exists and is future
            else:
                # No opening date, but deadline is in future - assume open
                return 'open'
        
        # No deadline - check opening date
        if self.opening_date:
            if self.opening_date <= now:
                return 'open'  # Opened but no closing date (open-ended)
            else:
                return 'open'  # Not opened yet, but will open (treat as open)
        
        # No dates at all
        return 'unknown'
    
    @property
    def computed_status(self):
        """Property to access computed status (for backward compatibility)."""
        return self.get_computed_status()
    
    def get_status_display(self):
        """Override to use computed status instead of stored status."""
        status = self.get_computed_status()
        status_dict = dict(GRANT_STATUSES)
        return status_dict.get(status, 'Unknown')
    
    @classmethod
    def generate_slug(cls, title, source):
        """Generate a unique slug from title and source."""
        base_slug = slugify(f"{title} {source}")
        slug = base_slug[:500]  # Ensure it fits in the field
        counter = 1
        while cls.objects.filter(slug=slug, source=source).exists():
            slug = f"{base_slug[:490]}-{counter}"
            counter += 1
        return slug
    
    @classmethod
    def calculate_hash(cls, grant_data):
        """Calculate SHA256 hash of grant content for change detection."""
        # Create a normalized representation of the grant data
        hash_data = {
            'title': grant_data.get('title', ''),
            'source': grant_data.get('source', ''),
            'summary': grant_data.get('summary', ''),
            'description': grant_data.get('description', ''),
            'url': grant_data.get('url', ''),
            'funding_amount': grant_data.get('funding_amount', ''),
            'deadline': str(grant_data.get('deadline', '')),
            'status': grant_data.get('status', 'unknown'),
        }
        # Sort keys for consistent hashing
        hash_string = json.dumps(hash_data, sort_keys=True)
        return hashlib.sha256(hash_string.encode()).hexdigest()
    
    @classmethod
    def upsert_from_payload(cls, grants_data, log_id=None, grants_found=None):
        """
        Upsert grants from a list of grant dictionaries.
        
        Args:
            grants_data: List of grant dictionaries to upsert
            log_id: Optional ScrapeLog ID to update
            grants_found: Optional number of grants found (if not provided, uses len(grants_data))
        
        Returns dict with 'created', 'updated', 'skipped' counts.
        """
        created = 0
        updated = 0
        skipped = 0
        
        for grant_data in grants_data:
            source = grant_data.get('source')
            title = grant_data.get('title')
            
            if not source or not title:
                skipped += 1
                continue
            
            # Generate slug if not provided
            slug = grant_data.get('slug') or cls.generate_slug(title, source)
            
            # Calculate hash
            hash_checksum = grant_data.get('hash_checksum') or cls.calculate_hash(grant_data)
            
            # Get URL for fallback lookup
            url = grant_data.get('url', '')
            
            # Try to find existing grant - check by slug first, then by URL
            grant = None
            try:
                # First try: lookup by slug and source (primary method)
                grant = cls.objects.get(slug=slug, source=source)
            except cls.DoesNotExist:
                # Second try: if URL is provided, lookup by URL and source (fallback)
                if url:
                    try:
                        grant = cls.objects.get(url=url, source=source)
                        # Update slug if it changed (e.g., title normalization)
                        if grant.slug != slug:
                            grant.slug = slug
                    except cls.DoesNotExist:
                        pass
            
            if grant:
                # Grant exists - check if hash changed
                if grant.hash_checksum != hash_checksum:
                    # Update grant
                    grant.title = title
                    grant.summary = grant_data.get('summary', grant.summary)
                    grant.description = grant_data.get('description', grant.description)
                    grant.url = grant_data.get('url', grant.url)
                    grant.funding_amount = grant_data.get('funding_amount', grant.funding_amount)
                    grant.deadline = grant_data.get('deadline')
                    grant.opening_date = grant_data.get('opening_date')
                    # Status is now computed from dates, so we don't update it here
                    grant.raw_data = grant_data.get('raw_data', grant.raw_data)
                    grant.scraped_at = grant_data.get('scraped_at') or timezone.now()
                    grant.hash_checksum = hash_checksum
                    grant.last_changed_at = timezone.now()
                    grant.save()
                    updated += 1
                else:
                    # No changes, skip
                    skipped += 1
            else:
                # Grant doesn't exist - create new grant
                grant = cls.objects.create(
                    title=title,
                    slug=slug,
                    source=source,
                    summary=grant_data.get('summary', ''),
                    description=grant_data.get('description', ''),
                    url=grant_data.get('url', ''),
                    funding_amount=grant_data.get('funding_amount', ''),
                    deadline=grant_data.get('deadline'),
                    opening_date=grant_data.get('opening_date'),
                    status='unknown',  # Status is computed from dates, default to unknown
                    raw_data=grant_data.get('raw_data', {}),
                    scraped_at=grant_data.get('scraped_at') or timezone.now(),
                    hash_checksum=hash_checksum,
                    first_seen_at=timezone.now(),
                )
                created += 1
        
        # Update ScrapeLog if log_id provided
        # Note: Using string reference to avoid circular dependency
        if log_id:
            try:
                # Import here to avoid circular dependency
                from grants.models import ScrapeLog
                scrape_log = ScrapeLog.objects.get(id=log_id)
                # Use provided grants_found, or fall back to len(grants_data)
                grants_found_count = grants_found if grants_found is not None else len(grants_data)
                
                # Debug logging
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Updating ScrapeLog {log_id}: grants_found={grants_found_count} (provided={grants_found}, fallback={len(grants_data)})")
                
                scrape_log.grants_found = grants_found_count
                scrape_log.grants_created = created
                scrape_log.grants_updated = updated
                scrape_log.grants_skipped = skipped
                scrape_log.save(update_fields=['grants_found', 'grants_created', 'grants_updated', 'grants_skipped'])
                logger.info(f"Successfully updated ScrapeLog {log_id}: grants_found={scrape_log.grants_found}")
            except ScrapeLog.DoesNotExist:
                # Log if log doesn't exist
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"ScrapeLog with id {log_id} does not exist")
            except Exception as e:
                # Log other errors instead of silently failing
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error updating ScrapeLog {log_id}: {e}", exc_info=True)
        
        return {
            'created': created,
            'updated': updated,
            'skipped': skipped,
        }


class ScrapeLog(models.Model):
    """Log entry for each scraper run."""
    
    source = models.CharField(max_length=50, choices=GRANT_SOURCES, db_index=True)
    status = models.CharField(max_length=50, choices=SCRAPE_STATUSES, default='running', db_index=True)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    grants_found = models.IntegerField(default=0)
    grants_created = models.IntegerField(default=0)
    grants_updated = models.IntegerField(default=0)
    grants_skipped = models.IntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'scrape_logs'
        indexes = [
            models.Index(fields=['source']),
            models.Index(fields=['status']),
            models.Index(fields=['started_at']),
        ]
        ordering = ['-started_at']
    
    def __str__(self):
        return f"{self.source} - {self.status} - {self.started_at}"
    
    def duration_seconds(self):
        """Return duration in seconds if completed."""
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    def total_grants_processed(self):
        """Return total grants processed."""
        return self.grants_created + self.grants_updated + self.grants_skipped


class EligibilityQuestionnaire(models.Model):
    """Store saved eligibility questionnaires with user selections."""
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='eligibility_questionnaires'
    )
    name = models.CharField(max_length=255, blank=True, null=True)
    selected_items = models.JSONField(default=list)  # List of selected item texts
    all_items = models.JSONField(default=list)  # All items available at time of creation
    total_grants = models.IntegerField(default=0)  # Total grants with checklists at time of creation
    sales_questionnaire = models.JSONField(default=dict, blank=True, null=True)  # Generated sales qualification questionnaire from ChatGPT
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'eligibility_questionnaires'
        indexes = [
            models.Index(fields=['user', 'created_at']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        name = self.name or f"Questionnaire {self.id}"
        return f"{name} - {self.user.email} - {self.created_at.strftime('%Y-%m-%d')}"
    
    def selected_count(self):
        """Return count of selected items."""
        return len(self.selected_items) if self.selected_items else 0
    
    def total_items(self):
        """Return total items available."""
        return len(self.all_items) if self.all_items else 0

