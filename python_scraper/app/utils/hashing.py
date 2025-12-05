import hashlib
from typing import Any, Dict


def sha256_for_grant(payload: Dict[str, Any]) -> str:
  """
  Compute a stable SHA256 hash for a grant based on key fields.
  """
  parts = [
      payload.get("source", "") or "",
      payload.get("title", "") or "",
      payload.get("url", "") or "",
      payload.get("deadline", "") or "",
      payload.get("description", "") or "",
      payload.get("funding_amount", "") or "",
  ]
  base = "||".join(parts)
  return hashlib.sha256(base.encode("utf-8")).hexdigest()

