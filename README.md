<div align="center">

# GitHub Actions Failure Analysis

[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-Failure%20Analysis-blue.svg?colorA=24292e&colorB=0366d6&style=flat&logo=githubactions&logoColor=white)](https://github.com/marketplace/actions/github-actions-failure-analysis)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/calebevans/gha-failure-analysis?logo=github)](https://github.com/calebevans/gha-failure-analysis/releases)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=calebevans_gha-failure-analysis&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=calebevans_gha-failure-analysis)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=calebevans_gha-failure-analysis&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=calebevans_gha-failure-analysis)

</div>

When your GitHub Actions workflow fails, this action automatically analyzes logs, correlates failures with code changes, and generates actionable root cause analysis reports.

## Features

- **Semantic Log Processing**: Uses [cordon](https://github.com/calebevans/cordon)'s transformer-based anomaly detection to extract relevant failure information from massive logs
- **LLM-Powered Analysis**: Leverages DSPy and your choice of LLM (OpenAI, Anthropic, Gemini, Ollama) for intelligent failure analysis
- **PR Context-Aware**: Automatically correlates code changes with failures to determine if PR changes caused the issue
- **Flexible Triggering**: Run in the same workflow or via `workflow_run` events
- **Secret Detection**: Automatically redacts secrets from all outputs
- **Professional Reports**: Generates structured, actionable root cause analyses with evidence and recommendations

## Quick Start

### Same Workflow (Recommended)

Add as a final job that runs on failure:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm test

  analyze:
    needs: test
    if: failure()
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: calebevans/gha-failure-analysis@v1
        with:
          llm-provider: openai
          llm-model: gpt-4o
          llm-api-key: ${{ secrets.OPENAI_API_KEY }}
          post-pr-comment: true
```

### Separate Workflow

Create a separate workflow that triggers on completion:

```yaml
name: Failure Analysis

on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]

jobs:
  analyze:
    if: ${{ github.event.workflow_run.conclusion == 'failure' }}
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: calebevans/gha-failure-analysis@v1
        with:
          run-id: ${{ github.event.workflow_run.id }}
          llm-provider: anthropic
          llm-model: claude-3-5-sonnet-20241022
          llm-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

> **Note:** The `github-token` parameter is optional and defaults to `${{ github.token }}`. Only specify it if you need to use a custom token with different permissions.

## How It Works

When a workflow fails, the action:

1. **Fetches** workflow run metadata, failed jobs, and logs
2. **Preprocesses** logs using cordon to extract semantically relevant sections
3. **Analyzes** failures (steps and tests) using LLMs to identify root causes
4. **Correlates** PR changes with failures to assess impact
5. **Synthesizes** findings into a concise root cause analysis report
6. **Outputs** results as job summaries, PR comments, and JSON artifacts

## PR Context Analysis

### What It Does

When analyzing PR-triggered workflow failures, the action automatically:

- **Fetches PR changes**: Retrieves all files changed with their diffs
- **Correlates with failures**: Uses LLM analysis to determine if code changes likely caused each failure
- **Assesses impact**: Provides clear assessment of whether PR changes are responsible
- **Identifies culprits**: Points to specific files and lines that may have caused issues

This helps you quickly understand if failures are due to your changes or unrelated infrastructure issues.

### Example Output

When PR changes cause failures, you'll see:

```markdown
## 🔍 PR Impact Assessment

🔴 **Impact Likelihood:** High

The test failures are directly related to code changes in this PR:
- Changes to `src/auth/login.py` introduced a validation error
- Modified authentication logic conflicts with test expectations in `tests/test_auth.py`

### 💡 Relevant Code Changes

**src/auth/login.py** (+12 -3)
- Modified password validation logic at lines 45-52
- Added new timeout parameter affecting authentication flow
```

### Configuration

PR context analysis is **enabled by default** for PR-triggered runs. To customize:

```yaml
- uses: calebevans/gha-failure-analysis@v1
  with:
    llm-provider: openai
    llm-model: gpt-4o
    llm-api-key: ${{ secrets.OPENAI_API_KEY }}
    analyze-pr-context: true  # Default: true
    pr-context-token-budget: 20  # % of context for PR diffs (default: 20%)
```

**Important:** The action analyzes the **specific commit that triggered the workflow**, not the current PR state. This ensures accurate analysis even if the PR has been updated since the failure.

## Configuration

### Github Settings

This workflow uses the default github-token to fetch the execution logs, depending on the specific repo permission setting the user might need to either set a [private access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) or create a [github app and set its keys](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps)


### Required Inputs

| Input | Description | Example |
|-------|-------------|---------|
| `llm-provider` | LLM provider | `openai`, `anthropic`, `gemini`, `ollama` |
| `llm-model` | Model name | `gpt-4o`, `claude-3-5-sonnet-20241022` |
| `llm-api-key` | LLM API key | `${{ secrets.OPENAI_API_KEY }}` |

### Optional Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `github-token` | `${{ github.token }}` | GitHub token for API access |
| `run-id` | Current run | Workflow run ID to analyze |
| `pr-number` | Auto-detect | Manual PR number override (for testing) |
| `llm-base-url` | Provider default | Custom LLM API base URL |
| `post-pr-comment` | `false` | Post analysis as PR comment |
| `analyze-pr-context` | `true` | Analyze failures in context of PR changes |
| `pr-context-token-budget` | `20` | % of context to allocate for PR diffs (0-50) |
| `ignored-jobs` | None | Comma-separated job name patterns to ignore |
| `ignored-steps` | None | Comma-separated step name patterns to ignore |
| `artifact-patterns` | None | Comma-separated glob patterns for artifacts |

### Cordon Options (Log Preprocessing)

| Input | Default | Description |
|-------|---------|-------------|
| `cordon-backend` | `sentence-transformers` | Embedding backend (`remote` or `sentence-transformers`) |
| `cordon-model-name` | `all-MiniLM-L6-v2` | Embedding model name |
| `cordon-api-key` | None | API key for remote embeddings |
| `cordon-device` | `cpu` | Device for local embeddings (`cpu`/`cuda`/`mps`) |
| `cordon-batch-size` | `32` | Batch size for embeddings |

### Outputs

| Output | Description |
|--------|-------------|
| `summary` | Brief failure summary |
| `category` | Failure category (infrastructure/test/build/configuration/timeout/unknown) |
| `report-path` | Path to full JSON report |

## LLM Providers

The action supports any LLM provider compatible with DSPy/LiteLLM:

### OpenAI

```yaml
llm-provider: openai
llm-model: gpt-4o
llm-api-key: ${{ secrets.OPENAI_API_KEY }}
```

### Anthropic

```yaml
llm-provider: anthropic
llm-model: claude-3-5-sonnet-20241022
llm-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Google Gemini

```yaml
llm-provider: gemini
llm-model: gemini-2.5-flash
llm-api-key: ${{ secrets.GEMINI_API_KEY }}
```

### Ollama (Local)

```yaml
llm-provider: ollama
llm-model: llama3.1:70b
# No API key needed for local Ollama
```

### Custom Endpoint

```yaml
llm-provider: openai
llm-model: custom-model
llm-api-key: ${{ secrets.CUSTOM_API_KEY }}
llm-base-url: https://custom-llm-gateway.example.com
```

## Cordon Configuration

Cordon preprocesses logs to extract semantically relevant sections. Configure it to use remote or local embeddings.

### Remote Embeddings (Recommended)

**Fast and no model downloads required.** Uses your LLM provider's embedding API:

```yaml
cordon-backend: remote
cordon-model-name: openai/text-embedding-3-small
cordon-api-key: ${{ secrets.OPENAI_API_KEY }}
```

**Supported providers:**
- OpenAI: `openai/text-embedding-3-small`, `openai/text-embedding-3-large`
- Google Gemini: `gemini/gemini-embedding-001`, `gemini/text-embedding-004`
- Cohere: `cohere/embed-english-v3.0`, `cohere/embed-multilingual-v3.0`
- Voyage: `voyage/voyage-2`, `voyage/voyage-code-2`

**Example with Gemini:**

```yaml
cordon-backend: remote
cordon-model-name: gemini/gemini-embedding-001
cordon-api-key: ${{ secrets.GEMINI_API_KEY }}
```

### Local Embeddings

For local embedding generation (slower, requires model download):

```yaml
cordon-backend: sentence-transformers
cordon-model-name: all-MiniLM-L6-v2
cordon-device: cpu  # or cuda/mps for GPU
```

**GPU Acceleration:** If your runner has a GPU, use it for 5-15x faster preprocessing:

```yaml
cordon-device: cuda  # NVIDIA GPUs
cordon-device: mps   # Apple Silicon
```

## Example Output

The action generates structured analyses like:

````markdown
# 🔍 Workflow Failure Analysis

| | |
|---|---|
| **Workflow** | `CI` |
| **Run ID** | [#21234567890](https://github.com/owner/repo/actions/runs/21234567890) |
| **Pull Request** | [#123](https://github.com/owner/repo/pull/123) |
| **Category** | 🧪 Test |

---

## 🎯 Root Cause

Test suite failed due to timeout waiting for database connection in integration tests.

## 🔬 Technical Details

### Immediate Cause
Integration test `test_user_authentication` timed out after 30 seconds while attempting
to establish a database connection.

### Contributing Factors
Database initialization script took longer than expected, causing connection pool exhaustion.

## 🔍 PR Impact Assessment

🔴 **Impact Likelihood:** High

The changes to `db/init.sql` increased startup time, directly causing the timeout.

### 💡 Relevant Code Changes

**db/init.sql** (+45 -12)
```diff
+ -- Added complex indexes that slow initialization
+ CREATE INDEX CONCURRENTLY idx_users_email ON users(email);
```

## 📊 Evidence

### ❌ test / Run integration tests

**Category:** test

**Root Cause:** Connection timeout after 30 seconds

<details>
<summary>📋 <b>View Detailed Evidence</b></summary>

```
ERROR: Timeout waiting for database connection
Connection pool exhausted: 0/10 connections available
Database startup took 45.2s (expected: <10s)
```
</details>
````

## Security

The action automatically detects and redacts secrets from all outputs using [detect-secrets](https://github.com/Yelp/detect-secrets). This prevents accidental exposure in:

- Job summaries
- PR comments
- JSON reports
- Console logs
