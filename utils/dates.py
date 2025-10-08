from datetime import datetime, timezone
from typing import Optional, Union

def as_aware_utc(dt: Optional[Union[datetime, str, int, float]]) -> Optional[datetime]:
    """
    Normalize input to timezone-aware UTC datetime.
    
    This helper prevents "can't compare offset-naive and offset-aware datetimes" errors
    by ensuring all datetime values are timezone-aware UTC.
    
    Args:
        dt: Input datetime in various formats:
            - datetime object (naive or aware)
            - ISO string (e.g., "2025-10-08T12:00:00Z")
            - Unix timestamp (int or float)
            - None
    
    Returns:
        Timezone-aware UTC datetime, or None if input is None
        
    Raises:
        TypeError: If input type is not supported
        
    Examples:
        >>> as_aware_utc(datetime(2025, 10, 8, 12, 0))  # naive
        datetime(2025, 10, 8, 12, 0, tzinfo=timezone.utc)
        
        >>> as_aware_utc("2025-10-08T12:00:00Z")
        datetime(2025, 10, 8, 12, 0, tzinfo=timezone.utc)
        
        >>> as_aware_utc(1728388800)  # epoch
        datetime(2024, 10, 8, 12, 0, tzinfo=timezone.utc)
    """
    if dt is None:
        return None
    
    # Handle Unix timestamps
    if isinstance(dt, (int, float)):
        return datetime.fromtimestamp(dt, tz=timezone.utc)
    
    # Handle ISO strings
    if isinstance(dt, str):
        try:
            # API-Football returns ISO format, handle "Z" suffix
            d = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            # Fallback: strip microseconds and parse
            clean_str = dt.split(".")[0].replace("Z", "").strip()
            d = datetime.strptime(clean_str, "%Y-%m-%dT%H:%M:%S")
        
        # Ensure timezone awareness
        return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)
    
    # Handle datetime objects
    if isinstance(dt, datetime):
        # If already aware, convert to UTC; if naive, assume UTC
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    
    raise TypeError(f"Unsupported datetime type: {type(dt)}")


def now_utc() -> datetime:
    """Get current time as timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)
