"""Generic retry decorator for MiAirX"""

import functools
import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


def retry(
    max_attempts: int = 2,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable | None = None,
    on_failure: Callable | None = None,
) -> Callable:
    """Generic retry decorator with configurable exception handling.
    
    Args:
        max_attempts: Maximum number of retry attempts
        retry_on: Tuple of exception types to retry on
        on_retry: Optional callback called before retry (receives self, exception)
        on_failure: Optional callback called after all retries exhausted (receives self, exception)
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except retry_on as e:
                    last_exc = e
                    log.warning(
                        f"Attempt {attempt + 1}/{max_attempts} failed for {func.__name__}: {e}"
                    )
                    if on_retry and attempt < max_attempts - 1:
                        # Pass self (first arg) if available, otherwise just exception
                        if args:
                            await on_retry(args[0], e)
                        else:
                            await on_retry(e)
            if on_failure:
                # Pass self (first arg) if available, otherwise just exception
                if args:
                    on_failure(args[0], last_exc)
                else:
                    on_failure(last_exc)
            raise last_exc

        return wrapper

    return decorator
