"""Integration tests for PR context analysis feature."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from gha_failure_analysis.analysis.analyzer import FailureAnalyzer
from gha_failure_analysis.github.models import (
    FileChange,
    JobResult,
    PRContext,
    StepResult,
    WorkflowAnalysis,
    WorkflowRun,
)


@pytest.fixture  # type: ignore[misc]
def pr_with_code_changes() -> PRContext:
    """Create a PR context with code changes."""
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
                patch=(
                    "@@ -45,5 +45,10 @@\n"
                    "-def login(user):\n"
                    "-    return old_auth(user)\n"
                    "+def login(user):\n"
                    "+    return new_auth(user)"
                ),
            ),
            FileChange(
                filename="tests/test_auth.py",
                status="modified",
                additions=5,
                deletions=2,
                changes=7,
                patch="@@ -100,2 +100,5 @@\n-assert old_behavior()\n+assert new_behavior()",
            ),
        ],
        total_additions=15,
        total_deletions=7,
        base_sha="abc123",
        head_sha="def456",
    )


@pytest.fixture  # type: ignore[misc]
def workflow_with_auth_failure() -> WorkflowAnalysis:
    """Create a workflow analysis with authentication-related failure."""
    workflow_run = WorkflowRun(
        id=12345,
        name="CI",
        head_branch="fix-auth",
        head_sha="def456",
        status="completed",
        conclusion="failure",
        html_url="https://github.com/org/repo/actions/runs/12345",
        repository="org/repo",
        pr_number=123,
    )

    step = StepResult(
        name="Run authentication tests",
        number=5,
        status="completed",
        conclusion="failure",
    )

    job = JobResult(
        id=67890,
        name="test",
        status="completed",
        conclusion="failure",
        steps=[step],
        html_url="https://github.com/org/repo/actions/runs/12345/job/67890",
    )

    return WorkflowAnalysis(
        workflow_run=workflow_run,
        failed_jobs=[job],
        failed_tests=[],
        additional_artifacts={},
    )


@pytest.mark.integration
class TestPRContextIntegration:
    """Integration tests for PR context analysis."""

    @patch("gha_failure_analysis.analysis.analyzer.dspy.ChainOfThought")
    def test_analyzer_with_pr_context(
        self,
        mock_cot: Mock,
        pr_with_code_changes: PRContext,
        workflow_with_auth_failure: WorkflowAnalysis,
        tmp_path: Path,
    ) -> None:
        """Test that analyzer properly uses PR context."""
        # Mock log file
        log_file = tmp_path / "test.log"
        log_file.write_text("ERROR: Authentication failed at login.py:47\n")
        workflow_with_auth_failure.failed_jobs[0].log_path = str(log_file)

        # Mock LLM responses
        def mock_step_analysis(*args: object, **kwargs: object) -> Mock:
            result = Mock()
            result.failure_category = "test"
            result.root_cause = "Authentication test failed due to login logic change"
            result.evidence = "[]"
            result.pr_related = "yes"
            return result

        def mock_rca_generation(*args: object, **kwargs: object) -> Mock:
            result = Mock()
            result.summary = "Tests failed due to authentication changes"
            result.detailed_analysis = "### Immediate Cause\nAuthentication logic changed"
            result.category = "test"
            result.pr_impact_assessment = "Likelihood: high\n\nChanges to login.py directly caused test failures"
            return result

        mock_step_analyzer = Mock()
        mock_step_analyzer.side_effect = mock_step_analysis

        mock_rca_generator = Mock()
        mock_rca_generator.side_effect = mock_rca_generation

        mock_cot.side_effect = [mock_step_analyzer, None, None, mock_rca_generator]

        # Create analyzer with PR context
        analyzer = FailureAnalyzer(
            preprocessor=None,
            config=None,
            pr_context=pr_with_code_changes,
        )
        analyzer.step_analyzer = mock_step_analyzer
        analyzer.rca_generator = mock_rca_generator

        # Run analysis
        report = analyzer(workflow_with_auth_failure)

        # Verify PR context was used
        assert report.pr_context is not None
        assert report.pr_context.pr_number == 123
        assert report.pr_impact_assessment is not None
        assert "high" in report.pr_impact_assessment.lower()

    @patch("gha_failure_analysis.analysis.analyzer.dspy.ChainOfThought")
    def test_analyzer_without_pr_context(
        self,
        mock_cot: Mock,
        workflow_with_auth_failure: WorkflowAnalysis,
        tmp_path: Path,
    ) -> None:
        """Test that analyzer works without PR context (backward compatibility)."""
        # Mock log file
        log_file = tmp_path / "test.log"
        log_file.write_text("ERROR: Test failed\n")
        workflow_with_auth_failure.failed_jobs[0].log_path = str(log_file)

        # Mock LLM responses
        def mock_step_analysis(*args: object, **kwargs: object) -> Mock:
            result = Mock()
            result.failure_category = "test"
            result.root_cause = "Test failed"
            result.evidence = "[]"
            return result

        def mock_rca_generation(*args: object, **kwargs: object) -> Mock:
            result = Mock(spec=["summary", "detailed_analysis", "category"])
            result.summary = "Test failed"
            result.detailed_analysis = "### Immediate Cause\nTest failure"
            result.category = "test"
            return result

        mock_step_analyzer = Mock()
        mock_step_analyzer.side_effect = mock_step_analysis

        mock_rca_generator = Mock()
        mock_rca_generator.side_effect = mock_rca_generation

        mock_cot.side_effect = [mock_step_analyzer, None, None, mock_rca_generator]

        # Create analyzer WITHOUT PR context
        analyzer = FailureAnalyzer(
            preprocessor=None,
            config=None,
            pr_context=None,  # No PR context
        )
        analyzer.step_analyzer = mock_step_analyzer
        analyzer.rca_generator = mock_rca_generator

        # Run analysis
        report = analyzer(workflow_with_auth_failure)

        # Verify report still works without PR context
        assert report.pr_context is None
        assert report.pr_impact_assessment is None
        assert len(report.change_correlations) == 0

    def test_markdown_includes_pr_assessment(
        self,
        pr_with_code_changes: PRContext,
    ) -> None:
        """Test that markdown output includes PR assessment when available."""
        from gha_failure_analysis.analysis.analyzer import RCAReport

        report = RCAReport(
            workflow_name="CI",
            run_id="12345",
            pr_number="123",
            summary="Test failed",
            detailed_analysis="### Immediate Cause\nCode changes broke tests",
            category="test",
            step_analyses=[],
            pr_context=pr_with_code_changes,
            pr_impact_assessment=(
                "Likelihood: high\n\n"
                "The authentication changes in src/auth/login.py directly caused the test failures."
            ),
            change_correlations=[],
        )

        markdown = report.to_markdown()

        # Verify PR Impact Assessment section exists
        assert "## 🔍 PR Impact Assessment" in markdown
        assert "High" in markdown  # Formatted likelihood
        assert "src/auth/login.py" in markdown

    def test_markdown_without_pr_assessment(self) -> None:
        """Test that markdown works without PR assessment."""
        from gha_failure_analysis.analysis.analyzer import RCAReport

        report = RCAReport(
            workflow_name="CI",
            run_id="12345",
            pr_number=None,
            summary="Test failed",
            detailed_analysis="### Immediate Cause\nTest failure",
            category="test",
            step_analyses=[],
        )

        markdown = report.to_markdown()

        # Verify no PR section when not available
        assert "## 🔍 PR Impact Assessment" not in markdown
        assert "## 🎯 Root Cause" in markdown
