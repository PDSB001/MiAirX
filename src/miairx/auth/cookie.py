"""Cookie parsing utilities for MiAirX"""

import logging
from typing import Optional

log = logging.getLogger(__name__)


def parse_cookie_string(cookie_str: str) -> dict[str, str]:
    """Parse cookie string and extract userId and passToken.
    
    Args:
        cookie_str: Cookie string in format "key1=value1; key2=value2"
        
    Returns:
        Dictionary with userId and passToken if found
    """
    result = {}
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key in ("userId", "passToken"):
                result[key] = value
    return result


def mask_cookie_value(value: str) -> str:
    """Mask sensitive cookie value for logging.
    
    Args:
        value: Cookie value to mask
        
    Returns:
        Masked value (first 4 chars + asterisks)
    """
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:4] + "****"


def validate_cookie_data(token_data: dict[str, str]) -> tuple[bool, Optional[str]]:
    """Validate cookie data has required fields.
    
    Args:
        token_data: Parsed cookie data
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not token_data.get("userId"):
        return False, "Missing userId in cookie"
    if not token_data.get("passToken"):
        return False, "Missing passToken in cookie"
    return True, None
