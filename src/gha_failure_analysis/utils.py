"""Utility functions and decorators for the failure analysis tool."""

import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

# Type variable for generic function return type
T = TypeVar("T")


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 2.0,
    rate_limit_delay: float = 6.0,
    context_errors_no_retry: bool = True,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to retry a function with exponential backoff on rate limit or transient errors.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Base delay in seconds for non-rate-limit errors (default: 2.0)
        rate_limit_delay: Base delay in seconds for rate limit errors (default: 6.0)
        context_errors_no_retry: If True, don't retry context window errors (default: True)

    Returns:
        Decorated function with retry logic

    Example:
        @retry_with_backoff(max_retries=3, rate_limit_delay=6.0)
        def call_api(data):
            return api.generate(data)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_error: Exception | None = None
            func_name = getattr(func, "__name__", "unknown_function")

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    last_error = e
                    error_msg = str(e)

                    # Check error types
                    is_rate_limit = (
                        "rate limit" in error_msg.lower()
                        or "quota" in error_msg.lower()
                        or "429" in error_msg
                        or "resource_exhausted" in error_msg.lower()
                    )

                    is_context_error = context_errors_no_retry and (
                        ("context" in error_msg.lower() and "window" in error_msg.lower())
                        or "exceeds the maximum" in error_msg.lower()
                    )

                    # Don't retry context errors - they won't succeed
                    if is_context_error:
                        logger.error(f"{func_name}: Context window exceeded, no retry. Error: {e}")
                        raise

                    # If this is the last attempt, raise the error
                    if attempt >= max_retries - 1:
                        logger.error(f"{func_name}: Failed after {max_retries} attempts. Error: {e}")
                        raise

                    # Calculate delay with exponential backoff
                    if is_rate_limit:
                        delay = rate_limit_delay * (2**attempt)
                        error_type = "rate limit"
                    else:
                        delay = base_delay * (2**attempt)
                        error_type = "transient"

                    logger.warning(
                        f"{func_name}: {error_type} error (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {delay:.1f}s... Error: {e}"
                    )
                    time.sleep(delay)

            # Should never reach here due to raise in loop, but satisfy type checker
            if last_error:
                raise last_error
            raise RuntimeError(f"{func_name}: Unexpected retry loop exit")

        return wrapper

    return decorator
