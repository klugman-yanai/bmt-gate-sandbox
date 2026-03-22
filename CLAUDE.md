# CLAUDE.md

Guidance for **Claude Code** (and similar agents) working in **bmt-gcloud**.

## Project overview

**bmt-gcloud** provides a **realistic path to test production BMT CI** against **real GCS** (and GCP), not mocks. The supported execution model is:

- **GitHub Actions** authenticates with **WIF**, uploads artifacts as needed, and **starts Google Workflows** via the Workflow Executions API.
- **Google Workflows** runs **Cloud Run** jobs: `bmt-control` (plan + coordinator) and `bmt-task-standard` / `bmt-task-heavy` (one BMT leg per task).
- **GCS** holds frozen plans under `triggers/`, snapshots and `current.json` under each project’s `results/` tree. The bucket layout mirrors **`gcp/stage`**.

Legacy **VM + vm_watcher** descriptions in old docs are **not** the current production story. Use **[docs/architecture.md](docs/architecture.md)**, **[docs/pipeline-dag.md](docs/pipeline-dag.md)**, and **[docs/bmt-architecture-deep-dive.md](docs/bmt-architecture-deep-dive.md)** for truth.

**Bucket:** 1:1 mirror of `gcp/stage` at the bucket root (see [gcp/README.md](gcp/README.md), [tools/shared/bucket_env.py](tools/shared/bucket_env.py)). **`gcp/image`** is baked into the VM image; **`gcp/stage`** is the editable mirror of runtime/config content.

**Docs index:** [docs/README.md](docs/README.md) · **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md) · **Security:** [SECURITY.md](SECURITY.md)

## Time and clocks

| Need | Use |
| ---- | --- |
| Wall-clock timestamps, TTL | `whenever.Instant.now()`; `.format_iso(unit="second")` or project `_now_iso()` / [tools/shared/time_utils.py](tools/shared/time_utils.py) |
| Durations, timeouts | `time.monotonic()` |
| Sleep / backoff | `time.sleep()` |

Avoid `time.time()` / `datetime.now()` for new code. CI and `gcp/` may use local helpers to stay self-contained when synced to the bucket.

## `tools/` layout

| Prefix | Role |
| ------ | ---- |
| `tools/shared/` | Libraries (not CLI entrypoints) |
| `tools/remote/` | GCS: sync, upload, verify, validate |
| `tools/bmt/` | Local batch runner, monitor, wait verdicts |
| `tools/repo/` | Layout policies, GitHub/repo vars, paths |
| `tools/pulumi/` | Pulumi → GitHub vars |

**CLI:** `uv run python -m tools --help` (Typer). **Just** recipes are preferred wrappers (`just deploy`, etc.).

**Layout tests:** `just test` or `uv run python -m tools.repo.gcp_layout_policy` / `repo_layout_policy`.

**Pulumi / vars:** `just pulumi`, `just validate` — see [infra/README.md](infra/README.md), [docs/configuration.md](docs/configuration.md).

## CI / BMT CLI

Entrypoint: **`uv run bmt <cmd>`** from repo root; implementation under **`.github/bmt/ci/`** (package installed via `uv pip install -e .`).

Workflows in **`.github/workflows/`** call into this CLI (e.g. **`bmt-handoff.yml`**: `write-context`, `filter-upload-matrix`, `invoke-workflow`, etc.). See **[.github/README.md](.github/README.md)** for workflow layout.

## Linting and type checking

```bash
uv pip install -e .
ruff check .
ruff format --check .
uv run ty check
```

Config: [pyproject.toml](pyproject.toml), [pyrightconfig.json](pyrightconfig.json).

**Path map:** CI → `uv run bmt` / `.github/bmt/ci/`. Bucket tools → `tools/remote/bucket_*.py`. Local BMT → `tools/bmt/`.

## Testing

### Unit tests (no GCS)

```bash
uv run python -m pytest tests/ -v
```

Covers CI models, gate logic, pointer helpers, etc.

### Local BMT batch (no GCS)

Uses **`tools/bmt/bmt_run_local`** — different path from Cloud Run orchestration; useful for runner/scoring. See [CONTRIBUTING.md](CONTRIBUTING.md) and older examples in repo docs.

### Pointer / snapshot flow (real bucket)

To exercise manager-style snapshot writes and **`current.json`** against a real bucket, you can run project managers or orchestration paths **as documented** in [docs/development.md](docs/development.md) and [docs/configuration.md](docs/configuration.md). Full **E2E** (Actions → Workflows → Cloud Run) is validated via CI and [docs/plans/2026-03-22-e2e-ci-validation.md](docs/plans/2026-03-22-e2e-ci-validation.md) when applicable.

## Devtools and pre-commit

- **`just deploy`** (with `GCS_BUCKET`) syncs `gcp/` to the bucket and verifies.
- Pre-commit may **block** commits that touch `gcp/` unless the bucket is in sync (`SKIP_SYNC_VERIFY=1` to bypass intentionally).

```bash
just deploy
# GCS_BUCKET="..." uv run python -m tools.remote.bucket_sync_gcp
```

## Architecture (short)

| Layer | Role |
| ----- | ---- |
| **Actions** | Build, validate, start Workflows, post status/handoff |
| **Workflows** | Plan → parallel Cloud Run tasks → coordinator |
| **Cloud Run** | `gcp/image` runtime: plan / task / coordinator modes |
| **GCS** | Plans, summaries, snapshots, `current.json` |

Runtime code: **`gcp/image/runtime/`**, entry via **`gcp/image/main.py`**. Plugins live under **`gcp/stage/projects/.../plugins/`** (published bundles).

**Details:** [docs/architecture.md](docs/architecture.md), [docs/pipeline-dag.md](docs/pipeline-dag.md), [ARCHITECTURE.md](ARCHITECTURE.md).

## GCP / repo environment

Required variables are documented in **[docs/configuration.md](docs/configuration.md)** (from Pulumi): e.g. `GCS_BUCKET`, `GCP_PROJECT`, `CLOUD_RUN_REGION`, `BMT_CONTROL_JOB`, `BMT_TASK_STANDARD_JOB`, `BMT_TASK_HEAVY_JOB`, `GCP_SA_EMAIL`, WIF provider, GitHub App secrets for reporting. Branch protection should require the configured **BMT status context**.

## Not committed

`data/`, local workspaces (`local_batch/`, etc.), `gcp-key.json`, secrets — see repo `.gitignore` and docs.
