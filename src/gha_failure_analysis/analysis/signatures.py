import dspy


class AnalyzeStepFailure(dspy.Signature):  # type: ignore[misc]
    """Analyze a CI pipeline step failure and identify the root cause.

    IMPORTANT: Logs have been preprocessed with semantic anomaly detection.
    - Only the most anomalous/unusual log sections are shown
    - Normal/repeated patterns are removed to reduce noise
    - Log sections are wrapped in XML tags: <block lines="X-Y" score="S">...</block>
    - Score indicates anomaly level (higher = more unusual, typically 0.0-1.0)
    - Higher scored blocks often contain errors, exceptions, or critical events
    - Final output lines are always included

    Focus on high-scoring blocks and error patterns. Be concise and specific.

    If PR context is provided, consider whether code changes in the PR may have
    contributed to this failure. Look for connections between changed files and
    the failure location.
    """

    step_name: str = dspy.InputField(desc="Name of the failed step")
    log_content: str = dspy.InputField(desc="Semantically filtered log content showing anomalous/error lines")
    step_context: str = dspy.InputField(desc="Step's position and dependencies in the pipeline")
    pr_context: str = dspy.InputField(
        desc="Optional: PR changes summary and relevant diffs if this is a PR-triggered run", default=""
    )

    failure_category: str = dspy.OutputField(
        desc="Failure category: infrastructure/test/build/configuration/timeout/unknown"
    )
    root_cause: str = dspy.OutputField(desc="Concise technical root cause (1-2 sentences)")
    evidence: str = dspy.OutputField(
        desc=(
            'JSON array of evidence items. Each item has "source" (artifact path) and "content" (log excerpt). '
            'Format: [{"source": "job/step-name line 123", "content": "error message here"}, ...]. '
            "Use actual paths relative to the workflow (e.g., job/step-name). "
            "Include line numbers when relevant. Content should be verbatim log/error text. "
            "Return valid JSON array - escape quotes and newlines properly."
        )
    )
    pr_related: str = dspy.OutputField(
        desc="If PR context provided, indicate if failure is likely related to PR changes: yes/no/maybe",
        default="unknown",
    )


class AnalyzeTestFailure(dspy.Signature):  # type: ignore[misc]
    """Analyze a test failure from XUnit results.

    IMPORTANT: Failure details have been preprocessed with semantic anomaly detection.
    - Only anomalous/unusual content is shown
    - Content may be wrapped in XML tags: <block lines="X-Y" score="S">...</block>
    - Higher scores indicate more unusual/critical content
    - Focus on high-scoring blocks for root cause

    Be concise and technical. Identify the immediate failure, not symptoms.
    Distinguish: creation failures vs validation failures vs timeouts.

    If PR context is provided, consider whether code changes in the PR may have
    caused this test to fail. Look for connections between changed files and
    the test location or functionality.
    """

    test_identifier: str = dspy.InputField(desc="Full test identifier")
    failure_type: str = dspy.InputField(desc="Type of failure or error")
    failure_message: str = dspy.InputField(desc="Failure or error message")
    failure_details: str = dspy.InputField(
        desc="Semantically filtered failure content showing anomalous lines, stack traces, and errors"
    )
    pr_context: str = dspy.InputField(
        desc="Optional: PR changes summary and relevant diffs if this is a PR-triggered run", default=""
    )

    root_cause_summary: str = dspy.OutputField(desc="One sentence stating the immediate technical cause")
    pr_related: str = dspy.OutputField(
        desc="If PR context provided, indicate if failure is likely related to PR changes: yes/no/maybe",
        default="unknown",
    )


class AnalyzeArtifacts(dspy.Signature):  # type: ignore[misc]
    """Analyze multiple diagnostic artifacts to extract key findings from each.

    Artifacts provide supplemental context about system state.
    They are NOT failure sources - extract relevant environmental details.

    IMPORTANT: Content has been preprocessed with semantic anomaly detection.
    - Only anomalous/unusual sections are shown
    - May be wrapped in XML tags: <block lines="X-Y" score="S">...</block>

    Process each artifact independently and return findings for each.
    You MUST return a valid JSON array even if artifacts are empty or have no findings.
    """

    artifacts_json: str = dspy.InputField(desc="JSON string of dict mapping artifact paths to preprocessed content")

    artifact_findings: str = dspy.OutputField(
        desc=(
            'Return a valid JSON array. Each element must have "artifact_path" and "key_findings" keys. '
            'Example: [{"artifact_path": "path/file.json", "key_findings": "Found X pods in error."}]. '
            "key_findings should be 2-3 sentences summarizing relevant details or anomalies. "
            "If an artifact has no relevant findings, set key_findings to 'No significant findings.' "
            "ALWAYS return valid JSON - never return empty or malformed responses."
        )
    )


class GenerateRCA(dspy.Signature):  # type: ignore[misc]
    """Generate a professional, concise root cause analysis for pipeline failures.

    CRITICAL INSTRUCTIONS:
    1. Identify the PRIMARY blocking failure (what failed FIRST and prevented other operations)
    2. Distinguish PRIMARY (prevented execution) vs SECONDARY (quality/validation checks)
    3. Be concise - avoid repeating the same information in multiple sections
    4. Each section should provide DISTINCT information:
       - Summary: State the PRIMARY root cause in 1-2 sentences
       - Detailed Analysis: Explain WHY it failed and impact (technical details, timeline)
       - Do NOT restate the root cause multiple times
    5. Use professional technical language
    6. Focus on facts from the analyses - do not invent information

    Cross-reference step and test analyses to understand causation.

    If PR context is provided:
    - Assess whether the failures are related to code changes in the PR
    - Use correlation results to support your assessment
    - Be clear about the relationship (or lack thereof) between PR changes and failures
    """

    workflow_name: str = dspy.InputField(desc="Name of the GitHub Actions workflow")
    run_id: str = dspy.InputField(desc="Workflow run ID")
    pr_number: str = dspy.InputField(desc="PR number if PR-triggered, otherwise 'N/A'")
    failed_steps_analysis: str = dspy.InputField(desc="JSON string of step failure analyses")
    failed_tests_analysis: str = dspy.InputField(desc="JSON string of test failure analyses")
    additional_context: str = dspy.InputField(
        desc=(
            "JSON string of supplemental diagnostic artifacts (logs, state dumps, etc.). "
            "These are NOT failures - use only for environment context when diagnosing failures above."
        )
    )
    pr_changes_summary: str = dspy.InputField(
        desc="Optional: Summary of PR changes if this is a PR-triggered run", default=""
    )
    change_correlations: str = dspy.InputField(
        desc="Optional: JSON string of correlation analyses between PR changes and failures", default=""
    )

    summary: str = dspy.OutputField(
        desc=(
            "Single concise sentence stating WHAT failed (the PRIMARY blocking failure). "
            "Example: 'Workflow failed due to test execution timeout in integration test suite.'"
        )
    )
    detailed_analysis: str = dspy.OutputField(
        desc=(
            "Structured technical explanation. Format as:\n"
            "### Immediate Cause\n"
            "(what directly failed - 1-2 sentences)\n\n"
            "### Contributing Factors\n"
            "(related issues if any - 1-2 sentences)\n\n"
            "Use markdown subheadings (###) for each section. Be concise and scannable."
        )
    )
    category: str = dspy.OutputField(
        desc="Primary failure category: infrastructure/test/build/configuration/timeout/unknown"
    )
    pr_impact_assessment: str = dspy.OutputField(
        desc=(
            "If PR context provided, assess whether PR changes caused the failure. "
            "Format: 'Likelihood: [high/medium/low/unlikely]\\n\\n"
            "[2-3 sentences explaining the relationship between changes and failure]'. "
            "Focus on WHAT changed and WHY it caused the failure. "
            "Do NOT mention internal analysis details, function names, or data structures. "
            "Speak directly about the code changes and their impact. "
            "If no PR context, return empty string."
        ),
        default="",
    )


class CorrelateChangesWithFailure(dspy.Signature):  # type: ignore[misc]
    """Analyze relationship between PR code changes and a failure.

    Determine if the code changes likely caused the failure by examining:
    - Changed files vs failed test/step file paths
    - Types of code changes (logic, dependencies, config, etc.)
    - Error messages and stack traces mentioning changed code
    - Temporal relationship (did this break after these changes?)

    Be analytical and evidence-based. Don't assume causation without clear links.
    Consider both direct and indirect relationships:
    - Direct: test file changed, corresponding test fails
    - Indirect: shared dependency changed, multiple tests fail
    - Unrelated: infrastructure issue independent of code changes
    """

    failure_type: str = dspy.InputField(desc="Type: 'step' or 'test'")
    failure_identifier: str = dspy.InputField(desc="Step or test name")
    failure_details: str = dspy.InputField(desc="Root cause and error details from failure analysis")
    changed_files_summary: str = dspy.InputField(desc="Summary of files changed in the PR")
    relevant_diffs: str = dspy.InputField(desc="Diffs of potentially related files")

    likelihood: str = dspy.OutputField(desc="Likelihood PR caused this failure: high/medium/low/unlikely")
    related_changes: str = dspy.OutputField(
        desc=(
            "Specific file paths that may have caused failure. "
            "Format: one file path per line, optionally with :line suffix. "
            "Example: 'src/auth/login.py:45' or 'tests/test_auth.py'. "
            "Return ONLY clean file paths, no markdown, no bullets, no explanatory text. "
            "Empty if unlikely."
        )
    )
    reasoning: str = dspy.OutputField(
        desc="Concise explanation of correlation (2-3 sentences). Include evidence or state why unrelated."
    )


class ExtractRelevantDiffSection(dspy.Signature):  # type: ignore[misc]
    """Extract the most relevant section of a diff that caused a failure.

    Given a file diff and failure details, identify the specific lines in the diff
    that are most likely responsible for the failure. Focus on:
    - Lines that add/remove/modify code related to error messages
    - Changes to function signatures, class attributes, or APIs
    - Configuration or constant changes

    Return ONLY the relevant section, not the entire diff.
    """

    filename: str = dspy.InputField(desc="Name of the file that was changed")
    full_diff: str = dspy.InputField(desc="Complete diff for the file")
    failure_summary: str = dspy.InputField(desc="Brief summary of what failed")

    relevant_section: str = dspy.OutputField(
        desc=(
            "Extract the most relevant 10-20 lines from the diff that likely caused the failure. "
            "Include the @@ hunk header and surrounding context. "
            "If multiple sections are relevant, pick the most important one. "
            "Return the actual diff lines (with +/- prefixes). "
            "If nothing relevant, return 'No directly relevant changes found.'"
        )
    )
