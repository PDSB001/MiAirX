"""Login retry decorator for speaker control"""

import asyncio
import functools
import logging
from collections.abc import Callable
from typing import Any

from miairx.auth.errors import LoginError, TokenExpiredError

log = logging.getLogger(__name__)


def _short_error(error: Exception, limit: int = 240) -> str:
    return str(error).replace("\n", " ")[:limit]


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
            log.warning(f"Login failure in {func.__name__}: {_short_error(e)}")
            log.info("Invalidating session and retrying...")
            
            # Invalidate session and re-login
            self.auth.invalidate_session()
            await self.auth.login()

            # Retry the operation
            return await func(self, *args, **kwargs)
        except Exception as e:
            # miservice-fork reports device/cloud timeouts as plain Exception
            # rather than MiAirX authentication exceptions. Retry these
            # transient speaker operations once without forcing a re-login.
            log.warning(
                f"Transient failure in {func.__name__}, retrying once: {_short_error(e)}"
            )
            await asyncio.sleep(0.5)
            return await func(self, *args, **kwargs)

    return wrapper
