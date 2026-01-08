import hashlib
import json
from typing import Any, Dict


def sha256_for_grant(payload: Dict[str, Any]) -> str:
  """
  Compute a stable SHA256 hash for a grant based on key fields.
  This must match Django's calculate_hash method in grants/models.py.
  """
  # Create a normalized representation matching Django's hash_data structure
  hash_data = {
      'title': payload.get('title', '') or '',
      'source': payload.get('source', '') or '',
      'summary': payload.get('summary', '') or '',
      'description': payload.get('description', '') or '',
      'url': payload.get('url', '') or '',
      'funding_amount': payload.get('funding_amount', '') or '',
      'deadline': str(payload.get('deadline', '')) if payload.get('deadline') else '',
      'status': payload.get('status', 'unknown') or 'unknown',
  }
  # Sort keys for consistent hashing (matching Django's sort_keys=True)
  hash_string = json.dumps(hash_data, sort_keys=True)
  return hashlib.sha256(hash_string.encode('utf-8')).hexdigest()

