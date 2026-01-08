"""
Tests for grant API endpoints (used by scraper service).
"""
import pytest
import json
from django.urls import reverse
from grants.tests.factories import GrantFactory


@pytest.mark.django_db
class TestGetGrantsAPI:
    """Test GET /api/grants endpoint."""
    
    def test_get_grants_requires_auth(self, client):
        """Test API requires authentication."""
        response = client.get(reverse('grants:api:api_grants'), {'source': 'ukri'})
        assert response.status_code == 401
    
    def test_get_grants_with_valid_key(self, client, settings):
        """Test API with valid API key."""
        settings.SCRAPER_API_KEY = 'test-key'
        GrantFactory(source='ukri', title='UKRI Grant 1')
        GrantFactory(source='ukri', title='UKRI Grant 2')
        GrantFactory(source='nihr', title='NIHR Grant')  # Different source
        
        response = client.get(
            reverse('grants:api:api_grants'),
            {'source': 'ukri'},
            HTTP_AUTHORIZATION='Bearer test-key'
        )
        
        assert response.status_code == 200
        data = response.json()
        assert 'grants' in data
        assert len(data['grants']) == 2
        assert all(grant['source'] == 'ukri' for grant in data['grants'])
    
    def test_get_grants_with_invalid_key(self, client, settings):
        """Test API with invalid API key."""
        settings.SCRAPER_API_KEY = 'test-key'
        
        response = client.get(
            reverse('grants:api:api_grants'),
            {'source': 'ukri'},
            HTTP_AUTHORIZATION='Bearer wrong-key'
        )
        
        assert response.status_code == 401
    
    def test_get_grants_missing_source(self, client, settings):
        """Test API without source parameter."""
        settings.SCRAPER_API_KEY = 'test-key'
        
        response = client.get(
            reverse('grants:api:api_grants'),
            HTTP_AUTHORIZATION='Bearer test-key'
        )
        
        assert response.status_code == 400


@pytest.mark.django_db
class TestUpsertGrantsAPI:
    """Test POST /api/grants/upsert endpoint."""
    
    def test_upsert_grants_requires_auth(self, client):
        """Test API requires authentication."""
        response = client.post(
            reverse('grants:api:api_grants_upsert'),
            content_type='application/json',
            data=json.dumps({'grants': []})
        )
        assert response.status_code == 401
    
    def test_upsert_grants_creates_new(self, client, settings):
        """Test upsert creates new grants."""
        settings.SCRAPER_API_KEY = 'test-key'
        
        payload = {
            'grants': [{
                'title': 'New Grant',
                'source': 'ukri',
                'url': 'https://example.com/grant',
                'summary': 'Test summary',
                'hash_checksum': 'abc123'
            }]
        }
        
        response = client.post(
            reverse('grants:api:api_grants_upsert'),
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_AUTHORIZATION='Bearer test-key'
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['created'] == 1
        assert data['updated'] == 0
    
    def test_upsert_grants_updates_existing(self, client, settings):
        """Test upsert updates existing grants."""
        settings.SCRAPER_API_KEY = 'test-key'
        
        # Create existing grant
        existing = GrantFactory(
            title='Existing Grant',
            source='ukri',
            hash_checksum='old_hash'
        )
        
        payload = {
            'grants': [{
                'title': 'Existing Grant',
                'source': 'ukri',
                'slug': existing.slug,
                'url': 'https://example.com/grant',
                'hash_checksum': 'new_hash'
            }]
        }
        
        response = client.post(
            reverse('grants:api:api_grants_upsert'),
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_AUTHORIZATION='Bearer test-key'
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['created'] == 0
        assert data['updated'] == 1
    
    def test_upsert_grants_invalid_json(self, client, settings):
        """Test upsert with invalid JSON."""
        settings.SCRAPER_API_KEY = 'test-key'
        
        response = client.post(
            reverse('grants:api:api_grants_upsert'),
            data='not json',
            content_type='application/json',
            HTTP_AUTHORIZATION='Bearer test-key'
        )
        
        assert response.status_code == 400
    
    def test_upsert_grants_missing_grants_array(self, client, settings):
        """Test upsert without grants array."""
        settings.SCRAPER_API_KEY = 'test-key'
        
        response = client.post(
            reverse('grants:api:api_grants_upsert'),
            data=json.dumps({}),
            content_type='application/json',
            HTTP_AUTHORIZATION='Bearer test-key'
        )
        
        assert response.status_code == 400






