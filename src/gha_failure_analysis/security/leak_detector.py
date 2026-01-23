import logging

from detect_secrets.core.plugins.util import get_mapping_from_secret_type_to_class

logger = logging.getLogger(__name__)


class LeakDetector:
    """Detects and redacts secrets from text to prevent leaks in logs/comments."""

    def __init__(self) -> None:
        """Initialize the leak detector with default plugins."""
        self.plugins = get_mapping_from_secret_type_to_class()
        logger.debug(f"Initialized leak detector with {len(self.plugins)} plugins")

    def sanitize_text(self, text: str) -> str:
        """Scan text for secrets and replace them with redaction labels.

        Args:
            text: The text to scan for secrets

        Returns:
            The sanitized text with secrets replaced by [REDACTED: type] labels
        """
        if not text:
            return text

        secrets = self._detect_secrets(text)
        if not secrets:
            return text

        # replace secrets in reverse order to maintain string positions
        secrets.sort(key=lambda x: x[0], reverse=True)
        sanitized = text
        for start, end, secret_type in secrets:
            redaction_label = self._get_redaction_label(secret_type)
            sanitized = sanitized[:start] + redaction_label + sanitized[end:]

        logger.info(f"Redacted {len(secrets)} secret(s) from text")
        return sanitized

    def _detect_secrets(self, text: str) -> list[tuple[int, int, str]]:
        """Detect all secrets in the text and return their positions.

        Args:
            text: The text to scan

        Returns:
            List of tuples (start_pos, end_pos, secret_type) for each secret found
        """
        secrets = []
        lines = text.split("\n")
        current_pos = 0

        for line_num, line in enumerate(lines, start=1):
            line_with_newline = line + ("\n" if line_num < len(lines) else "")

            for plugin_name, plugin_class in self.plugins.items():
                try:
                    plugin = plugin_class()
                    findings = plugin.analyze_line(filename="", line=line, line_number=line_num, **{})

                    for secret in findings:
                        secret_matches = self._find_secret_positions(line, secret)
                        for match_start, match_end in secret_matches:
                            abs_start = current_pos + match_start
                            abs_end = current_pos + match_end
                            secrets.append((abs_start, abs_end, secret.type))

                except Exception as e:
                    logger.debug(f"Plugin {plugin_name} failed on line {line_num}: {e}")

            current_pos += len(line_with_newline)

        return secrets

    def _find_secret_positions(self, line: str, secret: object) -> list[tuple[int, int]]:
        """Find the start and end positions of a secret in a line.

        Args:
            line: The line containing the secret
            secret: PotentialSecret object from detect-secrets

        Returns:
            List of (start, end) tuples for each occurrence
        """
        positions = []

        try:
            # extract secret location from the line
            if hasattr(secret, "secret_value"):
                secret_value = secret.secret_value
                start = 0
                while True:
                    pos = line.find(secret_value, start)
                    if pos == -1:
                        break
                    positions.append((pos, pos + len(secret_value)))
                    start = pos + 1

        except Exception as e:
            logger.debug(f"Failed to find secret position: {e}")

        return positions

    def _get_redaction_label(self, secret_type: str) -> str:
        """Get a human-readable redaction label for a secret type.

        Args:
            secret_type: The type of secret detected

        Returns:
            Formatted redaction label
        """
        return f"[REDACTED: {secret_type}]"
