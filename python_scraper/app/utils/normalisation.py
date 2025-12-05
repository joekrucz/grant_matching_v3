from datetime import datetime, timezone
from typing import Optional
import re


def parse_deadline(raw: str | None) -> Optional[str]:
  """
  Parse deadline string into ISO format datetime string.
  Returns None if parsing fails.
  """
  if not raw:
    return None
  
  # Clean up the string - remove quotes (including curly quotes), extra whitespace
  raw = raw.strip()
  # Replace curly quotes with regular quotes, then remove all quotes
  raw = raw.replace('"', '"').replace('"', '"').replace("'", "'").replace("'", "'")
  raw = raw.strip('"').strip("'").strip()
  
  # Try various date formats
  formats = [
    "%Y-%m-%d",                    # 2025-12-02
    "%Y-%m-%dT%H:%M:%S",          # 2025-12-02T10:30:00
    "%Y-%m-%dT%H:%M:%S%z",        # 2025-12-02T10:30:00+00:00
    "%d/%m/%Y",                    # 02/12/2025
    "%m/%d/%Y",                    # 12/02/2025
    "%d-%m-%Y",                    # 02-12-2025
    "%d %B %Y",                    # 2 December 2025
    "%d %b %Y",                    # 2 Dec 2025
    "%B %d, %Y",                   # December 2, 2025
    "%b %d, %Y",                   # Dec 2, 2025
    "%d %B %Y %H:%M",              # 2 December 2025 10:30
    "%d %B %Y %I:%M %p",           # 2 December 2025 10:30 AM
    "%A %d %B %Y",                 # Monday 2 December 2025
    "%A %d %B %Y %H:%M",           # Monday 2 December 2025 10:30
    "%A %d %B %Y %I:%M %p",        # Monday 2 December 2025 10:30 AM
  ]
  
  for fmt in formats:
    try:
      dt = datetime.strptime(raw, fmt)
      # Make timezone-aware (UTC) for Django compatibility
      if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
      # Return ISO format string
      return dt.isoformat()
    except ValueError:
      continue
  
  # Try to extract date from common patterns if direct parsing fails
  # Pattern: "DD Month YYYY" or "DD Month YYYY HH:MM"
  date_patterns = [
    r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})(?:\s+(\d{1,2}):(\d{2})(?:\s*(AM|PM))?)?',
    r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})(?:\s+(\d{1,2}):(\d{2})(?:\s*(AM|PM))?)?',
  ]
  
  for pattern in date_patterns:
    match = re.search(pattern, raw, re.IGNORECASE)
    if match:
      try:
        if len(match.groups()) >= 3:
          # Try to parse the matched date
          date_str = match.group(0)
          # Extract just the date part (first 3 groups)
          date_parts = ' '.join(date_str.split()[:3])
          # Try common formats
          for fmt in ["%d %B %Y", "%B %d, %Y", "%d %b %Y", "%b %d, %Y"]:
            try:
              dt = datetime.strptime(date_parts, fmt)
              if len(match.groups()) >= 5 and match.group(4) and match.group(5):
                # Has time component
                hour = int(match.group(4))
                minute = int(match.group(5))
                if len(match.groups()) >= 6 and match.group(6) and match.group(6).upper() == 'PM' and hour < 12:
                  hour += 12
                dt = dt.replace(hour=hour, minute=minute)
              # Make timezone-aware (UTC) for Django compatibility
              if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
              return dt.isoformat()
            except (ValueError, IndexError):
              continue
      except (ValueError, IndexError, AttributeError):
        continue
  
  # If all parsing fails, return None (don't store invalid dates)
  return None

