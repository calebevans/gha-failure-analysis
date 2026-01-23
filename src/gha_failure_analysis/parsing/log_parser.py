import logging
import re
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class LogLine:
    """Represents a single line from GitHub Actions logs."""

    timestamp: datetime
    content: str
    raw_line: str


@dataclass
class StepLog:
    """Represents logs for a single step."""

    step_name: str
    lines: list[LogLine]
    annotations: list[str]  # Error/warning annotations


class GitHubActionsLogParser:
    """Parser for GitHub Actions log format."""

    # GitHub Actions log line format: 2024-01-15T10:30:45.1234567Z content
    TIMESTAMP_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)\s+(.*)$")

    # GitHub Actions annotations
    GROUP_START_PATTERN = re.compile(r"##\[group\](.+)")
    GROUP_END_PATTERN = re.compile(r"##\[endgroup\]")
    ERROR_PATTERN = re.compile(r"##\[error\](.+)")
    WARNING_PATTERN = re.compile(r"##\[warning\](.+)")
    SECTION_PATTERN = re.compile(r"##\[section\](.+)")

    def parse_log_file(self, log_path: str) -> list[StepLog]:
        """Parse a GitHub Actions log file into steps.

        Args:
            log_path: Path to the log file

        Returns:
            List of StepLog objects
        """
        with open(log_path, encoding="utf-8", errors="replace") as f:
            content = f.read()

        return self.parse_log_content(content)

    def parse_log_content(self, content: str) -> list[StepLog]:
        """Parse GitHub Actions log content into steps.

        Args:
            content: Raw log content

        Returns:
            List of StepLog objects
        """
        steps: list[StepLog] = []
        current_step: StepLog | None = None

        lines = content.split("\n")

        for raw_line in lines:
            if not raw_line.strip():
                continue

            # Parse timestamp and content
            match = self.TIMESTAMP_PATTERN.match(raw_line)
            if not match:
                # Line without timestamp, append to current step if exists
                if current_step:
                    # Create a log line with no timestamp
                    log_line = LogLine(timestamp=datetime.min, content=raw_line, raw_line=raw_line)
                    current_step.lines.append(log_line)
                continue

            timestamp_str, content_part = match.groups()

            try:
                # Parse ISO 8601 timestamp
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.min

            # Check for group markers
            group_start = self.GROUP_START_PATTERN.match(content_part)
            if group_start:
                # Start new step
                step_name = group_start.group(1).strip()
                if current_step:
                    steps.append(current_step)
                current_step = StepLog(step_name=step_name, lines=[], annotations=[])
                continue

            group_end = self.GROUP_END_PATTERN.match(content_part)
            if group_end:
                # End current step
                if current_step:
                    steps.append(current_step)
                    current_step = None
                continue

            # Check for annotations
            error_match = self.ERROR_PATTERN.match(content_part)
            if error_match and current_step:
                current_step.annotations.append(f"ERROR: {error_match.group(1)}")

            warning_match = self.WARNING_PATTERN.match(content_part)
            if warning_match and current_step:
                current_step.annotations.append(f"WARNING: {warning_match.group(1)}")

            # Add line to current step
            if current_step:
                log_line = LogLine(timestamp=timestamp, content=content_part, raw_line=raw_line)
                current_step.lines.append(log_line)
            else:
                # No current step, might be preamble - create a default step
                if not steps or steps[-1].step_name != "Setup":
                    current_step = StepLog(step_name="Setup", lines=[], annotations=[])
                    steps.append(current_step)
                    current_step = None

        # Add final step if exists
        if current_step:
            steps.append(current_step)

        logger.info(f"Parsed {len(steps)} steps from log")
        return steps

    def extract_step_logs(self, log_path: str, step_name: str) -> str:
        """Extract logs for a specific step.

        Args:
            log_path: Path to the log file
            step_name: Name of the step to extract

        Returns:
            Combined log content for the step
        """
        steps = self.parse_log_file(log_path)

        for step in steps:
            if step.step_name == step_name:
                return self.format_step_logs(step)

        logger.warning(f"Step '{step_name}' not found in log")
        return ""

    def format_step_logs(self, step: StepLog) -> str:
        """Format a StepLog into a string.

        Args:
            step: StepLog object

        Returns:
            Formatted log content
        """
        lines = []

        # Add annotations at the top if any
        if step.annotations:
            lines.append("=== Annotations ===")
            lines.extend(step.annotations)
            lines.append("")

        # Add log lines
        for log_line in step.lines:
            lines.append(log_line.content)

        return "\n".join(lines)

    def get_step_names(self, log_path: str) -> list[str]:
        """Get list of step names from a log file.

        Args:
            log_path: Path to the log file

        Returns:
            List of step names
        """
        steps = self.parse_log_file(log_path)
        return [step.step_name for step in steps]
