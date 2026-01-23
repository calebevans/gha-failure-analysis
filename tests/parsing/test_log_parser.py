"""Tests for log parser."""
from gha_failure_analysis.parsing.log_parser import GitHubActionsLogParser


class TestGitHubActionsLogParser:
    """Tests for GitHub Actions log parser."""

    def test_parse_simple_log(self) -> None:
        """Test parsing a simple log with steps."""
        log_content = """2024-01-15T10:30:45.1234567Z ##[group]Run npm test
2024-01-15T10:30:45.2345678Z npm test
2024-01-15T10:30:46.1234567Z > test
2024-01-15T10:30:46.2345678Z > jest
2024-01-15T10:30:47.1234567Z PASS test/example.test.js
2024-01-15T10:30:47.2345678Z ##[endgroup]
2024-01-15T10:30:48.1234567Z ##[group]Run npm run lint
2024-01-15T10:30:48.2345678Z npm run lint
2024-01-15T10:30:49.1234567Z ##[error]Linting failed
2024-01-15T10:30:49.2345678Z ##[endgroup]
"""
        parser = GitHubActionsLogParser()
        steps = parser.parse_log_content(log_content)

        assert len(steps) == 2
        assert steps[0].step_name == "Run npm test"
        assert steps[1].step_name == "Run npm run lint"
        assert len(steps[1].annotations) == 1
        assert "ERROR: Linting failed" in steps[1].annotations[0]

    def test_format_step_logs(self) -> None:
        """Test formatting step logs."""
        log_content = """2024-01-15T10:30:45.1234567Z ##[group]Run tests
2024-01-15T10:30:45.2345678Z test output
2024-01-15T10:30:46.1234567Z ##[error]Test failed
2024-01-15T10:30:46.2345678Z ##[endgroup]
"""
        parser = GitHubActionsLogParser()
        steps = parser.parse_log_content(log_content)

        formatted = parser.format_step_logs(steps[0])
        assert "=== Annotations ===" in formatted
        assert "ERROR: Test failed" in formatted
        assert "test output" in formatted

    def test_get_step_names(self, tmp_path) -> None:  # type: ignore
        """Test getting step names from a log file."""
        log_file = tmp_path / "test.log"
        log_file.write_text(
            """2024-01-15T10:30:45.1234567Z ##[group]Step 1
2024-01-15T10:30:46.1234567Z ##[endgroup]
2024-01-15T10:30:47.1234567Z ##[group]Step 2
2024-01-15T10:30:48.1234567Z ##[endgroup]
"""
        )

        parser = GitHubActionsLogParser()
        step_names = parser.get_step_names(str(log_file))

        assert step_names == ["Step 1", "Step 2"]
