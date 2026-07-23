"""Authentication error types for MiAirX"""

from miairx.core.errors import AuthError, CaptchaRequiredError, LoginError, TokenExpiredError

__all__ = [
    "AuthError",
    "LoginError",
    "TokenExpiredError",
    "CaptchaRequiredError",
]
