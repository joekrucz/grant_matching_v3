"""
Tests for security utilities.
"""
import pytest
from django.test import RequestFactory
from grants_aggregator.security_utils import safe_json_loads


@pytest.mark.django_db
class TestSafeJsonLoads:
    """Test safe JSON loading with size limits."""
    
    def test_valid_json(self):
        """Test valid JSON is parsed correctly."""
        rf = RequestFactory()
        request = rf.post(
            '/test',
            data='{"key": "value"}',
            content_type='application/json'
        )
        
        data, error = safe_json_loads(request)
        assert data is not None
        assert data['key'] == 'value'
        assert error is None
    
    def test_invalid_json(self):
        """Test invalid JSON returns error."""
        rf = RequestFactory()
        request = rf.post(
            '/test',
            data='not json',
            content_type='application/json'
        )
        
        data, error = safe_json_loads(request)
        assert data is None
        assert error is not None
        assert error.status_code == 400
    
    def test_json_too_large(self):
        """Test JSON exceeding size limit is rejected."""
        rf = RequestFactory()
        large_data = 'x' * (11 * 1024 * 1024)  # 11MB
        request = rf.post(
            '/test',
            data=large_data,
            content_type='application/json'
        )
        
        data, error = safe_json_loads(request, max_size=10 * 1024 * 1024)
        assert data is None
        assert error is not None
        assert error.status_code == 413
    
    def test_empty_body(self):
        """Test empty request body."""
        rf = RequestFactory()
        request = rf.post('/test', data='', content_type='application/json')
        
        data, error = safe_json_loads(request)
        assert data == {}
        assert error is None






