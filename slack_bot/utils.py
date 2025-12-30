"""
Utility functions for Slack bot.
"""
import re
import hmac
import hashlib
import time
from django.conf import settings


def verify_slack_signature(request_body, timestamp, signature):
    """
    Verify Slack request signature.
    
    Args:
        request_body: Raw request body (bytes)
        timestamp: X-Slack-Request-Timestamp header
        signature: X-Slack-Signature header
        
    Returns:
        bool: True if signature is valid
    """
    signing_secret = getattr(settings, 'SLACK_SIGNING_SECRET', None)
    if not signing_secret:
        return False
    
    # Check timestamp (prevent replay attacks)
    if abs(time.time() - int(timestamp)) > 60 * 5:  # 5 minutes
        return False
    
    # Create signature base string
    sig_basestring = f"v0:{timestamp}:{request_body.decode('utf-8')}"
    
    # Create signature
    my_signature = 'v0=' + hmac.new(
        signing_secret.encode('utf-8'),
        sig_basestring.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Compare signatures using constant-time comparison
    return hmac.compare_digest(my_signature, signature)


def extract_company_number(text):
    """
    Extract company number from Slack message text.
    
    Supports formats:
    - 8 digits: 12345678
    - 2 letters + 6 digits: AB123456
    
    Args:
        text: Message text from Slack
        
    Returns:
        str or None: Company number if found, None otherwise
    """
    if not text:
        return None
    
    # Convert to uppercase for consistency
    text = text.upper().strip()
    
    # Patterns for UK company numbers
    patterns = [
        r'\b([0-9]{8})\b',  # 8 digits
        r'\b([A-Z]{2}[0-9]{6})\b',  # 2 letters + 6 digits
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    
    return None


def is_company_number(text):
    """
    Check if text looks like a company number.
    
    Args:
        text: Text to check
        
    Returns:
        bool: True if text matches company number pattern
    """
    if not text:
        return False
    
    text = text.upper().strip()
    patterns = [
        r'^[0-9]{8}$',  # 8 digits
        r'^[A-Z]{2}[0-9]{6}$',  # 2 letters + 6 digits
    ]
    
    for pattern in patterns:
        if re.match(pattern, text):
            return True
    
    return False

