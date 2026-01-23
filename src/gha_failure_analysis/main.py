import logging
import sys
import tempfile
from pathlib import Path

import click
import dspy

from .analysis.analyzer import FailureAnalyzer, RCAReport
from .config import Config
from .github.client import GitHubClient
from .github.models import JobResult, WorkflowAnalysis
from .output.github import post_pr_comment
from .output.report import set_action_output, write_job_summary, write_json_report
from .processing.preprocessor import LogPreprocessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def configure_dspy(config: Config) -> None:
    """Configure DSPy with the specified LLM."""
    logger.info(f"Configuring DSPy with {config.llm_provider}/{config.llm_model}")

    model = f"{config.llm_provider}/{config.llm_model}"
    lm_kwargs = {"model": model}

    if config.llm_api_key:
        lm_kwargs["api_key"] = config.llm_api_key

    if config.llm_base_url:
        lm_kwargs["api_base"] = config.llm_base_url
    elif config.llm_provider == "ollama":
        lm_kwargs["api_base"] = "http://localhost:11434"

    dspy.configure(lm=dspy.LM(**lm_kwargs))


def _preprocess_logs(jobs: list[JobResult], preprocessor: LogPreprocessor, tokens_per_step: int) -> None:
    """Preprocess job logs in place."""
    logger.info("Preprocessing logs with cordon...")
    for job in jobs:
        if job.log_path:
            processed = preprocessor.preprocess_file(job.log_path, job.name, max_tokens=tokens_per_step)
            tmp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False)
            tmp_file.write(processed)
            tmp_file.close()
            Path(job.log_path).unlink(missing_ok=True)
            job.log_path = tmp_file.name


def _cleanup_temp_files(jobs: list[JobResult]) -> None:
    """Clean up temporary log files."""
    for job in jobs:
        if job.log_path:
            Path(job.log_path).unlink(missing_ok=True)


def _post_to_github(config: Config, report: RCAReport) -> None:
    """Post report to GitHub PR."""
    if not config.post_pr_comment:
        return

    workflow_run_pr = report.pr_number
    if not workflow_run_pr:
        logger.warning("Cannot post PR comment: workflow not triggered by PR")
        return

    logger.info("Posting comment to PR...")
    try:
        post_pr_comment(
            github_token=config.github_token,
            repository=config.repository,
            pr_number=int(workflow_run_pr),
            report=report,
        )
        logger.info("Comment posted successfully")
    except Exception as e:
        logger.error(f"Failed to post PR comment: {e}")


@click.group()  # type: ignore[misc]
@click.version_option()  # type: ignore[misc]
def cli() -> None:
    """AI-powered GitHub Actions workflow failure analysis."""
    pass


@cli.command()  # type: ignore[misc]
@click.option("--verbose", is_flag=True, help="Enable verbose logging")  # type: ignore[misc]
def analyze(verbose: bool) -> None:
    """Analyze a failed workflow run and generate RCA report."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = Config()
    errors = config.validate()
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        sys.exit(1)

    logger.info(f"Analyzing workflow run: {config.run_id} in {config.repository}")

    configure_dspy(config)

    context_limit = config.detect_model_context_limit()
    logger.info(f"Model: {config.llm_model}, Context: {context_limit:,} tokens")

    github_client = GitHubClient(config.github_token, config=config)

    try:
        # Get workflow run metadata
        manual_pr = int(config.pr_number) if config.pr_number else None
        workflow_run = github_client.get_workflow_run(config.repository, int(config.run_id), manual_pr_number=manual_pr)
        logger.info(f"Workflow: {workflow_run.name}, Status: {workflow_run.conclusion}")

        if workflow_run.conclusion == "success":
            logger.info("Workflow run succeeded - no failures to analyze")
            print("\n✅ Workflow completed successfully - no failures to analyze.")
            sys.exit(0)

        # Get failed jobs
        failed_jobs = github_client.get_failed_jobs(config.repository, int(config.run_id))
        if not failed_jobs:
            logger.info("No failed jobs found")
            print("\n✅ No failed jobs found - workflow may have been cancelled.")
            sys.exit(0)

        # Fetch PR context if this is a PR-triggered run and analysis is enabled
        pr_context = None
        if workflow_run.pr_number and config.analyze_pr_context:
            try:
                logger.info(f"Fetching PR context for PR #{workflow_run.pr_number}")
                # Calculate token budget for PR diffs
                pr_token_budget = int(context_limit * (config.pr_context_token_budget_pct / 100))

                # Use the workflow run's head SHA to analyze the exact commit that was tested
                pr_context = github_client.get_pr_context(
                    config.repository,
                    workflow_run.pr_number,
                    max_tokens=pr_token_budget,
                    commit_sha=workflow_run.head_sha,  # Analyze the exact commit that failed
                )
                logger.info(f"PR context fetched for commit {workflow_run.head_sha[:7]}: {pr_context.change_summary}")
            except Exception as e:
                logger.warning(f"Failed to fetch PR context: {e}. Continuing without PR analysis.")
                pr_context = None

        # Download logs for failed jobs
        logger.info(f"Downloading logs for {len(failed_jobs)} failed jobs")
        for job in failed_jobs:
            log_path = github_client.download_job_logs(config.repository, job.id)
            if log_path:
                job.log_path = log_path
                job.log_size = Path(log_path).stat().st_size

        # Calculate token budgets
        total_failed_steps = sum(len(job.failed_steps) for job in failed_jobs)
        num_failed_tests = 0  # TODO: Parse artifacts for JUnit XML
        num_artifacts = 0

        tokens_per_step, tokens_per_test, tokens_per_artifact_batch = config.calculate_token_budgets(
            total_failed_steps, num_failed_tests, num_artifacts
        )

        logger.info(f"Failures: {total_failed_steps} steps, {num_failed_tests} tests")
        logger.info(f"Token budgets - steps: {tokens_per_step:,}, tests: {tokens_per_test:,}")

        # Preprocess logs
        preprocessor = LogPreprocessor(config=config)
        _preprocess_logs(failed_jobs, preprocessor, tokens_per_step)

        # Create workflow analysis
        workflow_analysis = WorkflowAnalysis(
            workflow_run=workflow_run,
            failed_jobs=failed_jobs,
            failed_tests=[],
            additional_artifacts={},
        )

        # Analyze failures
        analyzer = FailureAnalyzer(
            preprocessor=preprocessor,
            config=config,
            tokens_per_step=tokens_per_step,
            tokens_per_test=tokens_per_test,
            tokens_per_artifact_batch=tokens_per_artifact_batch,
            pr_context=pr_context,
        )

        logger.info("Analyzing failures with LLM...")
        try:
            report = analyzer(workflow_analysis)
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            sys.exit(1)
        finally:
            _cleanup_temp_files(failed_jobs)

        # Output report
        print("\n" + "=" * 80)
        print(report.to_markdown())
        print("=" * 80 + "\n")

        # Write job summary
        if config.post_job_summary:
            write_job_summary(report)

        # Write JSON report
        json_path = "/tmp/failure-analysis-report.json"
        write_json_report(report, json_path)

        # Set action outputs
        set_action_output("summary", report.summary)
        set_action_output("category", report.category)
        set_action_output("report-path", json_path)

        # Post to PR if requested
        _post_to_github(config, report)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        github_client.close()


if __name__ == "__main__":
    cli()
