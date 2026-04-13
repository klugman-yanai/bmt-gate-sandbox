# CLAUDE.md

Guidance for **Claude Code** (and similar agents) working in **bmt-gcloud**.

## Current Goal

Fully stable end-to-end pipeline: test and build the pipeline, build the **PEX binary**, publish it to **klugman-yanai/bmt-gcloud** GitHub Releases (tag-based), then run a **live test** from **Kardome-org/core-main** (local: `~/dev/kardome/core-main`) where core-main's CI downloads the PEX via a GitHub Action.

## Branch Strategy

Three long-lived branches: `main`, `dev`, `ci/check-bmt-gate`.

| PR direction | Pipeline triggers? |
|---|---|
| `feat/*` / `chore/*` / `bugfix/*` → `ci/check-bmt-gate` | Yes |
| `ci/check-bmt-gate` → `dev` | Yes (stable milestone) |
| `dev` → `main` | No |

New work always branches from and PRs to `ci/check-bmt-gate`.

## Project overview

**bmt-gcloud** provides a **realistic path to test production BMT CI** against **real GCS** (and GCP), not mocks. The supported execution model is:

- **GitHub Actions** authenticates with **WIF**, uploads artifacts as needed, and **starts Google Workflows** via the Workflow Executions API.
- **Google Workflows** runs **Cloud Run** jobs: `bmt-control` (plan + coordinator) and `bmt-task-standard` / `bmt-task-heavy` (one BMT leg per task).
- **GCS** holds frozen plans under `triggers/`, snapshots and `current.json` under each project’s `results/` tree. The bucket layout mirrors **`gcp/stage`**.

Legacy **VM + vm_watcher** descriptions in old docs are **not** the current production story. Use **[docs/architecture.md](docs/architecture.md)** for the full pipeline, diagrams, and maintainer deep dive.

**Bucket:** 1:1 mirror of `gcp/stage` at the bucket root (see [gcp/README.md](gcp/README.md), [tools/shared/bucket_env.py](tools/shared/bucket_env.py)). **`gcp/image`** is baked into the **Cloud Run** image; **`gcp/stage`** is the editable mirror of runtime/config content.

**Docs index:** [docs/README.md](docs/README.md) · **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md)

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
| `tools/terraform/` | Terraform → GitHub vars |
| `tools/local/` | Local dev helpers (`mount_remote_data.sh`, etc.) |
| `tools/scripts/` | Pre-commit hooks and preflight scripts |
| `tools/cli/` | Typer command modules (`bmt_cmd.py`, `bucket_cmd.py`, `build_cmd.py`, `repo_cmd.py`, `terraform_cmd.py`) |

**CLI:** `uv run python -m tools --help` (Typer). **Just** recipes are preferred wrappers:

| Recipe | What it does |
| ------ | ------------ |
| `just deploy` | Sync `gcp/stage` → bucket + verify |
| `just test` | Full pre-push suite (pytest, ruff, ty, actionlint, shellcheck, layout) |
| `just upload-data <project> <folder>` | Upload WAV dataset → `projects/<project>/inputs/<dataset>/` + manifest |
| `just ship` | Pre-push gate (test → preflight → deploy → image) |
| `just image` | Docker build + push to Artifact Registry |

**Layout tests:** `just test` runs the full pre-push suite: pytest, ruff, `ty check`, actionlint, shellcheck, and both layout policies. Run layout policies standalone: `uv run python -m tools.repo.gcp_layout_policy` / `repo_layout_policy`.

**Pulumi / vars:** `just pulumi`, `just validate` — see [infra/README.md](infra/README.md), [docs/configuration.md](docs/configuration.md).

## CI / BMT CLI

Entrypoint: **`uv run bmt <cmd>`** from repo root; implementation under **`.github/bmt/ci/`** (workspace member `bmt` is installed by **`uv sync`** at the repo root).

Workflows in **`.github/workflows/`** call into this CLI (e.g. **`bmt-handoff.yml`**: `write-context`, `filter-upload-matrix`, `invoke-workflow`, etc.). See **[.github/README.md](.github/README.md)** for workflow layout.

## Linting and type checking

```bash
uv sync
ruff check .
ruff format --check .
uv run ty check
```

Config: [pyproject.toml](pyproject.toml), [pyrightconfig.json](pyrightconfig.json).

**Lint / types vs. code smell:** Do not “fix” Ruff or `ty` by introducing sustained smell (for example `cast()` only to appease a `Protocol` assignment, or broad `# type: ignore` / `# noqa`). Prefer honest types: a **union of concrete classes** (or an ABC) when several implementations share a call site; structural `Protocol` typing where LSP-compatible; small factories with explicit return types; narrow single-line ignores with a one-line rationale. If the only option seems to be a cast or a blanket ignore, adjust boundaries until types are honest.

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

To exercise manager-style snapshot writes and **`current.json`** against a real bucket, you can run project managers or orchestration paths **as documented** in [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/configuration.md](docs/configuration.md). Full **E2E** (Actions → Workflows → Cloud Run) is covered by CI and workflow dispatch on `bmt-handoff.yml`.

## Devtools and pre-commit

- **Install [uv](https://docs.astral.sh/uv/) first**, then **`just setup`**: bootstraps Python 3.12+, **prek** hooks, and prints a Rich setup summary. See [CONTRIBUTING.md](CONTRIBUTING.md).
- **`just deploy`** (with `GCS_BUCKET`) syncs `gcp/` to the bucket and verifies.
- Pre-commit may **block** commits that touch `gcp/` unless the bucket is in sync (`SKIP_SYNC_VERIFY=1` to bypass intentionally).

```bash
just deploy
# GCS_BUCKET="..." uv run python -m tools.remote.bucket_sync_gcp
```

### Shell CLI preferences (agents)

When searching the tree, parsing structured output, or running repo commands, **prefer** these tools if they are on `PATH`. They reduce noise (e.g. obey `.gitignore`), speed up iteration, and match common dev setups. **If a binary is missing** (minimal CI image, container, or fresh VM), use the **fallback** so scripts and instructions stay portable.

| Prefer | Fallback | Role |
| ------ | -------- | ---- |
| **`rg`** ([ripgrep](https://github.com/BurntSushi/ripgrep)) | `grep` (with appropriate `-r` / excludes) | Recursive code and text search |
| **`fd`** ([fd](https://github.com/sharkdp/fd)) | `find` | Files by name/path under a tree |
| **`jq`** | _(same)_ | JSON: filter and project fields in the shell |
| **`yq`** (mikefarah / [go-yq](https://github.com/mikefarah/yq); `yq --version` mentions `github.com/mikefarah/yq`) | `jq` on JSON, or small **Python** in-repo helpers for YAML/TOML | YAML/JSON/XML in pipelines; **not** the Python [kislyuk/yq](https://github.com/kislyuk/yq) jq-wrapper (different CLI) |
| **`ast-grep`** | `rg` / `grep` | Structure-aware search when rules exist |
| **`sd`** | `sed` | Non-interactive replace (mind `sed` escaping) |
| **`uv`** | `python3 -m venv` + `pip` per [uv docs](https://docs.astral.sh/uv/) | Python env and `uv run` |
| **`just`** | invoke the underlying `recipe` commands manually | Task runner from [Justfile](Justfile) |

(Version numbers omitted — run `<tool> --version` to verify.)

## Architecture (short)

| Layer | Role |
| ----- | ---- |
| **Actions** | Build, validate, start Workflows, post status/handoff |
| **Workflows** | Plan → parallel Cloud Run tasks → coordinator |
| **Cloud Run** | `gcp/image` runtime: plan / task / coordinator modes |
| **GCS** | Plans, summaries, snapshots, `current.json` |

Runtime code: **`gcp/image/runtime/`**, entry via **`gcp/image/main.py`**. Plugins live under **`gcp/stage/projects/.../plugins/`** (published bundles).

**Details:** [docs/architecture.md](docs/architecture.md).

## GCP / repo environment

Required variables are documented in **[docs/configuration.md](docs/configuration.md)** (from Pulumi): e.g. `GCS_BUCKET`, `GCP_PROJECT`, `CLOUD_RUN_REGION`, `BMT_CONTROL_JOB`, `BMT_TASK_STANDARD_JOB`, `BMT_TASK_HEAVY_JOB`, `GCP_SA_EMAIL`, WIF provider, GitHub App secrets for reporting. Branch protection should require the configured **BMT status context**.

## Datasets

`inputs/` in `gcp/stage` holds only `.keep` placeholder files — WAV datasets are **not committed** (30–40 GB). Upload via:

```bash
GCS_BUCKET=train-kws-202311-bmt-gate just upload-data sk /path/to/false_alarms --dataset false_alarms
```

For large files (10–30 GB), use `gcloud storage cp` first then run `just upload-data --force` for manifest regen only.

## Runner metadata

`gcp/stage/projects/sk/runner_latest_meta.json` is a **placeholder** with `null` fields — intentional. It signals that a runner is configured for `sk` so CI skips the publish step and uses the bucket runner. Do not populate it with fake values.

## CI pipeline flags

| Env var | Effect |
| ------- | ------ |
| `BMT_SKIP_PUBLISH_RUNNERS=1` | Skip all runner publish jobs; assume runners already in bucket |
| `BMT_RUNNERS_PRESEEDED_IN_GCS=1` | Same but per-project; write upload markers without artifact check |

## Not committed

`data/`, local workspaces (`local_batch/`, etc.), `gcp-key.json`, secrets — see repo `.gitignore` and docs.
