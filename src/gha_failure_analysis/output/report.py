import json
import logging
import os
from pathlib import Path

from ..analysis.analyzer import RCAReport
from ..security.leak_detector import LeakDetector

logger = logging.getLogger(__name__)


def write_job_summary(report: RCAReport) -> None:
    """Write analysis report to GitHub Actions job summary.

    Args:
        report: RCA report object
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        logger.warning("GITHUB_STEP_SUMMARY not set, skipping job summary")
        return

    logger.info(f"Writing job summary to {summary_path}")

    # Sanitize before writing
    leak_detector = LeakDetector()
    sanitized_markdown = leak_detector.sanitize_text(report.to_markdown())

    try:
        with open(summary_path, "a") as f:
            f.write(sanitized_markdown)
        logger.info("Job summary written successfully")
    except Exception as e:
        logger.error(f"Failed to write job summary: {e}")


def write_json_report(report: RCAReport, output_path: str) -> None:
    """Write analysis report as JSON artifact.

    Args:
        report: RCA report object
        output_path: Path to write JSON file
    """
    logger.info(f"Writing JSON report to {output_path}")

    report_data = {
        "workflow_name": report.workflow_name,
        "run_id": report.run_id,
        "repository": report.repository,
        "pr_number": report.pr_number,
        "summary": report.summary,
        "detailed_analysis": report.detailed_analysis,
        "category": report.category,
        "pr_impact_assessment": report.pr_impact_assessment,
        "step_analyses": [
            {
                "job_name": sa.job_name,
                "step_name": sa.step_name,
                "failure_category": sa.failure_category,
                "root_cause": sa.root_cause,
                "evidence": sa.evidence,
            }
            for sa in report.step_analyses
        ],
        "test_analyses": [
            {
                "test_identifier": ta.test_identifier,
                "source_file": ta.source_file,
                "root_cause_summary": ta.root_cause_summary,
            }
            for ta in report.test_analyses
        ],
        "change_correlations": [c.to_dict() for c in report.change_correlations] if report.change_correlations else [],
    }

    # Sanitize JSON content
    leak_detector = LeakDetector()
    json_str = json.dumps(report_data, indent=2)
    sanitized_json = leak_detector.sanitize_text(json_str)

    try:
        Path(output_path).write_text(sanitized_json)
        logger.info("JSON report written successfully")
    except Exception as e:
        logger.error(f"Failed to write JSON report: {e}")


def set_action_output(name: str, value: str) -> None:
    """Set a GitHub Actions output variable.

    Args:
        name: Output variable name
        value: Output variable value
    """
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        logger.warning("GITHUB_OUTPUT not set, skipping output")
        return

    try:
        with open(output_file, "a") as f:
            # Sanitize value before setting
            leak_detector = LeakDetector()
            sanitized_value = leak_detector.sanitize_text(value)
            f.write(f"{name}={sanitized_value}\n")
        logger.debug(f"Set output: {name}")
    except Exception as e:
        logger.error(f"Failed to set output {name}: {e}")
