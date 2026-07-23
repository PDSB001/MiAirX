"""Unit tests for retry decorator"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from miairx.core.retry import retry
from miairx.core.errors import LoginError, TokenExpiredError


@pytest.mark.asyncio
async def test_retry_success_on_first_attempt():
    """Test successful execution on first attempt."""
    mock_func = AsyncMock(return_value="success")
    mock_func.__name__ = "test_func"
    
    decorated = retry(max_attempts=3)(mock_func)
    result = await decorated()
    
    assert result == "success"
    assert mock_func.call_count == 1


@pytest.mark.asyncio
async def test_retry_success_on_second_attempt():
    """Test successful execution on second attempt."""
    mock_func = AsyncMock(side_effect=[LoginError("fail"), "success"])
    mock_func.__name__ = "test_func"
    
    decorated = retry(max_attempts=3, retry_on=(LoginError,))(mock_func)
    result = await decorated()
    
    assert result == "success"
    assert mock_func.call_count == 2


@pytest.mark.asyncio
async def test_retry_exhausted():
    """Test retry exhaustion."""
    mock_func = AsyncMock(side_effect=LoginError("fail"))
    mock_func.__name__ = "test_func"
    
    decorated = retry(max_attempts=3, retry_on=(LoginError,))(mock_func)
    
    with pytest.raises(LoginError):
        await decorated()
    
    assert mock_func.call_count == 3


@pytest.mark.asyncio
async def test_retry_with_on_retry_callback():
    """Test retry with on_retry callback."""
    mock_func = AsyncMock(side_effect=[LoginError("fail"), "success"])
    mock_func.__name__ = "test_func"
    
    on_retry = AsyncMock()
    decorated = retry(max_attempts=3, retry_on=(LoginError,), on_retry=on_retry)(mock_func)
    result = await decorated()
    
    assert result == "success"
    assert on_retry.call_count == 1


@pytest.mark.asyncio
async def test_retry_with_on_failure_callback():
    """Test retry with on_failure callback."""
    mock_func = AsyncMock(side_effect=LoginError("fail"))
    mock_func.__name__ = "test_func"
    
    on_failure = MagicMock()
    decorated = retry(max_attempts=2, retry_on=(LoginError,), on_failure=on_failure)(mock_func)
    
    with pytest.raises(LoginError):
        await decorated()
    
    assert on_failure.call_count == 1


@pytest.mark.asyncio
async def test_retry_different_exception_type():
    """Test that non-matching exceptions are not retried."""
    mock_func = AsyncMock(side_effect=ValueError("different error"))
    mock_func.__name__ = "test_func"
    
    decorated = retry(max_attempts=3, retry_on=(LoginError,))(mock_func)
    
    with pytest.raises(ValueError):
        await decorated()
    
    assert mock_func.call_count == 1
