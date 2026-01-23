"""Module for fetching and processing PR context for failure analysis."""

import logging
from pathlib import Path

from github import Github
from github.PullRequest import PullRequest
from github.Repository import Repository

from .models import FileChange, PRContext

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (chars / 4)."""
    return len(text) // 4


def _is_binary_file(filename: str) -> bool:
    """Check if a file is likely binary based on extension."""
    binary_extensions = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".pyc",
        ".pyo",
        ".class",
        ".jar",
        ".war",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".mp3",
        ".mp4",
        ".avi",
        ".mov",
        ".webm",
    }
    return Path(filename).suffix.lower() in binary_extensions


def fetch_pr_context(
    github_client: Github,
    repository: str,
    pr_number: int,
    max_tokens: int | None = None,
    commit_sha: str | None = None,
) -> PRContext:
    """Fetch PR context with changed files and diffs.

    Args:
        github_client: Authenticated GitHub client
        repository: Repository in format "owner/repo"
        pr_number: Pull request number
        max_tokens: Maximum tokens to allocate for diffs (None = unlimited)
        commit_sha: Optional specific commit SHA to analyze (uses PR head if not provided)

    Returns:
        PRContext object with PR metadata and changes

    Raises:
        Exception: If PR cannot be fetched or processed
    """
    logger.info(f"Fetching PR context for {repository}#{pr_number}")
    if commit_sha:
        logger.info(f"Using specific commit SHA: {commit_sha}")

    try:
        repo = github_client.get_repo(repository)
        pr = repo.get_pull(pr_number)

        # Fetch PR metadata
        title = pr.title
        description = pr.body
        base_sha = pr.base.sha

        # Use the specified commit SHA if provided, otherwise use PR head
        head_sha = commit_sha if commit_sha else pr.head.sha

        # Fetch changed files - use comparison API if we have a specific commit
        if commit_sha:
            changed_files = _fetch_changed_files_for_commit(repo, base_sha, commit_sha, max_tokens)
        else:
            changed_files = _fetch_changed_files(pr, max_tokens)

        # Calculate totals
        total_additions = sum(f.additions for f in changed_files)
        total_deletions = sum(f.deletions for f in changed_files)

        logger.info(f"PR #{pr_number}: {len(changed_files)} files, " f"+{total_additions} -{total_deletions}")

        return PRContext(
            pr_number=pr_number,
            title=title,
            description=description,
            changed_files=changed_files,
            total_additions=total_additions,
            total_deletions=total_deletions,
            base_sha=base_sha,
            head_sha=head_sha,
        )

    except Exception as e:
        logger.error(f"Failed to fetch PR context for #{pr_number}: {e}")
        raise


def _fetch_changed_files_for_commit(
    repo: Repository, base_sha: str, head_sha: str, max_tokens: int | None
) -> list[FileChange]:
    """Fetch changed files for a specific commit comparison.

    Args:
        repo: GitHub Repository object
        base_sha: Base commit SHA
        head_sha: Head commit SHA
        max_tokens: Maximum tokens for diffs (None = unlimited)

    Returns:
        List of FileChange objects
    """
    changed_files = []
    total_tokens_used = 0

    try:
        # Use comparison API to get files changed between base and head
        comparison = repo.compare(base_sha, head_sha)
        files = comparison.files

        for file in files:
            filename = file.filename
            status = file.status
            additions = file.additions
            deletions = file.deletions
            changes = file.changes
            previous_filename = file.previous_filename if hasattr(file, "previous_filename") else None

            # Check if we should include the patch/diff
            patch = None
            if file.patch and not _is_binary_file(filename):
                patch_tokens = _estimate_tokens(file.patch)

                # Include patch if within budget
                if max_tokens is None or (total_tokens_used + patch_tokens) <= max_tokens:
                    patch = file.patch
                    total_tokens_used += patch_tokens
                    logger.debug(
                        f"Included diff for {filename} ({patch_tokens} tokens, "
                        f"{total_tokens_used}/{max_tokens or 'unlimited'} total)"
                    )
                else:
                    logger.debug(
                        f"Skipped diff for {filename} (would exceed budget: "
                        f"{total_tokens_used + patch_tokens} > {max_tokens})"
                    )
            elif _is_binary_file(filename):
                logger.debug(f"Skipped binary file: {filename}")

            changed_files.append(
                FileChange(
                    filename=filename,
                    status=status,
                    additions=additions,
                    deletions=deletions,
                    changes=changes,
                    patch=patch,
                    previous_filename=previous_filename,
                )
            )

        logger.info(
            f"Fetched {len(changed_files)} changed files for {head_sha[:7]} "
            f"({total_tokens_used} tokens used for diffs)"
        )

    except Exception as e:
        logger.error(f"Error fetching changed files for commit: {e}")
        raise

    return changed_files


def _fetch_changed_files(pr: PullRequest, max_tokens: int | None) -> list[FileChange]:
    """Fetch all changed files with diffs, respecting token budget.

    Args:
        pr: GitHub PullRequest object
        max_tokens: Maximum tokens for diffs (None = unlimited)

    Returns:
        List of FileChange objects
    """
    changed_files = []
    total_tokens_used = 0

    try:
        files = pr.get_files()

        for file in files:
            filename = file.filename
            status = file.status
            additions = file.additions
            deletions = file.deletions
            changes = file.changes
            previous_filename = file.previous_filename if hasattr(file, "previous_filename") else None

            # Check if we should include the patch/diff
            patch = None
            if file.patch and not _is_binary_file(filename):
                patch_tokens = _estimate_tokens(file.patch)

                # Include patch if within budget
                if max_tokens is None or (total_tokens_used + patch_tokens) <= max_tokens:
                    patch = file.patch
                    total_tokens_used += patch_tokens
                    logger.debug(
                        f"Included diff for {filename} ({patch_tokens} tokens, "
                        f"{total_tokens_used}/{max_tokens or 'unlimited'} total)"
                    )
                else:
                    logger.debug(
                        f"Skipped diff for {filename} (would exceed budget: "
                        f"{total_tokens_used + patch_tokens} > {max_tokens})"
                    )
            elif _is_binary_file(filename):
                logger.debug(f"Skipped binary file: {filename}")

            changed_files.append(
                FileChange(
                    filename=filename,
                    status=status,
                    additions=additions,
                    deletions=deletions,
                    changes=changes,
                    patch=patch,
                    previous_filename=previous_filename,
                )
            )

        logger.info(f"Fetched {len(changed_files)} changed files " f"({total_tokens_used} tokens used for diffs)")

    except Exception as e:
        logger.error(f"Error fetching changed files: {e}")
        raise

    return changed_files


def summarize_changes(pr_context: PRContext, max_files: int = 20) -> str:
    """Create a concise summary of PR changes for LLM context.

    Args:
        pr_context: PR context with changed files
        max_files: Maximum number of files to list individually

    Returns:
        Formatted string summarizing the changes
    """
    lines = [
        f"PR #{pr_context.pr_number}: {pr_context.title}",
        f"Changed: {pr_context.change_summary}",
        "",
    ]

    if pr_context.description:
        # Truncate description to first few lines
        desc_lines = pr_context.description.split("\n")[:3]
        lines.append("Description:")
        lines.extend(f"  {line}" for line in desc_lines)
        if len(pr_context.description.split("\n")) > 3:
            lines.append("  ...")
        lines.append("")

    # Group files by type
    files_by_type: dict[str, list[FileChange]] = {
        "added": [],
        "modified": [],
        "removed": [],
        "renamed": [],
    }

    for file in pr_context.changed_files:
        files_by_type[file.status].append(file)

    # List changed files
    lines.append("Changed Files:")
    total_listed = 0

    for status, files in files_by_type.items():
        if not files:
            continue

        lines.append(f"  {status.title()} ({len(files)}):")
        for file in files[: max_files - total_listed]:
            change_str = f"+{file.additions} -{file.deletions}"
            lines.append(f"    - {file.filename} ({change_str})")
            total_listed += 1

            if total_listed >= max_files:
                remaining = sum(len(f) for f in files_by_type.values()) - total_listed
                if remaining > 0:
                    lines.append(f"    ... and {remaining} more files")
                break

        if total_listed >= max_files:
            break

    return "\n".join(lines)


def get_relevant_diffs(pr_context: PRContext, related_files: list[str]) -> str:
    """Extract diffs for specific files related to a failure.

    Args:
        pr_context: PR context with changed files
        related_files: List of filenames to extract diffs for

    Returns:
        Formatted string with relevant diffs
    """
    lines = []

    for file in pr_context.changed_files:
        # Check if this file matches any of the related files
        if any(related in file.filename or file.filename in related for related in related_files):
            if file.patch:
                lines.append(f"### {file.filename} ({file.status})")
                lines.append(f"+{file.additions} -{file.deletions}")
                lines.append("```diff")
                lines.append(file.patch)
                lines.append("```")
                lines.append("")
            else:
                lines.append(f"### {file.filename} ({file.status})")
                lines.append(f"+{file.additions} -{file.deletions} (diff not available)")
                lines.append("")

    if not lines:
        return "No relevant diffs found for the specified files."

    return "\n".join(lines)


def find_related_files(pr_context: PRContext, failure_identifier: str) -> list[str]:
    """Find files in PR that might be related to a failure.

    Uses simple heuristics to match changed files with failure identifiers.

    Args:
        pr_context: PR context with changed files
        failure_identifier: Test name, step name, or file path from failure

    Returns:
        List of filenames likely related to the failure
    """
    related = []
    identifier_lower = failure_identifier.lower()

    # Extract potential file/module references from identifier
    # E.g., "test_auth.py::TestAuth::test_login" -> ["auth", "test_auth"]
    parts = identifier_lower.replace("::", "/").replace(".", "/").split("/")
    keywords = [p for p in parts if p and len(p) > 2]

    for file in pr_context.changed_files:
        filename_lower = file.filename.lower()

        # Check if any keyword appears in the filename
        for keyword in keywords:
            if keyword in filename_lower:
                related.append(file.filename)
                break

        # Also check if filename (without extension) appears in identifier
        filename_base = Path(file.filename).stem.lower()
        if filename_base in identifier_lower and len(filename_base) > 3:
            if file.filename not in related:
                related.append(file.filename)

    logger.debug(f"Found {len(related)} related files for '{failure_identifier}': {related}")
    return related
