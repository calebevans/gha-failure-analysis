import logging
import xml.etree.ElementTree as ElementTree

from .xunit_models import FailedTest

logger = logging.getLogger(__name__)


class XUnitParser:
    """Parser for XUnit/JUnit XML test result files."""

    def parse_xunit_file(self, content: str, source_path: str) -> list[FailedTest]:
        """Parse an XUnit XML file and extract failed test cases.

        Args:
            content: XML content as string
            source_path: Path to the source file (for reference in results)

        Returns:
            List of FailedTest objects for tests with failures or errors
        """
        failed_tests: list[FailedTest] = []

        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as e:
            logger.warning(f"Failed to parse XML from {source_path}: {e}")
            return failed_tests

        # Find all testcase elements (can be direct children or nested in testsuite)
        testcases = root.findall(".//testcase")

        for testcase in testcases:
            # Check if this testcase has a failure or error
            failure = testcase.find("failure")
            error = testcase.find("error")

            if failure is not None or error is not None:
                failed_test = self._extract_failed_test(testcase, failure, error, source_path)
                if failed_test:
                    failed_tests.append(failed_test)

        logger.debug(f"Parsed {len(failed_tests)} failed tests from {source_path}")
        return failed_tests

    def _extract_failed_test(
        self,
        testcase: ElementTree.Element,
        failure: ElementTree.Element | None,
        error: ElementTree.Element | None,
        source_path: str,
    ) -> FailedTest | None:
        """Extract a FailedTest from a testcase element.

        Args:
            testcase: The testcase XML element
            failure: The failure element (if present)
            error: The error element (if present)
            source_path: Path to the source XML file

        Returns:
            FailedTest object or None if extraction fails
        """
        try:
            # Extract testcase attributes
            test_name = testcase.get("name", "unknown")
            class_name = testcase.get("classname")
            test_id = testcase.get("id")

            # Extract failure information
            failure_type = None
            failure_message = None
            failure_content = None
            if failure is not None:
                failure_type = failure.get("type")
                failure_message = failure.get("message")
                failure_content = self._get_element_text(failure)

            # Extract error information
            error_type = None
            error_message = None
            error_content = None
            if error is not None:
                error_type = error.get("type")
                error_message = error.get("message")
                error_content = self._get_element_text(error)

            # Extract system-out and system-err
            system_out_elem = testcase.find("system-out")
            system_out = self._get_element_text(system_out_elem) if system_out_elem is not None else None

            system_err_elem = testcase.find("system-err")
            system_err = self._get_element_text(system_err_elem) if system_err_elem is not None else None

            return FailedTest(
                test_name=test_name,
                class_name=class_name,
                test_id=test_id,
                failure_type=failure_type,
                failure_message=failure_message,
                failure_content=failure_content,
                error_type=error_type,
                error_message=error_message,
                error_content=error_content,
                system_out=system_out,
                system_err=system_err,
                source_file=source_path,
            )
        except Exception as e:
            logger.warning(f"Failed to extract test case from {source_path}: {e}")
            return None

    def _get_element_text(self, element: ElementTree.Element | None) -> str | None:
        """Safely extract text content from an XML element.

        Args:
            element: XML element

        Returns:
            Text content or None if empty
        """
        if element is None:
            return None

        text = element.text
        if text and text.strip():
            return text.strip()

        return None
