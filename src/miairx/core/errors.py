"""Core exceptions for MiAirX"""


class MiAirError(Exception):
    """Base exception for all MiAirX errors"""
    pass


class AuthError(MiAirError):
    """Authentication-related errors"""
    pass


class LoginError(AuthError):
    """Login failed"""
    pass


class TokenExpiredError(AuthError):
    """Authentication token expired"""
    pass


class CaptchaRequiredError(AuthError):
    """Captcha verification required"""
    pass


class SpeakerError(MiAirError):
    """Speaker control errors"""
    pass


class MediaError(MiAirError):
    """Media processing errors"""
    pass


class ProtocolError(MiAirError):
    """Protocol implementation errors"""
    pass


class ConfigError(MiAirError):
    """Configuration errors"""
    pass
