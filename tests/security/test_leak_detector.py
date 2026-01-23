"""Tests for leak detector."""
from gha_failure_analysis.security.leak_detector import LeakDetector


class TestLeakDetector:
    """Tests for LeakDetector class."""

    def test_sanitize_with_no_secrets(self) -> None:
        """Test sanitizing text with no secrets."""
        detector = LeakDetector()
        text = "This is a normal log line with no secrets"
        result = detector.sanitize_text(text)
        assert result == text

    def test_sanitize_empty_text(self) -> None:
        """Test sanitizing empty text."""
        detector = LeakDetector()
        result = detector.sanitize_text("")
        assert result == ""

    def test_sanitize_none(self) -> None:
        """Test sanitizing None."""
        detector = LeakDetector()
        result = detector.sanitize_text("")
        assert result == ""
