"""Tests for Config module."""
import os
from unittest.mock import patch

from gha_failure_analysis.config import Config


class TestConfig:
    """Tests for Config class."""

    def test_validate_success(self) -> None:
        """Test validation with all required fields."""
        config = Config()
        config.github_token = "test-token"
        config.repository = "owner/repo"
        config.run_id = "123"
        config.llm_provider = "openai"
        config.llm_model = "gpt-4"
        config.llm_api_key = "sk-test"

        errors = config.validate()
        assert errors == []

    def test_validate_missing_fields(self) -> None:
        """Test validation with missing required fields."""
        config = Config()
        config.github_token = ""
        config.repository = ""
        config.run_id = ""
        config.llm_provider = ""
        config.llm_model = ""
        config.llm_api_key = ""

        errors = config.validate()
        assert len(errors) == 6
        assert "GITHUB_TOKEN is required" in errors
        assert "GITHUB_REPOSITORY is required" in errors

    def test_should_ignore_job(self) -> None:
        """Test job filtering."""
        config = Config()
        config.ignored_jobs_patterns = ["test-*", "lint"]

        assert config.should_ignore_job("test-integration")
        assert config.should_ignore_job("test-unit")
        assert config.should_ignore_job("lint")
        assert not config.should_ignore_job("build")

    def test_should_ignore_step(self) -> None:
        """Test step filtering."""
        config = Config()
        config.ignored_steps_patterns = ["Setup*", "Cleanup*"]

        assert config.should_ignore_step("Setup Node.js")
        assert config.should_ignore_step("Cleanup artifacts")
        assert not config.should_ignore_step("Run tests")

    @patch.dict(
        os.environ,
        {
            "INPUT_GITHUB-TOKEN": "test-token",
            "GITHUB_REPOSITORY": "owner/repo",
            "INPUT_RUN-ID": "123",
            "INPUT_LLM-PROVIDER": "openai",
            "INPUT_LLM-MODEL": "gpt-4",
            "INPUT_LLM-API-KEY": "sk-test",
        },
        clear=True,
    )
    def test_from_environment(self) -> None:
        """Test config loaded from environment."""
        config = Config()

        assert config.github_token == "test-token"
        assert config.repository == "owner/repo"
        assert config.run_id == "123"
        assert config.llm_provider == "openai"
        assert config.llm_model == "gpt-4"
        assert config.llm_api_key == "sk-test"
