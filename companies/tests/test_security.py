"""
Tests for security functions (SSRF protection, URL validation).
"""
import pytest
from unittest.mock import patch, MagicMock
from companies.security import (
    validate_website_url,
    validate_url_for_ssrf,
    is_private_ip,
    resolve_hostname
)


class TestIsPrivateIP:
    """Test private IP detection."""
    
    def test_private_ipv4_detection(self):
        """Test detection of private IPv4 addresses."""
        assert is_private_ip('192.168.1.1') is True
        assert is_private_ip('10.0.0.1') is True
        assert is_private_ip('172.16.0.1') is True
        assert is_private_ip('127.0.0.1') is True
    
    def test_public_ipv4_detection(self):
        """Test public IPv4 addresses are not flagged."""
        assert is_private_ip('8.8.8.8') is False
        assert is_private_ip('1.1.1.1') is False
    
    def test_invalid_ip(self):
        """Test invalid IP addresses."""
        assert is_private_ip('not.an.ip') is False
        assert is_private_ip('') is False


class TestResolveHostname:
    """Test hostname resolution."""
    
    @patch('companies.security.socket.getaddrinfo')
    def test_resolve_hostname_success(self, mock_getaddrinfo):
        """Test successful hostname resolution."""
        mock_getaddrinfo.return_value = [
            (None, None, None, None, ('93.184.216.34', None))
        ]
        ips = resolve_hostname('example.com')
        assert '93.184.216.34' in ips
    
    @patch('companies.security.socket.getaddrinfo')
    def test_resolve_hostname_failure(self, mock_getaddrinfo):
        """Test hostname resolution failure."""
        mock_getaddrinfo.side_effect = Exception('DNS error')
        ips = resolve_hostname('nonexistent.example.com')
        assert ips == []


class TestValidateURLForSSRF:
    """Test SSRF URL validation."""
    
    def test_valid_https_url(self):
        """Test valid HTTPS URL passes."""
        is_valid, error = validate_url_for_ssrf('https://example.com')
        assert is_valid is True
        assert error is None
    
    def test_valid_http_url(self):
        """Test valid HTTP URL passes."""
        is_valid, error = validate_url_for_ssrf('http://example.com')
        assert is_valid is True
        assert error is None
    
    def test_invalid_scheme(self):
        """Test invalid URL scheme is rejected."""
        is_valid, error = validate_url_for_ssrf('ftp://example.com')
        assert is_valid is False
        assert 'scheme' in error.lower()
    
    def test_empty_url(self):
        """Test empty URL is rejected."""
        is_valid, error = validate_url_for_ssrf('')
        assert is_valid is False
        assert error is not None
    
    def test_none_url(self):
        """Test None URL is rejected."""
        is_valid, error = validate_url_for_ssrf(None)
        assert is_valid is False
        assert error is not None
    
    def test_localhost_rejected(self):
        """Test localhost is rejected."""
        is_valid, error = validate_url_for_ssrf('https://localhost')
        assert is_valid is False
        assert 'localhost' in error.lower()
    
    def test_127_0_0_1_rejected(self):
        """Test 127.0.0.1 is rejected."""
        is_valid, error = validate_url_for_ssrf('https://127.0.0.1')
        assert is_valid is False
    
    @patch('companies.security.resolve_hostname')
    def test_private_ip_rejected(self, mock_resolve):
        """Test URL resolving to private IP is rejected."""
        mock_resolve.return_value = ['192.168.1.1']
        is_valid, error = validate_url_for_ssrf('https://internal.example.com')
        assert is_valid is False
        assert 'private' in error.lower()
    
    @patch('companies.security.resolve_hostname')
    def test_public_ip_allowed(self, mock_resolve):
        """Test URL resolving to public IP is allowed."""
        mock_resolve.return_value = ['8.8.8.8']
        is_valid, error = validate_url_for_ssrf('https://example.com')
        assert is_valid is True
    
    def test_metadata_hostname_rejected(self):
        """Test metadata service hostnames are rejected."""
        is_valid, error = validate_url_for_ssrf('https://metadata.google.internal')
        assert is_valid is False
        assert 'metadata' in error.lower()


class TestValidateWebsiteURL:
    """Test website URL validation."""
    
    def test_valid_https_url(self):
        """Test valid HTTPS URL passes."""
        is_valid, error = validate_website_url('https://example.com')
        assert is_valid is True
        assert error is None
    
    def test_empty_url_allowed(self):
        """Test empty URL is allowed (optional field)."""
        is_valid, error = validate_website_url('')
        assert is_valid is True
        assert error is None
    
    def test_none_url_allowed(self):
        """Test None URL is allowed (optional field)."""
        is_valid, error = validate_website_url(None)
        assert is_valid is True
        assert error is None
    
    def test_invalid_url_rejected(self):
        """Test invalid URL is rejected."""
        is_valid, error = validate_website_url('not-a-url')
        assert is_valid is False
        assert error is not None
    
    def test_localhost_rejected(self):
        """Test localhost is rejected."""
        is_valid, error = validate_website_url('https://localhost')
        assert is_valid is False
        assert 'localhost' in error.lower()
    
    def test_url_without_netloc_rejected(self):
        """Test URL without netloc is rejected."""
        is_valid, error = validate_website_url('https://')
        assert is_valid is False




