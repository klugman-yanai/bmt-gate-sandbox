# tests/

## Overview

```
tests/
  support/           # Shared test infrastructure (not tests themselves)
    fakes/           # Deterministic in-memory backends
      gcs.py         # FakeGcsStore
      github.py      # FakeGithubBackend
    fixtures/        # Reusable pytest fixtures
      paths.py       # repo_root, gcp_code_root, github_bmt_root, repo_stage_root
      ci.py          # mock_github_api, mock_config
    captures.py      # CallRecorder — generic attribute recorder for inline fakes
    testutils.py     # GITHUB_OUTPUT helpers and matrix contract assertions
    repo_policy.py   # SAMPLE_PROJECT, repo_stage_bmt_manifest — centralises hardcoded paths
  _support/          # Legacy shims — re-export from tests.support (backward compat only)
  ci/                # CI-layer tests (.github/bmt/ci/)
  bmt/               # BMT runtime tests (gcp/image/runtime/)
  gcp/               # GCP value-type / domain tests
  github/            # GitHub presentation / check rendering tests
  infra/             # Infrastructure alignment tests
  tools/             # Developer tool tests
```

## Pre-push vs full suite

**Pre-push** (if [prek](https://prek.j178.dev/) hooks are installed) runs **`pytest -m "unit or contract"`** only. That is a **narrow fast gate** (dozens of tests), not the whole tree—tests without those markers are **not** executed on push.

**Full verification** before a PR: run **`just test`** or **`uv run python -m pytest tests/ -v`** so every test under `tests/` runs. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## Test layers

| Marker | Description |
|--------|-------------|
| `unit` | Pure logic — no subprocess, network, or live filesystem beyond `tmp_path` |
| `contract` | Deterministic CLI contracts using fakes/mocks |
| `integration` | Subprocess / filesystem orchestration with local fakes |
| `bmt_plugin_load` | Load published BMT plugins from committed `gcp/stage` (import side effects) |

Re-add a `live_smoke` marker in [pyproject.toml](../pyproject.toml) when you introduce real cloud-backed tests that should be opt-in.

Modules that are not plain unit tests set an explicit module `pytestmark` (or per-test marks). Examples:

| Module / area | Marker |
|---------------|--------|
| [tests/ci/test_ci_models.py](ci/test_ci_models.py) | `unit` |
| [tests/ci/test_ci_commands_negative.py](ci/test_ci_commands_negative.py) | `contract` |
| [tests/tools/test_upload_runner_dedup.py](tools/test_upload_runner_dedup.py) | `contract` |
| [tests/gcp/test_value_types.py](gcp/test_value_types.py) | `unit` |
| [tests/ci/](ci/) (workflow guards, dispatch, runner resolution, etc.) | `unit` |
| [tests/github/](github/) | `unit` |
| [tests/gcp/test_bmt_domain_status.py](gcp/test_bmt_domain_status.py) | `unit` |
| [tests/infra/](infra/) | `unit` |
| [tests/tools/](tools/) (CLI, bucket helpers, repo vars, etc.) | `unit` or `integration` (see file) |
| [tests/bmt/](bmt/) runtime / scaffold | `integration` |
| [tests/bmt/test_stage_bmt_manifests.py](bmt/test_stage_bmt_manifests.py) | `unit` (static checks), per-test `bmt_plugin_load` / `integration` |
| [tests/test_coordinator_summaries.py](../test_coordinator_summaries.py) | `unit` |

Every test module sets `pytestmark` (or per-test marks) so `pytest -m "unit or contract"` matches the pre-push hook.

**Plugins (see [pyproject.toml](../pyproject.toml)):** `pytest-socket` blocks network unless a test opts in; `pytest-mock` is available for the `mocker` fixture but the suite often uses `monkeypatch`. **`pytest-randomly`** randomizes order; flaky failures usually indicate shared state bugs.

## Three concepts called "mock"

These are distinct:

1. **`FakeGcsStore`** — in-memory GCS; used for contract tests that write/read plans and results.
2. **`MagicMock` / `monkeypatch`** — Python-level function replacement for unit-isolating specific callsites.
3. **`BMT_USE_MOCK_RUNNER` / `use_mock_runner`** — Cloud Run runtime flag that substitutes a synthetic runner score for the real `kardome_runner` binary. Dev-only; not present in production workflows.

## Using shared support

```python
# Fakes
from tests.support.fakes.gcs import FakeGcsStore
# Fixtures (import in conftest.py or test module)
from tests.support.fixtures.ci import mock_config, mock_github_api
from tests.support.fixtures.paths import repo_root

# Generic capture recorder
from tests.support.captures import CallRecorder

# Policy constants
from tests.support.repo_policy import SAMPLE_PROJECT, repo_stage_bmt_manifest

# Matrix / GITHUB_OUTPUT contracts (shared with integration tests)
from tests.support.testutils import assert_github_matrix_include_shape, read_github_output
```

## Running

```bash
just test          # Full suite: pytest + ruff + ty + actionlint + shellcheck
uv run python -m pytest tests/ -v          # All tests
uv run python -m pytest tests/ -m unit       # Unit-marked modules only
uv run python -m pytest tests/ -m "unit or contract"   # Same as pre-push fast gate
```

Directory-scoped runs (no marker required): e.g. `uv run python -m pytest tests/ci/ -v`, `tests/bmt/`, `tests/gcp/`.

Optional: `uv run python -m pytest tests/ -n auto` speeds up CPU-bound runs; combine with care when debugging order-dependent failures (`pytest-randomly` already stresses ordering).

## Scripts under `tools/scripts/`

Operational scripts (for example dataset upload helpers) are not covered by the default `tests/` tree unless listed above; treat them as **maintainer / manual** unless a test is added alongside a change.
