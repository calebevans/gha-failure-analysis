import io
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import requests
from github import Auth, Github

from .models import JobResult, PRContext, StepResult, WorkflowRun
from .pr_context import fetch_pr_context

logger = logging.getLogger(__name__)


class GitHubClient:
    """Client for interacting with GitHub Actions API."""

    def __init__(self, token: str, config: Any = None) -> None:
        """Initialize GitHub client.

        Args:
            token: GitHub personal access token
            config: Optional Config instance for filtering settings
        """
        self.config = config
        auth = Auth.Token(token)
        self.github = Github(auth=auth)
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"token {token}"})

    def get_workflow_run(self, repository: str, run_id: int, manual_pr_number: int | None = None) -> WorkflowRun:
        """Get workflow run metadata.

        Args:
            repository: Repository in format "owner/repo"
            run_id: Workflow run ID
            manual_pr_number: Optional manual PR number override for testing

        Returns:
            WorkflowRun object
        """
        logger.info(f"Fetching workflow run {run_id} from {repository}")
        repo = self.github.get_repo(repository)
        run = repo.get_workflow_run(run_id)

        # Check if this is a PR-triggered run
        pr_number = None

        # Use manual override if provided
        if manual_pr_number:
            pr_number = manual_pr_number
            logger.info(f"Using manual PR number override: #{pr_number}")
        elif run.pull_requests and run.pull_requests.totalCount > 0:
            pr_number = run.pull_requests[0].number
            logger.info(f"Detected PR #{pr_number} from workflow run metadata")

        return WorkflowRun(
            id=run.id,
            name=run.name or "Unknown",
            head_branch=run.head_branch,
            head_sha=run.head_sha,
            status=run.status,
            conclusion=run.conclusion,
            html_url=run.html_url,
            repository=repository,
            pr_number=pr_number,
            created_at=run.created_at,
        )

    def get_failed_jobs(self, repository: str, run_id: int) -> list[JobResult]:
        """Get all failed jobs for a workflow run.

        Args:
            repository: Repository in format "owner/repo"
            run_id: Workflow run ID

        Returns:
            List of JobResult objects for failed jobs
        """
        logger.info(f"Fetching jobs for run {run_id}")
        repo = self.github.get_repo(repository)
        run = repo.get_workflow_run(run_id)

        failed_jobs = []
        for job in run.jobs():
            if job.conclusion != "success" and job.conclusion is not None:
                # Check if job should be ignored
                if self.config and self.config.should_ignore_job(job.name):
                    logger.info(f"Ignoring job (filtered): {job.name}")
                    continue

                # Extract steps
                steps = []
                for step_data in job.steps:
                    step = StepResult(
                        name=step_data.name,
                        number=step_data.number,
                        status=step_data.status,
                        conclusion=step_data.conclusion,
                        started_at=step_data.started_at,
                        completed_at=step_data.completed_at,
                    )
                    steps.append(step)

                job_result = JobResult(
                    id=job.id,
                    name=job.name,
                    status=job.status,
                    conclusion=job.conclusion,
                    steps=steps,
                    html_url=job.html_url,
                    started_at=job.started_at,
                    completed_at=job.completed_at,
                )

                logger.info(f"Found failed job: {job.name} ({len(job_result.failed_steps)} failed steps)")
                failed_jobs.append(job_result)

        return failed_jobs

    def download_job_logs(self, repository: str, job_id: int) -> str | None:
        """Download and extract logs for a job.

        Args:
            repository: Repository in format "owner/repo"
            job_id: Job ID

        Returns:
            Path to extracted log file or None if download fails
        """
        logger.info(f"Downloading logs for job {job_id}")

        try:
            # Get log download URL
            url = f"https://api.github.com/repos/{repository}/actions/jobs/{job_id}/logs"

            response = self.session.get(url, allow_redirects=True)
            response.raise_for_status()

            # Save to temp file
            tmp_file = tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False)
            tmp_file.write(response.content)
            tmp_file.close()

            log_size = Path(tmp_file.name).stat().st_size
            logger.info(f"Downloaded {log_size} bytes for job {job_id}")

            return tmp_file.name

        except Exception as e:
            logger.error(f"Failed to download logs for job {job_id}: {e}")
            return None

    def download_workflow_logs(self, repository: str, run_id: int) -> dict[int, str]:
        """Download logs for all jobs in a workflow run.

        Args:
            repository: Repository in format "owner/repo"
            run_id: Workflow run ID

        Returns:
            Dictionary mapping job ID to log file path
        """
        logger.info(f"Downloading all logs for run {run_id}")

        try:
            # Get log archive URL
            url = f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/logs"

            response = self.session.get(url, allow_redirects=True)
            response.raise_for_status()

            # Extract zip archive
            logs_by_job: dict[int, str] = {}

            with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
                for file_info in zip_file.filelist:
                    # Job logs are typically named like "1_job-name.txt"
                    if file_info.filename.endswith(".txt"):
                        # Extract to temp file
                        content = zip_file.read(file_info.filename)
                        tmp_file = tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False)
                        tmp_file.write(content)
                        tmp_file.close()

                        # Try to extract job number from filename
                        try:
                            job_num = int(file_info.filename.split("_")[0])
                            logs_by_job[job_num] = tmp_file.name
                            logger.debug(f"Extracted log: {file_info.filename} -> {tmp_file.name}")
                        except (ValueError, IndexError):
                            logger.warning(f"Could not parse job number from: {file_info.filename}")

            logger.info(f"Extracted logs for {len(logs_by_job)} jobs")
            return logs_by_job

        except Exception as e:
            logger.error(f"Failed to download workflow logs for run {run_id}: {e}")
            return {}

    def get_pr_context(
        self,
        repository: str,
        pr_number: int,
        max_tokens: int | None = None,
        commit_sha: str | None = None,
    ) -> PRContext:
        """Fetch PR context with changed files and diffs.

        Args:
            repository: Repository in format "owner/repo"
            pr_number: Pull request number
            max_tokens: Maximum tokens to allocate for diffs (None = unlimited)
            commit_sha: Optional specific commit SHA to analyze (e.g., from workflow run)

        Returns:
            PRContext object with PR metadata and changes

        Raises:
            Exception: If PR cannot be fetched or processed
        """
        logger.info(f"Fetching PR context for {repository}#{pr_number}")
        if commit_sha:
            logger.info(f"Analyzing specific commit: {commit_sha}")
        return fetch_pr_context(self.github, repository, pr_number, max_tokens, commit_sha)

    def close(self) -> None:
        """Close the GitHub client and cleanup resources."""
        self.github.close()
        self.session.close()
