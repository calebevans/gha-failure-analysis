"""Tests for utility functions and decorators."""

import time
from unittest.mock import Mock

import pytest
from gha_failure_analysis.utils import retry_with_backoff


class TestRetryWithBackoff:
    """Test the retry_with_backoff decorator."""

    def test_success_on_first_try(self) -> None:
        """Test that successful calls don't retry."""
        mock_func = Mock(return_value="success")
        decorated = retry_with_backoff(max_retries=3)(mock_func)

        result = decorated()

        assert result == "success"
        assert mock_func.call_count == 1

    def test_retry_on_transient_error(self) -> None:
        """Test that transient errors trigger retry with exponential backoff."""
        mock_func = Mock(side_effect=[Exception("temporary error"), "success"])
        decorated = retry_with_backoff(max_retries=3, base_delay=0.1)(mock_func)

        start_time = time.time()
        result = decorated()
        elapsed = time.time() - start_time

        assert result == "success"
        assert mock_func.call_count == 2
        # First attempt fails, then delays 0.1s before retry
        assert elapsed >= 0.1

    def test_rate_limit_error_longer_delay(self) -> None:
        """Test that rate limit errors use longer delays."""
        mock_func = Mock(side_effect=[Exception("Rate limit exceeded"), "success"])
        decorated = retry_with_backoff(max_retries=3, base_delay=0.1, rate_limit_delay=0.3)(mock_func)

        start_time = time.time()
        result = decorated()
        elapsed = time.time() - start_time

        assert result == "success"
        assert mock_func.call_count == 2
        # Should use rate_limit_delay instead of base_delay
        assert elapsed >= 0.3

    def test_quota_error_detection(self) -> None:
        """Test that quota errors are detected as rate limits."""
        mock_func = Mock(side_effect=[Exception("Quota exceeded for resource"), "success"])
        decorated = retry_with_backoff(max_retries=3, base_delay=0.1, rate_limit_delay=0.3)(mock_func)

        start_time = time.time()
        result = decorated()
        elapsed = time.time() - start_time

        assert result == "success"
        assert elapsed >= 0.3

    def test_429_error_detection(self) -> None:
        """Test that 429 status codes are detected as rate limits."""
        mock_func = Mock(side_effect=[Exception("Error 429: Too Many Requests"), "success"])
        decorated = retry_with_backoff(max_retries=3, base_delay=0.1, rate_limit_delay=0.3)(mock_func)

        start_time = time.time()
        result = decorated()
        elapsed = time.time() - start_time

        assert result == "success"
        assert elapsed >= 0.3

    def test_max_retries_exceeded(self) -> None:
        """Test that errors are raised after max retries."""
        mock_func = Mock(side_effect=Exception("persistent error"))
        decorated = retry_with_backoff(max_retries=2, base_delay=0.1)(mock_func)

        with pytest.raises(Exception, match="persistent error"):
            decorated()

        assert mock_func.call_count == 2

    def test_context_window_error_no_retry(self) -> None:
        """Test that context window errors are not retried."""
        mock_func = Mock(side_effect=Exception("Input exceeds the maximum context window"))
        decorated = retry_with_backoff(max_retries=3, context_errors_no_retry=True)(mock_func)

        with pytest.raises(Exception, match="maximum context window"):
            decorated()

        # Should fail immediately without retry
        assert mock_func.call_count == 1

    def test_context_window_error_with_retry_disabled(self) -> None:
        """Test that context errors can be retried if flag is disabled."""
        mock_func = Mock(side_effect=[Exception("context window exceeded"), "success"])
        decorated = retry_with_backoff(max_retries=3, base_delay=0.1, context_errors_no_retry=False)(mock_func)

        result = decorated()

        assert result == "success"
        assert mock_func.call_count == 2

    def test_exponential_backoff(self) -> None:
        """Test exponential backoff for multiple retries."""
        mock_func = Mock(side_effect=[Exception("error 1"), Exception("error 2"), "success"])
        decorated = retry_with_backoff(max_retries=3, base_delay=0.1)(mock_func)

        start_time = time.time()
        result = decorated()
        elapsed = time.time() - start_time

        assert result == "success"
        assert mock_func.call_count == 3
        # First retry: 0.1s, second retry: 0.2s (total >= 0.3s)
        assert elapsed >= 0.3

    def test_rate_limit_exponential_backoff(self) -> None:
        """Test exponential backoff for rate limit errors."""
        mock_func = Mock(
            side_effect=[
                Exception("rate limit error 1"),
                Exception("rate limit error 2"),
                "success",
            ]
        )
        decorated = retry_with_backoff(max_retries=3, base_delay=0.05, rate_limit_delay=0.2)(mock_func)

        start_time = time.time()
        result = decorated()
        elapsed = time.time() - start_time

        assert result == "success"
        assert mock_func.call_count == 3
        # Check rate limit exponential backoff: 0.2s, 0.4s (total >= 0.6s)
        assert elapsed >= 0.6

    def test_mixed_errors(self) -> None:
        """Test handling of mixed error types."""
        mock_func = Mock(
            side_effect=[
                Exception("rate limit exceeded"),  # Rate limit: 0.3s delay
                Exception("temporary error"),  # Transient: 0.1s delay
                "success",
            ]
        )
        decorated = retry_with_backoff(max_retries=3, base_delay=0.1, rate_limit_delay=0.3)(mock_func)

        start_time = time.time()
        result = decorated()
        elapsed = time.time() - start_time

        assert result == "success"
        assert mock_func.call_count == 3
        # First attempt: rate limit (0.3s), second attempt: transient (0.2s = 0.1*2^1)
        # Total should be at least 0.5s
        assert elapsed >= 0.5
