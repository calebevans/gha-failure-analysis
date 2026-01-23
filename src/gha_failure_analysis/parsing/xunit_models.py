from dataclasses import dataclass


@dataclass
class FailedTest:
    """Represents a failed test case from an XUnit XML file."""

    test_name: str
    class_name: str | None
    test_id: str | None
    failure_type: str | None
    failure_message: str | None
    failure_content: str | None
    error_type: str | None
    error_message: str | None
    error_content: str | None
    system_out: str | None
    system_err: str | None
    source_file: str

    @property
    def test_identifier(self) -> str:
        """Get the full test identifier (class.name or just name)."""
        if self.class_name:
            return f"{self.class_name}.{self.test_name}"
        return self.test_name

    @property
    def combined_failure_info(self) -> str:
        """Combine failure/error type and message."""
        if self.failure_type or self.failure_message:
            return f"{self.failure_type or 'Failure'}: {self.failure_message or 'No message'}"
        if self.error_type or self.error_message:
            return f"{self.error_type or 'Error'}: {self.error_message or 'No message'}"
        return "Unknown failure"

    @property
    def combined_details(self) -> str:
        """Combine all failure details for analysis."""
        parts = []

        if self.failure_content:
            parts.append(f"--- Failure Content ---\n{self.failure_content}")
        if self.error_content:
            parts.append(f"--- Error Content ---\n{self.error_content}")
        if self.system_out:
            parts.append(f"--- System Out ---\n{self.system_out}")
        if self.system_err:
            parts.append(f"--- System Err ---\n{self.system_err}")

        return "\n\n".join(parts) if parts else "No additional details available"
