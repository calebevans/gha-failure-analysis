"""Tests for PR context fetching and processing."""


from gha_failure_analysis.github.models import FileChange, PRContext
from gha_failure_analysis.github.pr_context import (
    _is_binary_file,
    find_related_files,
    get_relevant_diffs,
    summarize_changes,
)


class TestIsBinaryFile:
    """Tests for binary file detection."""

    def test_identifies_binary_extensions(self) -> None:
        """Test that common binary extensions are identified."""
        assert _is_binary_file("image.png") is True
        assert _is_binary_file("document.pdf") is True
        assert _is_binary_file("archive.zip") is True
        assert _is_binary_file("font.woff") is True

    def test_identifies_text_files(self) -> None:
        """Test that text files are not identified as binary."""
        assert _is_binary_file("script.py") is False
        assert _is_binary_file("config.json") is False
        assert _is_binary_file("readme.md") is False
        assert _is_binary_file("test.txt") is False


class TestSummarizeChanges:
    """Tests for PR change summarization."""

    def test_summarizes_basic_pr(self) -> None:
        """Test basic PR summary."""
        pr_context = PRContext(
            pr_number=123,
            title="Fix auth bug",
            description="Fixes authentication issue",
            changed_files=[
                FileChange(
                    filename="src/auth.py",
                    status="modified",
                    additions=10,
                    deletions=5,
                    changes=15,
                    patch="@@ -1,5 +1,10 @@\n...",
                ),
            ],
            total_additions=10,
            total_deletions=5,
            base_sha="abc123",
            head_sha="def456",
        )

        summary = summarize_changes(pr_context)

        assert "PR #123" in summary
        assert "Fix auth bug" in summary
        assert "1 files changed, +10 -5" in summary
        assert "src/auth.py" in summary

    def test_truncates_long_description(self) -> None:
        """Test that long descriptions are truncated."""
        long_desc = "\n".join([f"Line {i}" for i in range(10)])
        pr_context = PRContext(
            pr_number=123,
            title="Test",
            description=long_desc,
            changed_files=[],
            total_additions=0,
            total_deletions=0,
            base_sha="abc",
            head_sha="def",
        )

        summary = summarize_changes(pr_context)

        # Should have first 3 lines plus "..."
        assert "Line 0" in summary
        assert "Line 1" in summary
        assert "Line 2" in summary
        assert "..." in summary

    def test_limits_file_listing(self) -> None:
        """Test that file listing is limited."""
        files = [
            FileChange(
                filename=f"file{i}.py",
                status="modified",
                additions=1,
                deletions=1,
                changes=2,
            )
            for i in range(30)
        ]

        pr_context = PRContext(
            pr_number=123,
            title="Test",
            description=None,
            changed_files=files,
            total_additions=30,
            total_deletions=30,
            base_sha="abc",
            head_sha="def",
        )

        summary = summarize_changes(pr_context, max_files=10)

        # Should have at most 10 files listed plus "and X more"
        assert "and 20 more files" in summary


class TestGetRelevantDiffs:
    """Tests for extracting relevant diffs."""

    def test_extracts_matching_files(self) -> None:
        """Test that diffs for matching files are extracted."""
        pr_context = PRContext(
            pr_number=123,
            title="Test",
            description=None,
            changed_files=[
                FileChange(
                    filename="src/auth.py",
                    status="modified",
                    additions=5,
                    deletions=2,
                    changes=7,
                    patch="@@ -1,2 +1,5 @@\n-old\n+new",
                ),
                FileChange(
                    filename="src/other.py",
                    status="modified",
                    additions=1,
                    deletions=1,
                    changes=2,
                    patch="@@ -10,1 +10,1 @@\n-old\n+new",
                ),
            ],
            total_additions=6,
            total_deletions=3,
            base_sha="abc",
            head_sha="def",
        )

        diffs = get_relevant_diffs(pr_context, ["src/auth.py"])

        assert "src/auth.py" in diffs
        assert "@@ -1,2 +1,5 @@" in diffs
        assert "src/other.py" not in diffs

    def test_handles_missing_patches(self) -> None:
        """Test handling of files without patches."""
        pr_context = PRContext(
            pr_number=123,
            title="Test",
            description=None,
            changed_files=[
                FileChange(
                    filename="large_file.bin",
                    status="modified",
                    additions=100,
                    deletions=50,
                    changes=150,
                    patch=None,  # No patch available
                ),
            ],
            total_additions=100,
            total_deletions=50,
            base_sha="abc",
            head_sha="def",
        )

        diffs = get_relevant_diffs(pr_context, ["large_file.bin"])

        assert "large_file.bin" in diffs
        assert "diff not available" in diffs

    def test_returns_message_when_no_matches(self) -> None:
        """Test message when no related files found."""
        pr_context = PRContext(
            pr_number=123,
            title="Test",
            description=None,
            changed_files=[
                FileChange(
                    filename="src/auth.py",
                    status="modified",
                    additions=1,
                    deletions=1,
                    changes=2,
                    patch="diff",
                ),
            ],
            total_additions=1,
            total_deletions=1,
            base_sha="abc",
            head_sha="def",
        )

        diffs = get_relevant_diffs(pr_context, ["nonexistent.py"])

        assert "No relevant diffs found" in diffs


class TestFindRelatedFiles:
    """Tests for finding related files."""

    def test_finds_exact_match(self) -> None:
        """Test finding files with exact name match."""
        pr_context = PRContext(
            pr_number=123,
            title="Test",
            description=None,
            changed_files=[
                FileChange(filename="test_auth.py", status="modified", additions=1, deletions=1, changes=2),
                FileChange(filename="src/other.py", status="modified", additions=1, deletions=1, changes=2),
            ],
            total_additions=2,
            total_deletions=2,
            base_sha="abc",
            head_sha="def",
        )

        related = find_related_files(pr_context, "test_auth.py")

        assert "test_auth.py" in related
        assert "src/other.py" not in related

    def test_finds_keyword_match(self) -> None:
        """Test finding files with keyword matches."""
        pr_context = PRContext(
            pr_number=123,
            title="Test",
            description=None,
            changed_files=[
                FileChange(filename="src/auth/login.py", status="modified", additions=1, deletions=1, changes=2),
                FileChange(filename="tests/test_auth.py", status="modified", additions=1, deletions=1, changes=2),
                FileChange(filename="src/database.py", status="modified", additions=1, deletions=1, changes=2),
            ],
            total_additions=3,
            total_deletions=3,
            base_sha="abc",
            head_sha="def",
        )

        # Test identifier contains "auth" keyword
        related = find_related_files(pr_context, "test_auth::TestAuth::test_login")

        # Should find files with "auth" in the path
        assert "src/auth/login.py" in related or "tests/test_auth.py" in related
        assert "src/database.py" not in related

    def test_returns_empty_for_no_matches(self) -> None:
        """Test that empty list is returned when no matches found."""
        pr_context = PRContext(
            pr_number=123,
            title="Test",
            description=None,
            changed_files=[
                FileChange(filename="src/auth.py", status="modified", additions=1, deletions=1, changes=2),
            ],
            total_additions=1,
            total_deletions=1,
            base_sha="abc",
            head_sha="def",
        )

        related = find_related_files(pr_context, "completely_unrelated_test")

        assert len(related) == 0
