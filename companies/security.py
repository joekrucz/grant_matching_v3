"""
Security utilities for the companies app.
"""
import ipaddress
import socket
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)

# Private/internal IP ranges to block
PRIVATE_IP_RANGES = [
    ipaddress.IPv4Network('10.0.0.0/8'),
    ipaddress.IPv4Network('172.16.0.0/12'),
    ipaddress.IPv4Network('192.168.0.0/16'),
    ipaddress.IPv4Network('127.0.0.0/8'),
    ipaddress.IPv4Network('169.254.0.0/16'),  # Link-local
    ipaddress.IPv4Network('224.0.0.0/4'),  # Multicast
]

# Blocked hostnames
BLOCKED_HOSTNAMES = [
    'localhost',
    '127.0.0.1',
    '0.0.0.0',
    '::1',
    '[::1]',
]

# Allowed URL schemes
ALLOWED_SCHEMES = ['http', 'https']


def is_private_ip(ip_str):
    """Check if an IP address is private/internal."""
    try:
        ip = ipaddress.ip_address(ip_str)
        # Check if it's in any private range
        for private_range in PRIVATE_IP_RANGES:
            if ip in private_range:
                return True
        # Also check if it's IPv6 loopback
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return True
        return False
    except ValueError:
        return False


def resolve_hostname(hostname):
    """Resolve hostname to IP addresses."""
    try:
        # Get all IP addresses for the hostname
        ip_addresses = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        return [info[4][0] for info in ip_addresses]
    except (socket.gaierror, socket.herror, OSError):
        return []


def validate_url_for_ssrf(url):
    """
    Validate URL to prevent SSRF attacks.
    
    Args:
        url: URL string to validate
        
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    if not url or not isinstance(url, str):
        return False, "URL must be a non-empty string"
    
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Invalid URL format: {str(e)}"
    
    # Check scheme
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"URL scheme must be http or https, got: {parsed.scheme}"
    
    # Check hostname
    hostname = parsed.hostname
    if not hostname:
        return False, "URL must have a hostname"
    
    # Check against blocked hostnames (case-insensitive)
    if hostname.lower() in [h.lower() for h in BLOCKED_HOSTNAMES]:
        return False, f"Hostname '{hostname}' is not allowed"
    
    # Resolve hostname and check IP addresses
    ip_addresses = resolve_hostname(hostname)
    if not ip_addresses:
        # If we can't resolve, be cautious - allow only in DEBUG mode
        import django.conf
        if not django.conf.settings.DEBUG:
            return False, f"Could not resolve hostname '{hostname}'"
        logger.warning(f"Could not resolve hostname '{hostname}', allowing in DEBUG mode")
    else:
        # Check all resolved IPs
        for ip in ip_addresses:
            if is_private_ip(ip):
                return False, f"Hostname '{hostname}' resolves to private IP '{ip}' which is not allowed"
    
    # Additional checks for common SSRF targets
    if hostname.lower().startswith('metadata.') or 'metadata' in hostname.lower():
        return False, "Metadata service hostnames are not allowed"
    
    return True, None


def validate_website_url(url):
    """
    Validate website URL before storage.
    
    Args:
        url: URL string to validate
        
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    if not url:
        return True, None  # Empty URL is allowed (optional field)
    
    # Basic format validation
    is_valid, error = validate_url_for_ssrf(url)
    if not is_valid:
        return False, error
    
    # Additional validation: ensure it's a proper website URL
    parsed = urlparse(url)
    if not parsed.netloc:
        return False, "Invalid website URL format"
    
    return True, None

