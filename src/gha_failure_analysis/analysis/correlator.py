"""Module for correlating PR changes with failures."""

import json
import logging
from dataclasses import dataclass

import dspy

from ..github.models import PRContext
from ..github.pr_context import find_related_files, get_relevant_diffs, summarize_changes
from .signatures import CorrelateChangesWithFailure

logger = logging.getLogger(__name__)


@dataclass
class CorrelationResult:
    """Result of correlating PR changes with a failure."""

    failure_type: str  # "step" or "test"
    failure_identifier: str
    likely_caused_by_pr: bool
    confidence: str  # "high", "medium", "low", "unlikely"
    related_files: list[str]
    reasoning: str

    def to_dict(self) -> dict[str, str | bool | list[str]]:
        """Convert to dictionary for JSON serialization."""
        return {
            "failure_type": self.failure_type,
            "failure_identifier": self.failure_identifier,
            "likely_caused_by_pr": self.likely_caused_by_pr,
            "confidence": self.confidence,
            "related_files": self.related_files,
            "reasoning": self.reasoning,
        }


class ChangeCorrelator(dspy.Module):  # type: ignore[misc]
    """Correlates PR changes with failures using LLM analysis."""

    def __init__(self) -> None:
        """Initialize the correlator."""
        super().__init__()
        self.correlate = dspy.ChainOfThought(CorrelateChangesWithFailure)

    def correlate_with_step(
        self,
        step_name: str,
        failure_details: str,
        pr_context: PRContext,
    ) -> CorrelationResult:
        """Determine if PR changes likely caused a step failure.

        Args:
            step_name: Name of the failed step
            failure_details: Root cause and error details from step analysis
            pr_context: PR context with changed files

        Returns:
            CorrelationResult indicating relationship between PR and failure
        """
        logger.info(f"Correlating PR changes with step failure: {step_name}")

        # Find files that might be related to this step
        related_files = find_related_files(pr_context, step_name)

        # Get summary of all changes
        changes_summary = summarize_changes(pr_context)

        # Get diffs for related files
        relevant_diffs = get_relevant_diffs(pr_context, related_files) if related_files else "No related files found."

        try:
            # Run LLM correlation
            result = self.correlate(
                failure_type="step",
                failure_identifier=step_name,
                failure_details=failure_details,
                changed_files_summary=changes_summary,
                relevant_diffs=relevant_diffs,
            )

            # Parse likelihood
            likelihood = result.likelihood.lower()
            likely_caused_by_pr = likelihood in ("high", "medium")
            confidence = likelihood

            # Parse related changes - clean up any formatting issues
            related_changes_list = []
            if result.related_changes and result.related_changes.strip():
                # Split by newlines and clean each line
                for line in result.related_changes.split("\n"):
                    cleaned = line.strip()
                    # Remove markdown bullets, backticks, quotes, and extra dashes
                    cleaned = cleaned.lstrip("-*•").strip()
                    cleaned = cleaned.strip("`'\"")
                    cleaned = cleaned.replace("- `", "").replace("`", "")

                    # Only keep lines that look like file paths
                    if cleaned and ("/" in cleaned or ":" in cleaned) and len(cleaned) > 3:
                        related_changes_list.append(cleaned)

            logger.info(
                f"Step {step_name} correlation: {confidence} likelihood, "
                f"{len(related_changes_list)} related changes identified"
            )

            return CorrelationResult(
                failure_type="step",
                failure_identifier=step_name,
                likely_caused_by_pr=likely_caused_by_pr,
                confidence=confidence,
                related_files=related_changes_list if related_changes_list else related_files,
                reasoning=result.reasoning,
            )

        except Exception as e:
            logger.error(f"Correlation failed for step {step_name}: {e}")
            return CorrelationResult(
                failure_type="step",
                failure_identifier=step_name,
                likely_caused_by_pr=False,
                confidence="unknown",
                related_files=[],
                reasoning=f"Correlation analysis failed: {str(e)}",
            )

    def correlate_with_test(
        self,
        test_identifier: str,
        failure_details: str,
        pr_context: PRContext,
    ) -> CorrelationResult:
        """Determine if PR changes likely caused a test failure.

        Args:
            test_identifier: Full test identifier
            failure_details: Root cause summary from test analysis
            pr_context: PR context with changed files

        Returns:
            CorrelationResult indicating relationship between PR and failure
        """
        logger.info(f"Correlating PR changes with test failure: {test_identifier}")

        # Find files that might be related to this test
        related_files = find_related_files(pr_context, test_identifier)

        # Get summary of all changes
        changes_summary = summarize_changes(pr_context)

        # Get diffs for related files
        relevant_diffs = get_relevant_diffs(pr_context, related_files) if related_files else "No related files found."

        try:
            # Run LLM correlation
            result = self.correlate(
                failure_type="test",
                failure_identifier=test_identifier,
                failure_details=failure_details,
                changed_files_summary=changes_summary,
                relevant_diffs=relevant_diffs,
            )

            # Parse likelihood
            likelihood = result.likelihood.lower()
            likely_caused_by_pr = likelihood in ("high", "medium")
            confidence = likelihood

            # Parse related changes - clean up any formatting issues
            related_changes_list = []
            if result.related_changes and result.related_changes.strip():
                # Split by newlines and clean each line
                for line in result.related_changes.split("\n"):
                    cleaned = line.strip()
                    # Remove markdown bullets, backticks, quotes, and extra dashes
                    cleaned = cleaned.lstrip("-*•").strip()
                    cleaned = cleaned.strip("`'\"")
                    cleaned = cleaned.replace("- `", "").replace("`", "")

                    # Only keep lines that look like file paths
                    if cleaned and ("/" in cleaned or ":" in cleaned) and len(cleaned) > 3:
                        related_changes_list.append(cleaned)

            logger.info(
                f"Test {test_identifier} correlation: {confidence} likelihood, "
                f"{len(related_changes_list)} related changes identified"
            )

            return CorrelationResult(
                failure_type="test",
                failure_identifier=test_identifier,
                likely_caused_by_pr=likely_caused_by_pr,
                confidence=confidence,
                related_files=related_changes_list if related_changes_list else related_files,
                reasoning=result.reasoning,
            )

        except Exception as e:
            logger.error(f"Correlation failed for test {test_identifier}: {e}")
            return CorrelationResult(
                failure_type="test",
                failure_identifier=test_identifier,
                likely_caused_by_pr=False,
                confidence="unknown",
                related_files=[],
                reasoning=f"Correlation analysis failed: {str(e)}",
            )


def correlations_to_json(correlations: list[CorrelationResult]) -> str:
    """Convert correlation results to JSON string for LLM context.

    Args:
        correlations: List of correlation results

    Returns:
        JSON string representation
    """
    return json.dumps([c.to_dict() for c in correlations], indent=2)
