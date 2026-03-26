# CLAUDE.md

Agent rules for **bmt-gcloud**: VM-based BMT execution via Google Cloud, scoring audio quality metrics against a baseline to gate CI.

**Read next:** [docs/README.md](docs/README.md) (index).

## Code layout

| Area | Path |
| ---- | ---- |
| VM runtime (deployed to VM via bucket sync) | `backend/` — config, orchestrator, watcher, per-project managers |
| Bucket mirror (1:1 GCS mirror) | `benchmarks/` — projects, runners, inputs, outputs |
| CI package (portable, distributable) | `ci/src/bmt_gate/` — matrix, trigger, handshake, VM lifecycle |
| Infra (Terraform) | `infra/terraform/` |
| Developer tools CLI | `tools/` — bucket sync, layout policy, shared libs |
| Tests | `tests/` |

**Path constants:** `tools/repo/paths.py` — `DEFAULT_CONFIG_ROOT` (`backend`), `DEFAULT_STAGE_ROOT` (`benchmarks`), `CI_ROOT` (`ci`).

**Recipes:** `just` (see `just list`). Common: `just test`, `just deploy` (bucket sync, needs `GCS_BUCKET`).

## CI package (`ci/`)

Standalone Python package: `bmt-gate`. Src layout at `ci/src/bmt_gate/`.

- **Zero imports from `backend.*`** — has its own contract modules (`bmt_config.py`, `_constants.py`)
- Workspace member in root `pyproject.toml`
- Consumer repos install via: `bmt-gate = { git = "...", subdirectory = "ci" }`
- CLI: `uv run bmt <command>` (matrix, write-run-trigger, wait-handshake, start-vm, etc.)

## Time

| Need | Use |
| ---- | --- |
| Wall clock / TTL | `whenever.Instant.now()` (+ helpers in `tools/shared/time_utils.py`) |
| Durations / timeouts | `time.monotonic()` |
| Sleep / backoff | `time.sleep()` |

Avoid `time.time()` / `datetime.now()` for new code.

## Lint / types

```bash
uv sync && ruff check . && ruff format --check . && basedpyright
```

## Tests

```bash
uv run python -m pytest tests/ -v
```

No GCS or VM required for unit tests.

## Shell (when available)

Prefer **`rg`** (not `grep -r`), **`fd`** (not `find`), **`jq`**, **`uv`**, **`just`**.
