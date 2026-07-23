"""Login retry decorator for speaker control"""

import functools
import logging
from collections.abc import Callable
from typing import Any

from miairx.auth.errors import LoginError, TokenExpiredError

log = logging.getLogger(__name__)


def with_login_retry(func: Callable) -> Callable:
    """Decorator that handles login failures with automatic retry.
    
    This decorator catches LoginError and TokenExpiredError exceptions,
    invalidates the session, re-logins, and retries the operation once.
    """

    @functools.wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await func(self, *args, **kwargs)
        except (LoginError, TokenExpiredError) as e:
            log.warning(f"Login failure in {func.__name__}: {e}")
            log.info("Invalidating session and retrying...")
            
            # Invalidate session and re-login
            self.auth.invalidate_session()
            await self.auth.login()
            
            # Retry the operation
            return await func(self, *args, **kwargs)

    return wrapper
