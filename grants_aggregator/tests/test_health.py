"""
Tests for health check endpoint.
"""
import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestHealthCheck:
    """Test health check endpoint."""
    
    def test_health_check(self, client):
        """Test health check endpoint returns OK."""
        response = client.get('/health/')
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'healthy'
        assert data['database'] == 'ok'
        assert data['cache'] == 'ok'

