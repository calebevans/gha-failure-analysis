# gha-failure-analysis

AI-powered analysis of GitHub Actions workflow failures using semantic log preprocessing with [cordon](https://github.com/calebevans/cordon).

## What It Does

When your GitHub Actions workflow fails, this action:

1. **Fetches** workflow run metadata, failed jobs, and logs
2. **Preprocesses** logs using cordon to extract semantically relevant failure information
3. **Analyzes** failures (steps and tests) using LLMs to identify root causes
4. **Synthesizes** findings into a concise root cause analysis report
5. **Outputs** results as job summaries, PR comments (optional), and JSON artifacts

## Features

- **Semantic Log Processing**: Uses cordon's transformer-based anomaly detection to reduce logs to their most relevant sections
- **LLM-Powered Analysis**: Leverages DSPy and your choice of LLM (OpenAI, Anthropic, Google Gemini, Ollama, etc.)
- **PR Context-Aware Analysis**: Intelligently correlates code changes with failures to determine if PR changes caused the failure
- **Flexible Triggering**: Can run in the same workflow or via `workflow_run` events
- **Secret Detection**: Automatically redacts secrets from all outputs
- **Dynamic Token Budgeting**: Optimizes LLM context usage based on failure count
- **Professional Reports**: Generates structured, actionable root cause analyses

## PR Context Analysis

When analyzing PR-triggered workflow failures, the tool automatically:

1. **Fetches PR changes**: Retrieves all files changed in the PR with their diffs
2. **Correlates with failures**: Uses LLM-powered analysis to determine if code changes likely caused each failure
3. **Assesses impact**: Provides a clear assessment of whether the PR changes are responsible for the failures
4. **Identifies related changes**: Points to specific files and lines that may have caused the issues

This helps you quickly understand if failures are due to your changes or unrelated infrastructure issues.

### How It Works

For each failure (step or test), the analyzer:
- **Analyzes the exact commit that was tested**: Uses the workflow run's commit SHA, not the PR's current state
- Identifies files changed in the PR that match the failure location
- Passes relevant code diffs to the LLM along with failure details
- Determines correlation likelihood: high, medium, low, or unlikely
- Synthesizes findings into an overall PR impact assessment

**Important**: The tool analyzes the **specific commit that triggered the workflow**, not the current state of the PR. This means even if the PR has been updated or merged with fixes, it will analyze the code as it was when the failure occurred.

### Example Output

When PR changes cause failures, you'll see:

```markdown
## PR Impact Assessment

**Likelihood PR Changes Caused Failure:** High

The test failures are directly related to code changes in this PR:
- Changes to `src/auth/login.py` introduced a validation error
- Modified authentication logic conflicts with test expectations in `tests/test_auth.py`

### Related Changes
- `src/auth/login.py:45-52` - Modified password validation logic
- `src/config/settings.py:12` - Changed default timeout value
```

### Configuration

PR context analysis is **enabled by default** for PR-triggered runs. To disable or configure:

```yaml
- uses: calebevans/gha-failure-analysis@v1
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
    llm-provider: openai
    llm-model: gpt-4o
    llm-api-key: ${{ secrets.OPENAI_API_KEY }}
    analyze-pr-context: true  # Default: true
    pr-context-token-budget: 20  # % of context for PR diffs (default: 20%)
```

## Usage

### Same Workflow (After Failure)

Add as a final step that runs on failure:

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
    steps:
      - uses: calebevans/gha-failure-analysis@v1
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          llm-provider: openai
          llm-model: gpt-4o
          llm-api-key: ${{ secrets.OPENAI_API_KEY }}
          post-pr-comment: true
```

### Separate Workflow (workflow_run Event)

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
    steps:
      - uses: calebevans/gha-failure-analysis@v1
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          run-id: ${{ github.event.workflow_run.id }}
          llm-provider: anthropic
          llm-model: claude-3-5-sonnet-20241022
          llm-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

## Configuration

### Required Inputs

| Input | Description | Example |
|-------|-------------|---------|
| `github-token` | GitHub token for API access | `${{ secrets.GITHUB_TOKEN }}` |
| `llm-provider` | LLM provider | `openai`, `anthropic`, `gemini`, `ollama` |
| `llm-model` | Model name | `gpt-4o`, `claude-3-5-sonnet-20241022` |
| `llm-api-key` | LLM API key | `${{ secrets.OPENAI_API_KEY }}` |

### Optional Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `run-id` | Current run | Workflow run ID to analyze |
| `pr-number` | Auto-detect | Manual PR number override (for testing) |
| `llm-base-url` | Provider default | Custom LLM API base URL |
| `cordon-device` | `cpu` | Device for cordon (`cpu`/`cuda`/`mps`) |
| `cordon-backend` | `sentence-transformers` | Embedding backend (`remote` or `sentence-transformers`) |
| `cordon-model-name` | `all-MiniLM-L6-v2` | Embedding model (HuggingFace or provider/model for remote) |
| `cordon-api-key` | None | API key for remote embeddings (required if backend is `remote`) |
| `cordon-batch-size` | `32` | Batch size for embeddings |
| `post-pr-comment` | `false` | Post analysis as PR comment |
| `analyze-pr-context` | `true` | Analyze failures in context of PR changes |
| `pr-context-token-budget` | `20` | % of context to allocate for PR diffs (0-50) |
| `ignored-jobs` | None | Comma-separated job name patterns to ignore |
| `ignored-steps` | None | Comma-separated step name patterns to ignore |
| `artifact-patterns` | None | Comma-separated glob patterns for artifacts |

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

Cordon preprocesses logs to extract anomalous sections. You can configure it to use either remote or local embeddings.

### Remote Embeddings (Recommended)

**Fast and no model downloads required.** Use your existing LLM provider's embedding API:

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

If you prefer to run embeddings locally (slower, requires model download):

```yaml
cordon-backend: sentence-transformers
cordon-model-name: all-MiniLM-L6-v2
cordon-device: cpu  # or cuda/mps if GPU available
```

**GPU Acceleration:**
If your runner has a GPU, use it for faster preprocessing:
```yaml
cordon-device: cuda  # or mps for Apple Silicon
```

## Example Output

The action generates a structured analysis like:

```markdown
# Workflow Failure Analysis
**Workflow:** `CI`
**Run ID:** `1234567890` | **PR:** #123 | **Category:** Test

---
## Root Cause

Test suite failed due to timeout waiting for database connection in integration tests.

## Technical Details

### Immediate Cause
Integration test `test_user_authentication` timed out after 30 seconds while attempting
to establish a database connection.

### Contributing Factors
Database initialization script took longer than expected, causing connection pool exhaustion.

### Impact
Blocked all subsequent integration tests from executing, resulting in incomplete test coverage.

## Evidence

**test / Run integration tests** — *test*

<details>
<summary><code>test/integration_test.log line 456</code></summary>

```
ERROR: Timeout waiting for database connection
Connection pool exhausted: 0/10 connections available
```
</details>
```

## Security

The action automatically detects and redacts secrets from all outputs using [detect-secrets](https://github.com/Yelp/detect-secrets). This prevents accidental exposure in:

- Job summaries
- PR comments
- JSON reports
- Console logs

## Performance

- **GPU Acceleration**: Both embedding and scoring use GPU when available (5-15x faster)
- **Dynamic Budgeting**: Automatically adjusts token allocation based on failure count
- **Efficient Batching**: Processes multiple failures optimally
