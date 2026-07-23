"""Authentication module for MiAirX"""

from miairx.auth.cookie import mask_cookie_value, parse_cookie_string, validate_cookie_data
from miairx.auth.errors import AuthError, CaptchaRequiredError, LoginError, TokenExpiredError
from miairx.auth.manager import AuthManager

__all__ = [
    "AuthManager",
    "AuthError",
    "LoginError",
    "TokenExpiredError",
    "CaptchaRequiredError",
    "parse_cookie_string",
    "mask_cookie_value",
    "validate_cookie_data",
]
