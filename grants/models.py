"""
Grant and ScrapeLog models.
"""
import hashlib
import json
from django.db import models, transaction, IntegrityError
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify


GRANT_SOURCES = [
    ('ukri', 'UKRI'),  # Fallback for grants without specific council
    ('bbsrc', 'BBSRC'),
    ('epsrc', 'EPSRC'),
    ('mrc', 'MRC'),
    ('stfc', 'STFC'),
    ('ahrc', 'AHRC'),
    ('esrc', 'ESRC'),
    ('nerc', 'NERC'),
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
    def _create_snapshot(cls, grant):
        """Create a JSON snapshot of grant data for change tracking."""
        # Helper to safely convert datetime to string
        def to_iso(dt):
            if dt is None:
                return None
            if isinstance(dt, str):
                return dt  # Already a string
            if hasattr(dt, 'isoformat'):
                return dt.isoformat()
            return str(dt)
        
        return {
            'title': grant.title,
            'summary': grant.summary,
            'description': grant.description[:1000] if grant.description else None,  # Truncate long descriptions
            'url': grant.url,
            'funding_amount': grant.funding_amount,
            'deadline': to_iso(grant.deadline),
            'opening_date': to_iso(grant.opening_date),
            'status': grant.status,
            'hash_checksum': grant.hash_checksum,
        }
    
    @classmethod
    def _detect_field_changes(cls, before_snapshot, after_snapshot):
        """Detect which fields changed between two snapshots."""
        changes = {}
        all_fields = set(before_snapshot.keys()) | set(after_snapshot.keys())
        
        for field in all_fields:
            before_val = before_snapshot.get(field)
            after_val = after_snapshot.get(field)
            
            if before_val != after_val:
                changes[field] = {
                    'before': before_val,
                    'after': after_val,
                }
        
        return changes
    
    @classmethod
    def _create_change_summary(cls, field_changes):
        """Create a human-readable summary of changes."""
        if not field_changes:
            return "No changes detected"
        
        def format_field_name(field):
            """Format field name for display (replace underscores with spaces)."""
            return field.replace('_', ' ').title()
        
        changed_fields = list(field_changes.keys())
        if len(changed_fields) == 1:
            field = changed_fields[0]
            return f"Updated {format_field_name(field)}"
        elif len(changed_fields) <= 3:
            return f"Updated {', '.join(format_field_name(f) for f in changed_fields)}"
        else:
            return f"Updated {len(changed_fields)} fields"
    
    @classmethod
    def _get_scrape_finding_model(cls):
        """Safely get ScrapeFinding model, returning None if it doesn't exist."""
        try:
            from grants.models import ScrapeFinding
            return ScrapeFinding
        except (ImportError, AttributeError):
            return None
    
    @classmethod
    def _get_scrape_run_model(cls):
        """Safely get ScrapeRun model, returning None if it doesn't exist."""
        try:
            from grants.models import ScrapeRun
            return ScrapeRun
        except (ImportError, AttributeError):
            return None
    
    @classmethod
    @transaction.atomic
    def upsert_from_payload(cls, grants_data, log_id=None, grants_found=None):
        """
        Upsert grants from a list of grant dictionaries.
        
        Args:
            grants_data: List of grant dictionaries to upsert
            log_id: Optional ScrapeLog ID to update
            grants_found: Optional number of grants found (if not provided, uses len(grants_data))
        
        Returns dict with 'created', 'updated', 'skipped' counts.
        
        Note: This method is wrapped in a transaction to ensure atomicity.
        If any grant fails, the entire operation is rolled back.
        """
        created = 0
        updated = 0
        skipped = 0
        
        # Get or create ScrapeRun for detailed reporting
        scrape_run = None
        if log_id:
            try:
                from grants.models import ScrapeLog
                from django.db import OperationalError
                ScrapeRun = cls._get_scrape_run_model()
                if ScrapeRun:
                    scrape_log = ScrapeLog.objects.get(id=log_id)
                    try:
                        scrape_run, _ = ScrapeRun.objects.get_or_create(scrape_log=scrape_log)
                    except OperationalError:
                        # Table doesn't exist yet (migrations not run) - skip detailed reporting
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.debug(f"ScrapeRun table doesn't exist yet for log_id {log_id}, skipping detailed reporting")
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Could not create ScrapeRun for log_id {log_id}: {e}", exc_info=True)
        
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
                            grant.save(update_fields=['slug'])
                    except cls.DoesNotExist:
                        pass
            
            if grant:
                # Grant exists - check if hash changed
                if grant.hash_checksum != hash_checksum:
                    # Create before snapshot
                    before_snapshot = cls._create_snapshot(grant)
                    
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
                    
                    # Create after snapshot and detect changes
                    after_snapshot = cls._create_snapshot(grant)
                    field_changes = cls._detect_field_changes(before_snapshot, after_snapshot)
                    change_summary = cls._create_change_summary(field_changes)
                    
                    # Create finding for updated grant
                    if scrape_run:
                        try:
                            # Import here to avoid issues if model doesn't exist yet
                            ScrapeFinding = cls._get_scrape_finding_model()
                            if ScrapeFinding:
                                ScrapeFinding.objects.create(
                                    scrape_run=scrape_run,
                                    finding_type='updated',
                                    grant=grant,
                                    grant_slug=grant.slug,
                                    grant_source=grant.source,
                                    grant_title=grant.title,
                                    before_snapshot=before_snapshot,
                                    after_snapshot=after_snapshot,
                                    field_changes=field_changes,
                                    change_summary=change_summary,
                                )
                        except Exception as e:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.warning(f"Could not create ScrapeFinding for updated grant: {e}", exc_info=True)
                    
                    updated += 1
                else:
                    # No changes, skip
                    skipped += 1
            else:
                # Grant doesn't exist - create new grant
                # Use get_or_create to handle race conditions where two scrapers
                # might try to create the same grant simultaneously
                try:
                    grant, was_created = cls.objects.get_or_create(
                        slug=slug,
                        source=source,
                        defaults={
                            'title': title,
                            'summary': grant_data.get('summary', ''),
                            'description': grant_data.get('description', ''),
                            'url': grant_data.get('url', ''),
                            'funding_amount': grant_data.get('funding_amount', ''),
                            'deadline': grant_data.get('deadline'),
                            'opening_date': grant_data.get('opening_date'),
                            'status': 'unknown',  # Status is computed from dates, default to unknown
                            'raw_data': grant_data.get('raw_data', {}),
                            'scraped_at': grant_data.get('scraped_at') or timezone.now(),
                            'hash_checksum': hash_checksum,
                            'first_seen_at': timezone.now(),
                        }
                    )
                    
                    if was_created:
                        # New grant was created
                        # Create snapshot for new grant
                        after_snapshot = cls._create_snapshot(grant)
                        
                        # Create finding for new grant
                        if scrape_run:
                            try:
                                # Import here to avoid issues if model doesn't exist yet
                                ScrapeFinding = cls._get_scrape_finding_model()
                                if ScrapeFinding:
                                    ScrapeFinding.objects.create(
                                        scrape_run=scrape_run,
                                        finding_type='new',
                                        grant=grant,
                                        grant_slug=grant.slug,
                                        grant_source=grant.source,
                                        grant_title=grant.title,
                                        after_snapshot=after_snapshot,
                                        change_summary="New grant discovered",
                                    )
                            except Exception as e:
                                import logging
                                logger = logging.getLogger(__name__)
                                logger.warning(f"Could not create ScrapeFinding for new grant: {e}", exc_info=True)
                        
                        created += 1
                    else:
                        # Grant was created by another process between our check and create
                        # This is a race condition - treat it as an update if hash changed
                        if grant.hash_checksum != hash_checksum:
                            # Create before snapshot
                            before_snapshot = cls._create_snapshot(grant)
                            
                            # Update grant
                            grant.title = title
                            grant.summary = grant_data.get('summary', grant.summary)
                            grant.description = grant_data.get('description', grant.description)
                            grant.url = grant_data.get('url', grant.url)
                            grant.funding_amount = grant_data.get('funding_amount', grant.funding_amount)
                            grant.deadline = grant_data.get('deadline')
                            grant.opening_date = grant_data.get('opening_date')
                            grant.raw_data = grant_data.get('raw_data', grant.raw_data)
                            grant.scraped_at = grant_data.get('scraped_at') or timezone.now()
                            grant.hash_checksum = hash_checksum
                            grant.last_changed_at = timezone.now()
                            grant.save()
                            
                            # Create after snapshot and detect changes
                            after_snapshot = cls._create_snapshot(grant)
                            field_changes = cls._detect_field_changes(before_snapshot, after_snapshot)
                            change_summary = cls._create_change_summary(field_changes)
                            
                            # Create finding for updated grant
                            if scrape_run:
                                try:
                                    ScrapeFinding = cls._get_scrape_finding_model()
                                    if ScrapeFinding:
                                        ScrapeFinding.objects.create(
                                            scrape_run=scrape_run,
                                            finding_type='updated',
                                            grant=grant,
                                            grant_slug=grant.slug,
                                            grant_source=grant.source,
                                            grant_title=grant.title,
                                            before_snapshot=before_snapshot,
                                            after_snapshot=after_snapshot,
                                            field_changes=field_changes,
                                            change_summary=change_summary,
                                        )
                                except Exception as e:
                                    import logging
                                    logger = logging.getLogger(__name__)
                                    logger.warning(f"Could not create ScrapeFinding for updated grant: {e}", exc_info=True)
                            
                            updated += 1
                        else:
                            # No changes, skip
                            skipped += 1
                            
                except IntegrityError as e:
                    # Handle case where unique constraint is violated despite get_or_create
                    # This can happen if slug+source is not the only unique constraint
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"IntegrityError creating grant {slug} from {source}: {e}. Attempting to fetch existing grant.")
                    
                    # Try to fetch the grant that was created by another process
                    try:
                        grant = cls.objects.get(slug=slug, source=source)
                        # Check if hash changed and update if needed
                        if grant.hash_checksum != hash_checksum:
                            before_snapshot = cls._create_snapshot(grant)
                            grant.title = title
                            grant.summary = grant_data.get('summary', grant.summary)
                            grant.description = grant_data.get('description', grant.description)
                            grant.url = grant_data.get('url', grant.url)
                            grant.funding_amount = grant_data.get('funding_amount', grant.funding_amount)
                            grant.deadline = grant_data.get('deadline')
                            grant.opening_date = grant_data.get('opening_date')
                            grant.raw_data = grant_data.get('raw_data', grant.raw_data)
                            grant.scraped_at = grant_data.get('scraped_at') or timezone.now()
                            grant.hash_checksum = hash_checksum
                            grant.last_changed_at = timezone.now()
                            grant.save()
                            
                            after_snapshot = cls._create_snapshot(grant)
                            field_changes = cls._detect_field_changes(before_snapshot, after_snapshot)
                            change_summary = cls._create_change_summary(field_changes)
                            
                            if scrape_run:
                                try:
                                    ScrapeFinding = cls._get_scrape_finding_model()
                                    if ScrapeFinding:
                                        ScrapeFinding.objects.create(
                                            scrape_run=scrape_run,
                                            finding_type='updated',
                                            grant=grant,
                                            grant_slug=grant.slug,
                                            grant_source=grant.source,
                                            grant_title=grant.title,
                                            before_snapshot=before_snapshot,
                                            after_snapshot=after_snapshot,
                                            field_changes=field_changes,
                                            change_summary=change_summary,
                                        )
                                except Exception as e:
                                    logger.warning(f"Could not create ScrapeFinding for updated grant: {e}", exc_info=True)
                            
                            updated += 1
                        else:
                            skipped += 1
                    except cls.DoesNotExist:
                        # Grant doesn't exist and we can't create it - skip
                        logger.error(f"Could not create or fetch grant {slug} from {source} after IntegrityError")
                        skipped += 1
        
        # Update ScrapeLog and ScrapeRun if log_id provided
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
                
                # Update ScrapeRun with finding counts (if it exists)
                if scrape_run:
                    try:
                        scrape_run.new_count = scrape_run.findings.filter(finding_type='new').count()
                        scrape_run.updated_count = scrape_run.findings.filter(finding_type='updated').count()
                        scrape_run.deleted_count = scrape_run.findings.filter(finding_type='deleted').count()
                        scrape_run.error_count = scrape_run.findings.filter(finding_type='error').count()
                        scrape_run.total_findings = scrape_run.findings.count()
                        scrape_run.save()
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"Could not update ScrapeRun counts: {e}", exc_info=True)
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


FINDING_TYPES = [
    ('new', 'New Grant'),
    ('updated', 'Updated Grant'),
    ('deleted', 'Deleted/Unavailable Grant'),
    ('error', 'Error Processing Grant'),
]


class ScrapeRun(models.Model):
    """Detailed report for a scraper run, linked to ScrapeLog."""
    
    scrape_log = models.OneToOneField(
        'ScrapeLog',
        on_delete=models.CASCADE,
        related_name='detailed_report',
        db_index=True
    )
    total_findings = models.IntegerField(default=0)
    new_count = models.IntegerField(default=0)
    updated_count = models.IntegerField(default=0)
    deleted_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'scrape_runs'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"ScrapeRun for {self.scrape_log.source} - {self.created_at}"


class ScrapeFinding(models.Model):
    """Individual finding from a scraper run (new, updated, deleted, or error)."""
    
    scrape_run = models.ForeignKey(
        'ScrapeRun',
        on_delete=models.CASCADE,
        related_name='findings',
        db_index=True
    )
    finding_type = models.CharField(max_length=20, choices=FINDING_TYPES, db_index=True)
    grant = models.ForeignKey(
        'Grant',
        on_delete=models.CASCADE,
        related_name='scrape_findings',
        null=True,
        blank=True,
        db_index=True
    )
    grant_slug = models.SlugField(max_length=500, db_index=True)  # Store slug even if grant deleted
    grant_source = models.CharField(max_length=50, choices=GRANT_SOURCES, db_index=True)
    grant_title = models.CharField(max_length=500)  # Store title for reference
    
    # Snapshot data (before/after for updates, current for new, last known for deleted)
    before_snapshot = models.JSONField(default=dict, blank=True, null=True)  # Previous state
    after_snapshot = models.JSONField(default=dict, blank=True, null=True)  # Current/new state
    
    # Change summary - human-readable description of what changed
    change_summary = models.TextField(blank=True, null=True)
    
    # Field-level changes (for updated grants)
    field_changes = models.JSONField(default=dict, blank=True, null=True)  # {'field_name': {'before': 'old', 'after': 'new'}}
    
    # Error details (for error findings)
    error_message = models.TextField(blank=True, null=True)
    error_url = models.URLField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = 'scrape_findings'
        indexes = [
            models.Index(fields=['scrape_run', 'finding_type']),
            models.Index(fields=['grant_source', 'finding_type']),
            models.Index(fields=['created_at']),
        ]
        ordering = ['-created_at', 'finding_type', 'grant_title']
    
    def __str__(self):
        return f"{self.get_finding_type_display()} - {self.grant_title} ({self.grant_source})"


