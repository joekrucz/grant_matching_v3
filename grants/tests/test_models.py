"""
Tests for Grant model.
"""
import pytest
from django.utils import timezone
from datetime import timedelta
from grants.models import Grant
from grants.tests.factories import GrantFactory, ClosedGrantFactory


@pytest.mark.django_db
class TestGrant:
    """Test Grant model methods."""
    
    def test_grant_str(self):
        """Test grant string representation."""
        grant = GrantFactory(title='Test Grant', source='ukri')
        assert str(grant) == 'Test Grant (ukri)'
    
    def test_get_computed_status_open(self):
        """Test computed status for open grant."""
        future = timezone.now() + timedelta(days=30)
        grant = GrantFactory(deadline=future, opening_date=None)
        assert grant.get_computed_status() == 'open'
    
    def test_get_computed_status_closed(self):
        """Test computed status for closed grant."""
        past = timezone.now() - timedelta(days=1)
        grant = GrantFactory(deadline=past)
        assert grant.get_computed_status() == 'closed'
    
    def test_get_computed_status_unknown(self):
        """Test computed status for grant with no dates."""
        grant = GrantFactory(deadline=None, opening_date=None)
        assert grant.get_computed_status() == 'unknown'
    
    def test_get_computed_status_with_opening_date(self):
        """Test computed status with opening date in past."""
        past = timezone.now() - timedelta(days=10)
        future = timezone.now() + timedelta(days=20)
        grant = GrantFactory(deadline=future, opening_date=past)
        assert grant.get_computed_status() == 'open'
    
    def test_computed_status_property(self):
        """Test computed_status property."""
        grant = GrantFactory(deadline=timezone.now() + timedelta(days=30))
        assert grant.computed_status == 'open'
    
    def test_generate_slug(self):
        """Test slug generation."""
        slug = Grant.generate_slug('Test Grant Title', 'ukri')
        assert slug is not None
        assert 'test-grant-title' in slug.lower()
        assert 'ukri' in slug.lower()
    
    def test_generate_slug_uniqueness(self):
        """Test slug generation ensures uniqueness."""
        # Create a grant with a slug
        existing = GrantFactory(slug='test-grant-ukri', source='ukri')
        
        # Generate slug for same title/source
        new_slug = Grant.generate_slug('Test Grant', 'ukri')
        assert new_slug != existing.slug  # Should be different
    
    def test_calculate_hash(self):
        """Test hash calculation for grant data."""
        grant_data = {
            'title': 'Test Grant',
            'source': 'ukri',
            'url': 'https://example.com',
            'summary': 'Test summary',
            'description': 'Test description',
            'funding_amount': '£100,000',
            'deadline': '2024-12-31',
            'status': 'open'
        }
        hash1 = Grant.calculate_hash(grant_data)
        hash2 = Grant.calculate_hash(grant_data)
        
        assert hash1 == hash2  # Same data = same hash
        assert len(hash1) == 64  # SHA256 hex length
    
    def test_calculate_hash_different_data(self):
        """Test hash changes with different data."""
        grant_data1 = {'title': 'Grant 1', 'source': 'ukri'}
        grant_data2 = {'title': 'Grant 2', 'source': 'ukri'}
        
        hash1 = Grant.calculate_hash(grant_data1)
        hash2 = Grant.calculate_hash(grant_data2)
        
        assert hash1 != hash2  # Different data = different hash
    
    def test_upsert_from_payload_creates_new(self):
        """Test upsert creates new grant."""
        grants_data = [{
            'title': 'New Grant',
            'source': 'ukri',
            'url': 'https://example.com/grant',
            'summary': 'Test summary',
            'hash_checksum': 'abc123'
        }]
        
        result = Grant.upsert_from_payload(grants_data)
        
        assert result['created'] == 1
        assert result['updated'] == 0
        assert result['skipped'] == 0
        assert Grant.objects.filter(title='New Grant').exists()
    
    def test_upsert_from_payload_updates_existing(self):
        """Test upsert updates existing grant when hash changes."""
        # Create existing grant
        existing = GrantFactory(
            title='Existing Grant',
            source='ukri',
            hash_checksum='old_hash'
        )
        
        # Upsert with same slug but different hash
        grants_data = [{
            'title': 'Existing Grant',
            'source': 'ukri',
            'slug': existing.slug,
            'url': 'https://example.com/grant',
            'summary': 'Updated summary',
            'hash_checksum': 'new_hash'
        }]
        
        result = Grant.upsert_from_payload(grants_data)
        
        assert result['created'] == 0
        assert result['updated'] == 1
        assert result['skipped'] == 0
        
        existing.refresh_from_db()
        assert existing.hash_checksum == 'new_hash'
        assert existing.summary == 'Updated summary'
    
    def test_upsert_from_payload_skips_unchanged(self):
        """Test upsert skips grant when hash unchanged."""
        existing = GrantFactory(
            title='Existing Grant',
            source='ukri',
            hash_checksum='same_hash'
        )
        
        grants_data = [{
            'title': 'Existing Grant',
            'source': 'ukri',
            'slug': existing.slug,
            'hash_checksum': 'same_hash'
        }]
        
        result = Grant.upsert_from_payload(grants_data)
        
        assert result['created'] == 0
        assert result['updated'] == 0
        assert result['skipped'] == 1
    
    def test_upsert_from_payload_skips_invalid(self):
        """Test upsert skips grants without required fields."""
        grants_data = [
            {'title': 'Grant without source'},  # Missing source
            {'source': 'ukri'},  # Missing title
            {}  # Empty
        ]
        
        result = Grant.upsert_from_payload(grants_data)
        
        assert result['created'] == 0
        assert result['updated'] == 0
        assert result['skipped'] == 3




