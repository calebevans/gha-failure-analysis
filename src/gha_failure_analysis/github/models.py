from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..parsing.xunit_models import FailedTest


@dataclass
class WorkflowRun:
    """Represents a GitHub Actions workflow run."""

    id: int
    name: str
    head_branch: str
    head_sha: str
    status: str
    conclusion: str | None
    html_url: str
    repository: str
    pr_number: int | None = None
    created_at: datetime | None = None


@dataclass
class StepResult:
    """Represents a single step execution result."""

    name: str
    number: int
    status: str
    conclusion: str | None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def passed(self) -> bool:
        """Check if step passed."""
        return self.conclusion == "success"


@dataclass
class JobResult:
    """Represents a job within a workflow run."""

    id: int
    name: str
    status: str
    conclusion: str | None
    steps: list[StepResult] = field(default_factory=list)
    log_path: str | None = None
    log_size: int = 0
    html_url: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def passed(self) -> bool:
        """Check if job passed."""
        return self.conclusion == "success"

    @property
    def failed_steps(self) -> list[StepResult]:
        """Get list of failed steps."""
        return [step for step in self.steps if not step.passed and step.conclusion is not None]


@dataclass
class WorkflowAnalysis:
    """Complete workflow analysis result."""

    workflow_run: WorkflowRun
    failed_jobs: list[JobResult]
    failed_tests: list["FailedTest"] = field(default_factory=list)
    additional_artifacts: dict[str, str] = field(default_factory=dict)

    @property
    def total_failed_steps(self) -> int:
        """Get total number of failed steps across all jobs."""
        return sum(len(job.failed_steps) for job in self.failed_jobs)


@dataclass
class FileChange:
    """Represents a single file change in a PR."""

    filename: str
    status: str  # added, modified, removed, renamed
    additions: int
    deletions: int
    changes: int
    patch: str | None = None  # Actual diff content
    previous_filename: str | None = None  # For renamed files


@dataclass
class PRContext:
    """Complete PR context for analysis."""

    pr_number: int
    title: str
    description: str | None
    changed_files: list[FileChange]
    total_additions: int
    total_deletions: int
    base_sha: str
    head_sha: str

    @property
    def total_files_changed(self) -> int:
        """Get total number of files changed."""
        return len(self.changed_files)

    @property
    def change_summary(self) -> str:
        """Get a brief summary of changes."""
        return f"{self.total_files_changed} files changed, +{self.total_additions} -{self.total_deletions}"
