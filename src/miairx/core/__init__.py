"""Core module for MiAirX"""

from miairx.core.errors import (
    AuthError,
    CaptchaRequiredError,
    ConfigError,
    LoginError,
    MediaError,
    MiAirError,
    ProtocolError,
    SpeakerError,
    TokenExpiredError,
)
from miairx.core.lifecycle import LifecycleManager, lifecycle
from miairx.core.logging import setup_logging
from miairx.core.retry import retry

__all__ = [
    "MiAirError",
    "AuthError",
    "LoginError",
    "TokenExpiredError",
    "CaptchaRequiredError",
    "SpeakerError",
    "MediaError",
    "ProtocolError",
    "ConfigError",
    "retry",
    "setup_logging",
    "LifecycleManager",
    "lifecycle",
]
