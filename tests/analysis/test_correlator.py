"""Tests for change correlator."""

from unittest.mock import Mock, patch

import pytest
from gha_failure_analysis.analysis.correlator import ChangeCorrelator, CorrelationResult, correlations_to_json
from gha_failure_analysis.github.models import FileChange, PRContext


@pytest.fixture  # type: ignore[misc]
def sample_pr_context() -> PRContext:
    """Create a sample PR context for testing."""
    return PRContext(
        pr_number=123,
        title="Fix authentication bug",
        description="This PR fixes a bug in the login flow",
        changed_files=[
            FileChange(
                filename="src/auth/login.py",
                status="modified",
                additions=10,
                deletions=5,
                changes=15,
                patch="@@ -45,5 +45,10 @@\n-old_auth()\n+new_auth()",
            ),
            FileChange(
                filename="tests/test_auth.py",
                status="modified",
                additions=20,
                deletions=2,
                changes=22,
                patch="@@ -100,2 +100,20 @@\n+new_test()",
            ),
        ],
        total_additions=30,
        total_deletions=7,
        base_sha="abc123",
        head_sha="def456",
    )


class TestCorrelationResult:
    """Tests for CorrelationResult dataclass."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        result = CorrelationResult(
            failure_type="test",
            failure_identifier="test_auth.py::test_login",
            likely_caused_by_pr=True,
            confidence="high",
            related_files=["src/auth/login.py"],
            reasoning="Test failure directly related to changed authentication logic",
        )

        result_dict = result.to_dict()

        assert result_dict["failure_type"] == "test"
        assert result_dict["failure_identifier"] == "test_auth.py::test_login"
        assert result_dict["likely_caused_by_pr"] is True
        assert result_dict["confidence"] == "high"
        assert result_dict["related_files"] == ["src/auth/login.py"]
        reasoning = result_dict["reasoning"]
        assert isinstance(reasoning, str)
        assert "authentication logic" in reasoning


class TestCorrelationsToJson:
    """Tests for correlation JSON conversion."""

    def test_converts_list_to_json(self) -> None:
        """Test converting list of correlations to JSON."""
        correlations = [
            CorrelationResult(
                failure_type="test",
                failure_identifier="test1",
                likely_caused_by_pr=True,
                confidence="high",
                related_files=["file1.py"],
                reasoning="Reason 1",
            ),
            CorrelationResult(
                failure_type="step",
                failure_identifier="step1",
                likely_caused_by_pr=False,
                confidence="unlikely",
                related_files=[],
                reasoning="Reason 2",
            ),
        ]

        json_str = correlations_to_json(correlations)

        assert "test1" in json_str
        assert "step1" in json_str
        assert "high" in json_str
        assert "unlikely" in json_str

    def test_handles_empty_list(self) -> None:
        """Test handling of empty correlation list."""
        json_str = correlations_to_json([])

        assert json_str == "[]"


class TestChangeCorrelator:
    """Tests for ChangeCorrelator."""

    @patch("gha_failure_analysis.analysis.correlator.dspy.ChainOfThought")
    def test_correlate_with_step_success(self, mock_cot: Mock, sample_pr_context: PRContext) -> None:
        """Test successful step correlation."""
        # Mock the LLM response
        mock_result = Mock()
        mock_result.likelihood = "high"
        mock_result.related_changes = "src/auth/login.py:45-52"
        mock_result.reasoning = "The step failure is directly caused by changes to authentication logic"

        mock_cot_instance = Mock()
        mock_cot_instance.return_value = mock_result
        mock_cot.return_value = mock_cot_instance

        correlator = ChangeCorrelator()
        correlator.correlate = mock_cot_instance

        result = correlator.correlate_with_step(
            step_name="build/run-tests",
            failure_details="Authentication test failed with invalid credentials error",
            pr_context=sample_pr_context,
        )

        assert result.failure_type == "step"
        assert result.failure_identifier == "build/run-tests"
        assert result.likely_caused_by_pr is True  # high likelihood
        assert result.confidence == "high"
        assert "src/auth/login.py:45-52" in result.related_files
        assert "authentication logic" in result.reasoning

    @patch("gha_failure_analysis.analysis.correlator.dspy.ChainOfThought")
    def test_correlate_with_test_success(self, mock_cot: Mock, sample_pr_context: PRContext) -> None:
        """Test successful test correlation."""
        # Mock the LLM response
        mock_result = Mock()
        mock_result.likelihood = "medium"
        mock_result.related_changes = "tests/test_auth.py:100"
        mock_result.reasoning = "Test may be affected by authentication changes"

        mock_cot_instance = Mock()
        mock_cot_instance.return_value = mock_result
        mock_cot.return_value = mock_cot_instance

        correlator = ChangeCorrelator()
        correlator.correlate = mock_cot_instance

        result = correlator.correlate_with_test(
            test_identifier="test_auth.py::TestAuth::test_login",
            failure_details="Login test failed - unexpected response",
            pr_context=sample_pr_context,
        )

        assert result.failure_type == "test"
        assert result.likely_caused_by_pr is True  # medium likelihood
        assert result.confidence == "medium"

    @patch("gha_failure_analysis.analysis.correlator.dspy.ChainOfThought")
    def test_correlate_with_step_unlikely(self, mock_cot: Mock, sample_pr_context: PRContext) -> None:
        """Test step correlation with unlikely result."""
        # Mock the LLM response
        mock_result = Mock()
        mock_result.likelihood = "unlikely"
        mock_result.related_changes = ""
        mock_result.reasoning = "Infrastructure failure unrelated to code changes"

        mock_cot_instance = Mock()
        mock_cot_instance.return_value = mock_result
        mock_cot.return_value = mock_cot_instance

        correlator = ChangeCorrelator()
        correlator.correlate = mock_cot_instance

        result = correlator.correlate_with_step(
            step_name="setup/install-dependencies",
            failure_details="Network timeout connecting to package registry",
            pr_context=sample_pr_context,
        )

        assert result.likely_caused_by_pr is False  # unlikely
        assert result.confidence == "unlikely"
        assert len(result.related_files) == 0 or result.related_files == []

    @patch("gha_failure_analysis.analysis.correlator.dspy.ChainOfThought")
    def test_handles_correlation_failure(self, mock_cot: Mock, sample_pr_context: PRContext) -> None:
        """Test handling of correlation errors."""
        # Mock the LLM to raise an exception
        mock_cot_instance = Mock()
        mock_cot_instance.side_effect = Exception("LLM API error")
        mock_cot.return_value = mock_cot_instance

        correlator = ChangeCorrelator()
        correlator.correlate = mock_cot_instance

        result = correlator.correlate_with_step(
            step_name="test-step",
            failure_details="Some failure",
            pr_context=sample_pr_context,
        )

        # Should return a result with unknown confidence
        assert result.failure_type == "step"
        assert result.confidence == "unknown"
        assert "failed" in result.reasoning.lower()

    @patch("gha_failure_analysis.analysis.correlator.dspy.ChainOfThought")
    def test_parses_multiline_related_changes(self, mock_cot: Mock, sample_pr_context: PRContext) -> None:
        """Test parsing of multiline related changes."""
        # Mock the LLM response with multiple file references
        mock_result = Mock()
        mock_result.likelihood = "high"
        mock_result.related_changes = "src/auth/login.py:45\nsrc/auth/validate.py:23\ntests/test_auth.py:100"
        mock_result.reasoning = "Multiple files affected"

        mock_cot_instance = Mock()
        mock_cot_instance.return_value = mock_result
        mock_cot.return_value = mock_cot_instance

        correlator = ChangeCorrelator()
        correlator.correlate = mock_cot_instance

        result = correlator.correlate_with_test(
            test_identifier="test_auth",
            failure_details="Auth test failed",
            pr_context=sample_pr_context,
        )

        # Should parse all three file references
        assert len(result.related_files) >= 3
        assert any("login.py" in f for f in result.related_files)
        assert any("validate.py" in f for f in result.related_files)
        assert any("test_auth.py" in f for f in result.related_files)
