# tests/

## Overview

```
tests/
  support/           # Shared test infrastructure (not tests themselves)
    fakes/           # Deterministic in-memory backends
      gcs.py         # FakeGcsStore
      vm.py          # FakeVmBackend, VmDescribeStatus, VmMetadataCallRecord
      github.py      # FakeGithubBackend
    fixtures/        # Reusable pytest fixtures
      paths.py       # repo_root, gcp_code_root, github_bmt_root, repo_stage_root
      ci.py          # mock_github_api, mock_config
    captures.py      # CallRecorder — generic attribute recorder for inline fakes
    testutils.py     # GITHUB_OUTPUT helpers (combined_output, read_github_output, decode_output_json)
    repo_policy.py   # SAMPLE_PROJECT, repo_stage_bmt_manifest — centralises hardcoded paths
  _support/          # Legacy shims — re-export from tests.support (backward compat only)
  ci/                # CI-layer tests (.github/bmt/ci/)
  bmt/               # BMT runtime tests (gcp/image/runtime/)
  gcp/               # GCP value-type / domain tests
  github/            # GitHub presentation / check rendering tests
  infra/             # Infrastructure alignment tests
  tools/             # Developer tool tests
```

## Test layers

| Marker | Description |
|--------|-------------|
| `unit` | Pure logic — no subprocess, network, or live filesystem |
| `contract` | Deterministic CLI contracts using fakes/mocks |
| `integration` | Subprocess / filesystem orchestration with local fakes |
| `live_smoke` | Cloud-backed smoke tests (not run in default fast gate) |

Files that deviate from `unit` carry an explicit `pytestmark`:

- `tests/ci/test_ci_commands.py` → `integration`
- `tests/tools/test_devtools_exit_codes.py` → `integration`
- `tests/tools/test_upload_runner_dedup.py` → `contract`

## Three concepts called "mock"

These are distinct:

1. **`FakeGcsStore`** — in-memory GCS; used for contract tests that write/read plans and results.
2. **`MagicMock` / `monkeypatch`** — Python-level function replacement for unit-isolating specific callsites.
3. **`BMT_USE_MOCK_RUNNER` / `use_mock_runner`** — Cloud Run runtime flag that substitutes a synthetic runner score for the real `kardome_runner` binary. Dev-only; not present in production workflows.

## Using shared support

```python
# Fakes
from tests.support.fakes.gcs import FakeGcsStore
from tests.support.fakes.vm import FakeVmBackend

# Fixtures (import in conftest.py or test module)
from tests.support.fixtures.ci import mock_config, mock_github_api
from tests.support.fixtures.paths import repo_root

# Generic capture recorder
from tests.support.captures import CallRecorder

# Policy constants
from tests.support.repo_policy import SAMPLE_PROJECT, repo_stage_bmt_manifest
```

## Running

```bash
just test          # Full suite: pytest + ruff + ty + actionlint + shellcheck
uv run python -m pytest tests/ -v          # All tests
uv run python -m pytest tests/ -m unit     # Unit tests only
uv run python -m pytest tests/ -m "not live_smoke"  # Skip cloud-backed tests
```
