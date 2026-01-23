"""Tests for GitHub models."""

from gha_failure_analysis.github.models import JobResult, StepResult, WorkflowAnalysis, WorkflowRun


class TestWorkflowRun:
    """Tests for WorkflowRun model."""

    def test_workflow_run_creation(self) -> None:
        """Test creating a WorkflowRun."""
        run = WorkflowRun(
            id=123,
            name="CI",
            head_branch="main",
            head_sha="abc123",
            status="completed",
            conclusion="failure",
            html_url="https://github.com/owner/repo/actions/runs/123",
            repository="owner/repo",
            pr_number=456,
        )

        assert run.id == 123
        assert run.name == "CI"
        assert run.pr_number == 456


class TestStepResult:
    """Tests for StepResult model."""

    def test_step_passed(self) -> None:
        """Test step passed property."""
        step = StepResult(
            name="Build",
            number=1,
            status="completed",
            conclusion="success",
        )
        assert step.passed

    def test_step_failed(self) -> None:
        """Test step failed."""
        step = StepResult(
            name="Test",
            number=2,
            status="completed",
            conclusion="failure",
        )
        assert not step.passed


class TestJobResult:
    """Tests for JobResult model."""

    def test_failed_steps(self) -> None:
        """Test getting failed steps."""
        job = JobResult(
            id=1,
            name="build",
            status="completed",
            conclusion="failure",
            steps=[
                StepResult(name="Step1", number=1, status="completed", conclusion="success"),
                StepResult(name="Step2", number=2, status="completed", conclusion="failure"),
                StepResult(name="Step3", number=3, status="completed", conclusion="failure"),
            ],
        )

        failed = job.failed_steps
        assert len(failed) == 2
        assert failed[0].name == "Step2"
        assert failed[1].name == "Step3"


class TestWorkflowAnalysis:
    """Tests for WorkflowAnalysis model."""

    def test_total_failed_steps(self) -> None:
        """Test counting total failed steps."""
        workflow_run = WorkflowRun(
            id=123,
            name="CI",
            head_branch="main",
            head_sha="abc123",
            status="completed",
            conclusion="failure",
            html_url="https://github.com/owner/repo/actions/runs/123",
            repository="owner/repo",
        )

        job1 = JobResult(
            id=1,
            name="job1",
            status="completed",
            conclusion="failure",
            steps=[
                StepResult(name="Step1", number=1, status="completed", conclusion="failure"),
                StepResult(name="Step2", number=2, status="completed", conclusion="failure"),
            ],
        )

        job2 = JobResult(
            id=2,
            name="job2",
            status="completed",
            conclusion="failure",
            steps=[
                StepResult(name="Step1", number=1, status="completed", conclusion="failure"),
            ],
        )

        analysis = WorkflowAnalysis(
            workflow_run=workflow_run,
            failed_jobs=[job1, job2],
        )

        assert analysis.total_failed_steps == 3
