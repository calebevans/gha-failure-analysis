import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import dspy

from ..github.models import FileChange, JobResult, PRContext, StepResult, WorkflowAnalysis
from ..github.pr_context import find_related_files, get_relevant_diffs, summarize_changes
from ..parsing.xunit_models import FailedTest
from ..security.leak_detector import LeakDetector
from ..utils import retry_with_backoff
from .correlator import ChangeCorrelator, CorrelationResult, correlations_to_json
from .signatures import (
    AnalyzeArtifacts,
    AnalyzeStepFailure,
    AnalyzeTestFailure,
    ExtractRelevantDiffSection,
    GenerateRCA,
)

logger = logging.getLogger(__name__)


def _sanitize_json_string(text: str) -> str:
    """Sanitize JSON string by escaping unescaped control characters."""
    import re

    def escape_control_chars(match: re.Match[str]) -> str:
        content = match.group(1)
        content = content.replace("\n", "\\n")
        content = content.replace("\r", "\\r")
        content = content.replace("\t", "\\t")
        content = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", content)
        return f'"{content}"'

    return re.sub(r'"((?:[^"\\]|\\.)*)(?<!\\)"', escape_control_chars, text)


@dataclass
class StepAnalysis:
    """Analysis result for a single step."""

    job_name: str
    step_name: str
    failure_category: str
    root_cause: str
    evidence: list[dict[str, str]]


@dataclass
class TestFailureAnalysis:
    """Analysis result for a single test failure."""

    test_identifier: str
    source_file: str
    root_cause_summary: str


@dataclass
class ArtifactAnalysis:
    """Analysis result for a diagnostic artifact."""

    artifact_path: str
    key_findings: str


@dataclass
class RCAReport:
    """Complete root cause analysis report."""

    workflow_name: str
    run_id: str
    pr_number: str | None
    summary: str
    detailed_analysis: str
    category: str
    step_analyses: list[StepAnalysis]
    test_analyses: list[TestFailureAnalysis] = field(default_factory=list)
    artifact_analyses: list[ArtifactAnalysis] = field(default_factory=list)
    pr_context: PRContext | None = None
    pr_impact_assessment: str | None = None
    change_correlations: list[CorrelationResult] = field(default_factory=list)
    repository: str = ""  # Repository in format "owner/repo"
    code_snippets: list[tuple[str, str, str]] = field(default_factory=list)  # (filename, change_type, snippet)

    def _get_run_url(self) -> str:
        """Generate URL for the workflow run."""
        if self.repository:
            return f"[#{self.run_id}](https://github.com/{self.repository}/actions/runs/{self.run_id})"
        return f"`{self.run_id}`"

    def _get_pr_url(self) -> str:
        """Generate URL for the pull request."""
        if not self.pr_number:
            return ""
        if self.repository:
            return f"[#{self.pr_number}](https://github.com/{self.repository}/pull/{self.pr_number})"
        return f"#{self.pr_number}"

    def _group_similar_failures(self) -> dict[str, list[StepAnalysis]]:
        """Group similar failures together to reduce noise."""
        groups: dict[str, list[StepAnalysis]] = {}

        for analysis in self.step_analyses:
            # Create a key based on the step name (ignoring job variations)
            # E.g., "Test (Python 3.13)/Run tests" -> "Run tests"
            step_key = analysis.step_name

            if step_key not in groups:
                groups[step_key] = []
            groups[step_key].append(analysis)

        return groups

    def _select_useful_evidence(self, evidence: list[dict[str, str]], root_cause: str) -> list[dict[str, str]]:
        """Use LLM to select the most useful, non-redundant evidence items.

        Args:
            evidence: List of evidence items with 'source' and 'content'
            root_cause: The identified root cause

        Returns:
            Filtered list of diverse, useful evidence items
        """
        if not evidence:
            return []

        # If 2 or fewer items, just return them all
        if len(evidence) <= 2:
            return evidence

        try:
            import json

            from .signatures import SelectUsefulEvidence

            # Prepare evidence as JSON
            evidence_json = json.dumps(evidence, indent=2)

            # Use LLM to select most useful evidence
            selector = dspy.Predict(SelectUsefulEvidence)
            result = selector(root_cause=root_cause, all_evidence=evidence_json)

            # Parse selected indices
            if result.selected_indices and result.selected_indices.strip():
                indices_str = result.selected_indices.strip()
                indices = [int(idx.strip()) for idx in indices_str.split(",") if idx.strip().isdigit()]

                # Validate indices and select items
                selected = []
                for idx in indices:
                    if 0 <= idx < len(evidence):
                        selected.append(evidence[idx])

                if selected:
                    return selected[:3]  # Cap at 3 max

        except Exception as e:
            logger.warning(f"Failed to use LLM for evidence selection: {e}, falling back to first 2 items")

        # Fallback: just take first 2 items
        return evidence[:2]

    def _format_pr_impact_section(self) -> str:
        """Format the PR Impact Assessment section."""
        if not self.pr_impact_assessment or not self.pr_impact_assessment.strip():
            return ""

        parts = ["## 🔍 PR Impact Assessment\n\n"]

        # Add likelihood header
        likelihood_emoji, likelihood = self._extract_likelihood()
        parts.append(f"{likelihood_emoji} **Impact Likelihood:** {likelihood}\n\n")

        # Add assessment text
        assessment_text = self._get_assessment_text()
        if assessment_text:
            parts.append(f"{assessment_text}\n\n")

        # Add code snippets and affected files
        parts.extend(self._format_code_snippets())
        parts.extend(self._format_affected_files())

        return "".join(parts)

    def _extract_likelihood(self) -> tuple[str, str]:
        """Extract likelihood emoji and text from assessment."""
        if not self.pr_impact_assessment:
            return "⚪", "Unlikely"

        assessment_lower = self.pr_impact_assessment.lower()

        likelihood_map = {
            "likelihood: high": ("🔴", "High"),
            "likelihood: medium": ("🟡", "Medium"),
            "likelihood: low": ("🟢", "Low"),
        }

        for pattern, (emoji, text) in likelihood_map.items():
            if pattern in assessment_lower:
                return emoji, text

        return "⚪", "Unlikely"

    def _get_assessment_text(self) -> str:
        """Get assessment text without the likelihood line."""
        if not self.pr_impact_assessment:
            return ""

        assessment_lines = self.pr_impact_assessment.split("\n")
        return "\n".join(line for line in assessment_lines if not line.lower().startswith("likelihood:")).strip()

    def _format_code_snippets(self) -> list[str]:
        """Format code snippets section."""
        if not self.code_snippets:
            return []

        parts = ["### 💡 Relevant Code Changes\n\n"]

        for filename, change_type, snippet in self.code_snippets:
            file_header = self._create_file_header(filename, change_type)
            parts.append(f"{file_header}\n\n")
            parts.append("<details>\n<summary>View changes</summary>\n\n")
            parts.append(f"```diff\n{snippet}\n```\n\n")
            parts.append("</details>\n\n")

        return parts

    def _create_file_header(self, filename: str, change_type: str) -> str:
        """Create file header with optional link."""
        if self.repository and self.pr_context:
            file_url = f"https://github.com/{self.repository}/blob/{self.pr_context.head_sha}/{filename}"
            return f"**[`{filename}`]({file_url})** ({change_type})"
        return f"**`{filename}`** ({change_type})"

    def _format_affected_files(self) -> list[str]:
        """Format affected files section."""
        if not self.change_correlations:
            return []

        high_conf = [c for c in self.change_correlations if c.confidence in ("high", "medium")]
        if not high_conf:
            return []

        parts = ["### 📝 All Affected Files\n\n"]
        file_confidence = self._collect_file_confidence(high_conf)

        for file_ref, conf in sorted(file_confidence.items())[:10]:
            conf_badge = "🔴" if conf == "high" else "🟡"
            file_line = self._create_file_line(file_ref, conf_badge)
            parts.append(f"{file_line}\n")

        parts.append("\n")
        return parts

    def _collect_file_confidence(self, correlations: list[CorrelationResult]) -> dict[str, str]:
        """Collect unique files with their highest confidence level."""
        file_confidence: dict[str, str] = {}

        for corr in correlations:
            for file_ref in corr.related_files:
                cleaned_ref = self._extract_file_path(file_ref)
                # Keep highest confidence for each file
                if cleaned_ref not in file_confidence or corr.confidence == "high":
                    file_confidence[cleaned_ref] = corr.confidence

        return file_confidence

    def _extract_file_path(self, file_ref: str) -> str:
        """Extract clean file path from reference string."""
        if ":" not in file_ref:
            return file_ref

        # Could be "file.py:123" or "text: file.py"
        parts_split = file_ref.split(":")
        for part in parts_split:
            if "/" in part or part.endswith((".py", ".js", ".ts", ".go", ".java", ".md")):
                return part.strip()

        return file_ref

    def _create_file_line(self, file_ref: str, conf_badge: str) -> str:
        """Create file line with optional GitHub link."""
        if self.repository and self.pr_context:
            file_url = f"https://github.com/{self.repository}/blob/{self.pr_context.head_sha}/{file_ref}"
            return f"- {conf_badge} [`{file_ref}`]({file_url})"
        return f"- {conf_badge} `{file_ref}`"

    def _format_evidence_section(self) -> str:
        """Format the Evidence section with grouped failures."""
        if not self.step_analyses:
            return ""

        parts = ["<details>\n<summary><b>📊 Evidence</b></summary>\n\n"]
        groups = self._group_similar_failures()

        for step_name, analyses in groups.items():
            if len(analyses) > 1:
                parts.extend(self._format_multiple_failures(step_name, analyses))
            else:
                parts.extend(self._format_single_failure(step_name, analyses[0]))

        parts.append("</details>\n\n")
        return "".join(parts)

    def _format_multiple_failures(self, step_name: str, analyses: list[StepAnalysis]) -> list[str]:
        """Format section for multiple jobs failing the same step."""
        parts = []
        job_names = [a.job_name for a in analyses]
        parts.append(f"### ❌ {step_name}\n\n")
        parts.append(f"**Failed in {len(analyses)} jobs:** {', '.join(job_names)}\n\n")

        representative = analyses[0]
        parts.append(f"**Category:** {representative.failure_category}\n\n")
        parts.append(f"**Root Cause:** {representative.root_cause}\n\n")

        parts.extend(self._format_evidence_details(representative))
        return parts

    def _format_single_failure(self, step_name: str, analysis: StepAnalysis) -> list[str]:
        """Format section for a single failure."""
        parts = []
        parts.append(f"### ❌ {analysis.job_name} / {step_name}\n\n")
        parts.append(f"**Category:** {analysis.failure_category}\n\n")
        parts.append(f"**Root Cause:** {analysis.root_cause}\n\n")

        parts.extend(self._format_evidence_details(analysis))
        return parts

    def _format_evidence_details(self, analysis: StepAnalysis) -> list[str]:
        """Format evidence details if available."""
        if not analysis.evidence:
            return []

        useful_evidence = self._select_useful_evidence(analysis.evidence, analysis.root_cause)
        if not useful_evidence:
            return []

        parts = ["<details>\n<summary>📋 <b>View Detailed Evidence</b></summary>\n\n"]
        parts.extend(self._format_evidence_items(useful_evidence))
        parts.append("</details>\n\n")
        return parts

    def _format_evidence_items(self, evidence_items: list[dict[str, Any]]) -> list[str]:
        """Format individual evidence items."""
        parts = []
        for item in evidence_items:
            source = item.get("source", "unknown")
            content = self._truncate_content(item.get("content", ""))

            parts.append(f"**Source:** `{source}`\n\n")
            parts.append(f"```\n{content}\n```\n\n")
        return parts

    def _truncate_content(self, content: str) -> str:
        """Truncate and clean content for display."""
        content = content.replace("`", "'").strip()
        if len(content) > 500:
            return content[:500] + "\n... (truncated)"
        return content

    def to_markdown(self) -> str:
        """Generate markdown formatted report with leak detection."""
        parts = [
            "# 🔍 Workflow Failure Analysis\n\n",
            "| | |\n",
            "|---|---|\n",
            f"| **Workflow** | `{self.workflow_name}` |\n",
            f"| **Run ID** | {self._get_run_url()} |\n",
        ]

        if self.pr_number:
            parts.append(f"| **Pull Request** | {self._get_pr_url()} |\n")

        # Category with emoji
        category_emoji = {
            "infrastructure": "🏗️",
            "test": "🧪",
            "build": "🔨",
            "configuration": "⚙️",
            "timeout": "⏱️",
            "unknown": "❓",
        }.get(self.category.lower(), "❓")

        parts.append(f"| **Category** | {category_emoji} {self.category.title()} |\n")
        parts.append("\n---\n\n")

        # Root Cause section
        parts.append("## 🎯 Root Cause\n\n")
        parts.append(f"{self.summary}\n\n")

        # Technical Details section
        parts.append("## 🔬 Technical Details\n\n")
        parts.append(f"{self.detailed_analysis}\n\n")

        # PR Impact Assessment with improved formatting
        pr_section = self._format_pr_impact_section()
        if pr_section:
            parts.append(pr_section)

        # Evidence section with grouping
        evidence_section = self._format_evidence_section()
        if evidence_section:
            parts.append(evidence_section)

        # Add footer
        parts.append("---\n\n")
        parts.append("<sub>\n\n")
        parts.append("Generated by [gha-failure-analysis](https://github.com/calebevans/gha-failure-analysis)\n\n")
        parts.append("</sub>\n")

        markdown_output = "".join(parts)

        # Sanitize for secret leaks
        leak_detector = LeakDetector()
        sanitized_output = leak_detector.sanitize_text(markdown_output)

        return sanitized_output


class FailureAnalyzer(dspy.Module):  # type: ignore[misc]
    """DSPy module for analyzing workflow failures."""

    def __init__(
        self,
        preprocessor: Any = None,
        config: Any = None,
        tokens_per_step: int = 100_000,
        tokens_per_test: int = 50_000,
        tokens_per_artifact_batch: int = 50_000,
        pr_context: PRContext | None = None,
    ) -> None:
        """Initialize the analyzer.

        Args:
            preprocessor: LogPreprocessor for reducing log size
            config: Config for settings
            tokens_per_step: Token limit per step
            tokens_per_test: Token limit per test
            tokens_per_artifact_batch: Token limit per artifact batch
            pr_context: Optional PR context for correlation analysis
        """
        super().__init__()
        self.step_analyzer = dspy.ChainOfThought(AnalyzeStepFailure)
        self.test_analyzer = dspy.ChainOfThought(AnalyzeTestFailure)
        self.artifact_analyzer = dspy.Predict(AnalyzeArtifacts)
        self.rca_generator = dspy.ChainOfThought(GenerateRCA)
        self.diff_extractor = dspy.Predict(ExtractRelevantDiffSection)
        self.preprocessor = preprocessor
        self.config = config
        self.tokens_per_step = tokens_per_step
        self.tokens_per_test = tokens_per_test
        self.tokens_per_artifact_batch = tokens_per_artifact_batch
        self.pr_context = pr_context

        # Initialize correlator if PR context is available
        self.correlator = ChangeCorrelator() if pr_context else None

    def _get_step_context(self, job: JobResult, step: StepResult) -> str:
        """Extract step context."""
        return f"Job: {job.name}, Step {step.number}: {step.name}"

    def _read_log_content(self, job: JobResult, step: StepResult) -> str:
        """Read log content for a step."""
        if not job.log_path:
            return "(No log content available)"

        try:
            # For now, return full job log - in future, parse by step
            return Path(job.log_path).read_text()
        except Exception as e:
            logger.error(f"Failed to read log from {job.log_path}: {e}")
            return "(No log content available)"

    @retry_with_backoff(max_retries=3, base_delay=2.0, rate_limit_delay=10.0)
    def _call_step_analyzer(self, step_name: str, log_content: str, step_context: str, pr_context: str) -> Any:
        """Call DSPy step analyzer with retry handling."""
        return self.step_analyzer(
            step_name=step_name,
            log_content=log_content,
            step_context=step_context,
            pr_context=pr_context,
        )

    def _analyze_step(self, job: JobResult, step: StepResult) -> StepAnalysis:
        """Analyze a single failed step with automatic retry logic."""
        logger.info(f"Analyzing step: {job.name}/{step.name}")

        step_context = self._get_step_context(job, step)
        log_content = self._read_log_content(job, step)
        pr_context_str = self._prepare_pr_context_for_step(job, step)

        try:
            result = self._call_step_analyzer(
                step_name=f"{job.name}/{step.name}",
                log_content=log_content,
                step_context=step_context,
                pr_context=pr_context_str,
            )

            evidence_list = self._parse_step_evidence(result.evidence, step.name)

            return StepAnalysis(
                job_name=job.name,
                step_name=step.name,
                failure_category=result.failure_category,
                root_cause=result.root_cause,
                evidence=evidence_list,
            )
        except Exception as e:
            logger.error(f"Step {step.name}: analysis failed after all retries: {e}")
            return StepAnalysis(
                job_name=job.name,
                step_name=step.name,
                failure_category="unknown",
                root_cause=f"Analysis failed: {str(e)}",
                evidence=[],
            )

    def _prepare_pr_context_for_step(self, job: JobResult, step: StepResult) -> str:
        """Prepare PR context string for step analysis."""
        if not self.pr_context:
            return ""

        related_files = find_related_files(self.pr_context, f"{job.name}/{step.name}")
        changes_summary = summarize_changes(self.pr_context, max_files=10)

        if related_files:
            relevant_diffs = get_relevant_diffs(self.pr_context, related_files)
            return f"{changes_summary}\n\n{relevant_diffs}"

        return changes_summary

    def _parse_step_evidence(self, raw_evidence: str | None, step_name: str) -> list[dict[str, str]]:
        """Parse and validate evidence JSON."""
        try:
            raw_evidence = raw_evidence or "[]"
            sanitized_evidence = _sanitize_json_string(raw_evidence)
            evidence_list = json.loads(sanitized_evidence)
            return evidence_list if isinstance(evidence_list, list) else []
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to parse evidence JSON for {step_name}: {e}")
            return []

    @retry_with_backoff(max_retries=3, base_delay=2.0, rate_limit_delay=10.0)
    def _call_test_analyzer(
        self,
        test_identifier: str,
        failure_type: str,
        failure_message: str,
        failure_details: str,
        pr_context: str,
    ) -> Any:
        """Call DSPy test analyzer with retry handling."""
        return self.test_analyzer(
            test_identifier=test_identifier,
            failure_type=failure_type,
            failure_message=failure_message,
            failure_details=failure_details,
            pr_context=pr_context,
        )

    @retry_with_backoff(max_retries=3, base_delay=2.0, rate_limit_delay=10.0, context_errors_no_retry=True)
    def _call_rca_generator(
        self,
        workflow_name: str,
        run_id: str,
        pr_number: str,
        failed_steps_analysis: str,
        failed_tests_analysis: str,
        additional_context: str,
        pr_changes_summary: str,
        change_correlations: str,
    ) -> Any:
        """Call DSPy RCA generator with retry handling."""
        return self.rca_generator(
            workflow_name=workflow_name,
            run_id=run_id,
            pr_number=pr_number,
            failed_steps_analysis=failed_steps_analysis,
            failed_tests_analysis=failed_tests_analysis,
            additional_context=additional_context,
            pr_changes_summary=pr_changes_summary,
            change_correlations=change_correlations,
        )

    def _analyze_test_failure(self, test: FailedTest) -> TestFailureAnalysis:
        """Analyze a single test failure with automatic retry logic."""
        logger.info(f"Analyzing test: {test.test_identifier}")

        details = self._preprocess_test_details(test)
        pr_context_str = self._prepare_pr_context_for_test(test)

        try:
            result = self._call_test_analyzer(
                test_identifier=test.test_identifier,
                failure_type=test.failure_type or test.error_type or "Unknown",
                failure_message=test.failure_message or test.error_message or "No message",
                failure_details=details,
                pr_context=pr_context_str,
            )

            return TestFailureAnalysis(
                test_identifier=test.test_identifier,
                source_file=test.source_file,
                root_cause_summary=result.root_cause_summary,
            )
        except Exception as e:
            logger.error(f"Test {test.test_identifier}: analysis failed after all retries: {e}")
            return TestFailureAnalysis(
                test_identifier=test.test_identifier,
                source_file=test.source_file,
                root_cause_summary=f"Analysis failed: {str(e)}",
            )

    def _preprocess_test_details(self, test: FailedTest) -> str:
        """Preprocess test details if preprocessor is available."""
        details = test.combined_details
        if self.preprocessor:
            details = self.preprocessor.preprocess(
                details, f"test:{test.test_identifier}", max_tokens=self.tokens_per_test
            )
        return details

    def _prepare_pr_context_for_test(self, test: FailedTest) -> str:
        """Prepare PR context string for test analysis."""
        if not self.pr_context:
            return ""

        related_files = find_related_files(self.pr_context, test.test_identifier)
        changes_summary = summarize_changes(self.pr_context, max_files=10)

        if related_files:
            relevant_diffs = get_relevant_diffs(self.pr_context, related_files)
            return f"{changes_summary}\n\n{relevant_diffs}"

        return changes_summary

    def _analyze_all_test_failures(self, tests: list[FailedTest]) -> list[TestFailureAnalysis]:
        """Analyze all test failures."""
        if not tests:
            return []

        logger.info(f"Analyzing {len(tests)} test failures")
        return [self._analyze_test_failure(test) for test in tests]

    def _correlate_all_failures(
        self,
        step_analyses: list[StepAnalysis],
        test_analyses: list[TestFailureAnalysis],
    ) -> list[CorrelationResult]:
        """Run correlation analysis on all failures.

        Args:
            step_analyses: List of step analysis results
            test_analyses: List of test analysis results

        Returns:
            List of correlation results
        """
        if not self.pr_context or not self.correlator:
            return []

        logger.info("Correlating failures with PR changes")
        correlations = []

        # Correlate step failures
        for step_analysis in step_analyses:
            try:
                corr = self.correlator.correlate_with_step(
                    step_name=f"{step_analysis.job_name}/{step_analysis.step_name}",
                    failure_details=step_analysis.root_cause,
                    pr_context=self.pr_context,
                )
                correlations.append(corr)
            except Exception as e:
                logger.warning(f"Failed to correlate step {step_analysis.step_name}: {e}")

        # Correlate test failures
        for test_analysis in test_analyses:
            try:
                corr = self.correlator.correlate_with_test(
                    test_identifier=test_analysis.test_identifier,
                    failure_details=test_analysis.root_cause_summary,
                    pr_context=self.pr_context,
                )
                correlations.append(corr)
            except Exception as e:
                logger.warning(f"Failed to correlate test {test_analysis.test_identifier}: {e}")

        # Log summary
        high_conf = len([c for c in correlations if c.confidence in ("high", "medium")])
        logger.info(f"Correlation complete: {high_conf}/{len(correlations)} failures likely caused by PR")

        return correlations

    def _extract_files_from_errors(self, step_analyses: list[StepAnalysis]) -> set[str]:
        """Extract filenames mentioned in error messages and evidence.

        Args:
            step_analyses: List of step analysis results

        Returns:
            Set of filenames found in errors
        """
        error_files = set()

        for analysis in step_analyses[:5]:  # Check first 5 failures
            # Check root cause
            if analysis.root_cause:
                # Look for file paths in root cause (e.g., "tests/test_core.py:64")
                import re

                file_patterns = re.findall(r"[\w/]+\.[\w]+(?::\d+)?", analysis.root_cause)
                for pattern in file_patterns:
                    filename = pattern.split(":")[0]
                    if "/" in filename:
                        error_files.add(filename)

            # Check evidence
            for evidence_item in analysis.evidence[:3]:
                source = evidence_item.get("source", "")
                # Extract filename from source like "tests/test_core.py:64: AttributeError"
                import re

                file_patterns = re.findall(r"([\w/]+\.[\w]+)", source)
                error_files.update(file_patterns)

        logger.debug(f"Extracted {len(error_files)} files from error messages: {error_files}")
        return error_files

    def _extract_relevant_code_snippets(
        self,
        report_summary: str,
        correlations: list[CorrelationResult],
        step_analyses: list[StepAnalysis],
    ) -> list[tuple[str, str, str]]:
        """Extract relevant code snippets from PR changes using LLM.

        Args:
            report_summary: The failure summary from the report
            correlations: List of correlation results
            step_analyses: Step analysis results to extract error file references

        Returns:
            List of tuples: (filename, change_type, snippet)
        """
        if not self.pr_context or not correlations:
            logger.debug("No PR context or correlations available for snippet extraction")
            return []

        error_files = self._extract_files_from_errors(step_analyses)
        high_conf = [c for c in correlations if c.confidence in ("high", "medium")]
        logger.info(f"Extracting code snippets from {len(high_conf)} high-confidence correlations")

        candidate_files = self._collect_candidate_files(high_conf, error_files)
        snippets = self._extract_snippets_from_candidates(candidate_files, report_summary)

        logger.info(f"Extracted {len(snippets)} code snippets")
        return snippets

    def _collect_candidate_files(
        self, correlations: list[CorrelationResult], error_files: set[str]
    ) -> list[tuple[str, int]]:
        """Collect candidate files with priority scoring."""
        candidate_files: list[tuple[str, int]] = []
        seen = set()

        for corr in correlations:
            for file_ref in corr.related_files:
                filename = self._clean_filename(file_ref)

                if filename in seen:
                    continue
                seen.add(filename)

                priority = self._calculate_file_priority(filename, corr.confidence, error_files)
                candidate_files.append((filename, priority))

        candidate_files.sort(key=lambda x: x[1], reverse=True)
        return candidate_files

    def _clean_filename(self, file_ref: str) -> str:
        """Extract and clean filename from file reference."""
        filename = file_ref.split(":")[0].strip()
        return filename.strip("`'\"- ")

    def _calculate_file_priority(self, filename: str, confidence: str, error_files: set[str]) -> int:
        """Calculate priority score for a file."""
        priority = 10 if confidence == "high" else 5

        if filename in error_files:
            priority += 20
            logger.debug(f"Boosting priority for {filename} (appears in errors)")

        return priority

    def _extract_snippets_from_candidates(
        self, candidate_files: list[tuple[str, int]], report_summary: str
    ) -> list[tuple[str, str, str]]:
        """Extract snippets from top candidate files."""
        snippets = []

        for filename, priority in candidate_files[:3]:
            logger.debug(f"Checking file: {filename} (priority: {priority})")
            snippet = self._try_extract_snippet_for_file(filename, report_summary)

            if snippet:
                snippets.append(snippet)

        return snippets

    def _try_extract_snippet_for_file(self, filename: str, report_summary: str) -> tuple[str, str, str] | None:
        """Try to extract a snippet for a specific file."""
        file_change = self._find_file_change(filename)

        if not file_change:
            logger.debug(f"File {filename} not found in PR changes or has no patch")
            return None

        return self._extract_diff_snippet(filename, file_change, report_summary)

    def _find_file_change(self, filename: str) -> FileChange | None:
        """Find file change in PR context."""
        if not self.pr_context:
            return None

        for file_change in self.pr_context.changed_files:
            if file_change.filename == filename and file_change.patch:
                return file_change
        return None

    def _extract_diff_snippet(
        self, filename: str, file_change: FileChange, report_summary: str
    ) -> tuple[str, str, str] | None:
        """Extract relevant diff snippet using LLM."""
        logger.info(f"Extracting relevant diff section for {filename}")

        try:
            result = self.diff_extractor(
                filename=filename,
                full_diff=file_change.patch,
                failure_summary=report_summary,
            )

            relevant_section = result.relevant_section.strip()

            if self._is_relevant_section(relevant_section):
                change_type = f"+{file_change.additions} -{file_change.deletions}"
                logger.info(f"Added snippet for {filename} ({len(relevant_section)} chars)")
                return (filename, change_type, relevant_section)

            logger.debug(f"LLM found no relevant changes in {filename}")
            return None
        except Exception as e:
            logger.warning(f"Failed to extract relevant diff section for {filename}: {e}")
            return None

    def _is_relevant_section(self, section: str) -> bool:
        """Check if extracted section is relevant."""
        return bool(section and "no directly relevant" not in section.lower())

    def _create_synthesis_context(
        self,
        step_analyses: list[StepAnalysis],
        test_analyses: list[TestFailureAnalysis],
        artifact_analyses: list[ArtifactAnalysis],
    ) -> tuple[str, str, str]:
        """Create unified context for RCA generation."""
        steps_dict = [
            {
                "job_name": a.job_name,
                "step_name": a.step_name,
                "failure_category": a.failure_category,
                "root_cause": a.root_cause,
                "evidence": a.evidence,
            }
            for a in step_analyses
        ]

        tests_dict = [
            {
                "test_identifier": a.test_identifier,
                "source_file": a.source_file,
                "root_cause_summary": a.root_cause_summary,
            }
            for a in test_analyses
        ]

        artifacts_dict = {
            "note": "Supplemental diagnostic artifacts providing system context.",
            "analyses": [
                {
                    "artifact_path": a.artifact_path,
                    "key_findings": a.key_findings,
                }
                for a in artifact_analyses
            ],
        }

        return json.dumps(steps_dict, indent=2), json.dumps(tests_dict, indent=2), json.dumps(artifacts_dict, indent=2)

    def forward(self, workflow_analysis: WorkflowAnalysis) -> RCAReport:
        """Analyze workflow failures and generate RCA report."""
        logger.info(f"Starting analysis of {workflow_analysis.total_failed_steps} failed steps")

        if workflow_analysis.total_failed_steps == 0:
            raise ValueError("No failures to analyze")

        # Analyze all failed steps across all jobs
        step_analyses = []
        for job in workflow_analysis.failed_jobs:
            for step in job.failed_steps:
                analysis = self._analyze_step(job, step)
                step_analyses.append(analysis)

        test_analyses = self._analyze_all_test_failures(workflow_analysis.failed_tests)

        # Run correlation if PR context is available
        correlations = self._correlate_all_failures(step_analyses, test_analyses)

        steps_json, tests_json, artifacts_json = self._create_synthesis_context(step_analyses, test_analyses, [])

        # Prepare PR context for RCA generation
        pr_changes_summary = ""
        change_correlations_json = ""
        if self.pr_context:
            pr_changes_summary = summarize_changes(self.pr_context, max_files=15)
            if correlations:
                change_correlations_json = correlations_to_json(correlations)

        logger.info("Generating overall RCA")
        try:
            pr_num = (
                str(workflow_analysis.workflow_run.pr_number) if workflow_analysis.workflow_run.pr_number else "N/A"
            )
            rca = self._call_rca_generator(
                workflow_name=workflow_analysis.workflow_run.name,
                run_id=str(workflow_analysis.workflow_run.id),
                pr_number=pr_num,
                failed_steps_analysis=steps_json,
                failed_tests_analysis=tests_json,
                additional_context=artifacts_json,
                pr_changes_summary=pr_changes_summary,
                change_correlations=change_correlations_json,
            )

            # Create report object first (needed for snippet extraction)
            pr_num_str = (
                str(workflow_analysis.workflow_run.pr_number) if workflow_analysis.workflow_run.pr_number else None
            )
            pr_assessment = rca.pr_impact_assessment if hasattr(rca, "pr_impact_assessment") else None
            report = RCAReport(
                workflow_name=workflow_analysis.workflow_run.name,
                run_id=str(workflow_analysis.workflow_run.id),
                pr_number=pr_num_str,
                summary=rca.summary,
                detailed_analysis=rca.detailed_analysis,
                category=rca.category,
                step_analyses=step_analyses,
                test_analyses=test_analyses,
                pr_context=self.pr_context,
                pr_impact_assessment=pr_assessment,
                change_correlations=correlations,
                repository=workflow_analysis.workflow_run.repository,
            )

            # Extract code snippets after report is created
            report.code_snippets = self._extract_relevant_code_snippets(report.summary, correlations, step_analyses)

            return report
        except Exception as e:
            logger.error(f"RCA generation failed: {e}")
            pr_num_str = (
                str(workflow_analysis.workflow_run.pr_number) if workflow_analysis.workflow_run.pr_number else None
            )
            report = RCAReport(
                workflow_name=workflow_analysis.workflow_run.name,
                run_id=str(workflow_analysis.workflow_run.id),
                pr_number=pr_num_str,
                summary=f"RCA generation failed: {str(e)}",
                detailed_analysis="Unable to generate detailed analysis.",
                category="unknown",
                step_analyses=step_analyses,
                test_analyses=test_analyses,
                pr_context=self.pr_context,
                change_correlations=correlations,
                repository=workflow_analysis.workflow_run.repository,
            )

            # Try to extract snippets even on error
            try:
                report.code_snippets = self._extract_relevant_code_snippets(
                    f"RCA generation failed: {str(e)}", correlations, step_analyses
                )
            except Exception:
                pass

            return report
