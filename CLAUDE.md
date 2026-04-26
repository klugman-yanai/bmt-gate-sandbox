# CLAUDE.md

Guidance for **Claude Code** (and similar agents) working in **bmt-gcloud**.

## Current Goal

This repo ships the GCP BMT stack: Actions call Workflows, Workflows run Cloud Run jobs, artifacts and results sit in GCS. Plugins and the PEX live here. Copy `plugins/projects/sk/` when you add a project (manifest, scoring policy, batch vs per-case execution in `runtime/kardome_runparams.py`). You change `kardome_runner` in Kardome-org/core-main.

For SK: keep preset numbers in core-main `Runners/params/src/run_params_SK.c`. Write per-case score JSON next to the output WAV so `runtime/kardome_case_metrics.py` can read it without stdout regex. Merge runner work to core-main `dev`. Land infra and workflow edits here via PR to `ci/check-bmt-gate`.

Ship when a klugman-yanai/bmt-gcloud release tags a PEX, publishes the Cloud Run image and release marker, and core-main CI at `~/dev/kardome/core-main` can run handoff and smoke on that drop. Read [docs/README.md](docs/README.md) and [docs/architecture.md](docs/architecture.md).

## Branch Strategy

Three long-lived branches: `main`, `dev`, `ci/check-bmt-gate`.


| PR direction                                            | Pipeline triggers?     |
| ------------------------------------------------------- | ---------------------- |
| `feat/*` / `chore/*` / `bugfix/*` → `ci/check-bmt-gate` | Yes                    |
| `ci/check-bmt-gate` → `dev`                             | Yes (stable milestone) |
| `dev` → `main`                                          | No                     |


New work always branches from and PRs to `ci/check-bmt-gate`.

Open a PR into `ci/check-bmt-gate` to run the full BMT graph (checks, Handoff, cloud workflow, gate) on the PR head SHA. A merge still triggers `push`, so `build-and-test-dev.yml` runs again without a new `pull_request` event. Use a PR when you want review plus that same coverage; do not rely on push alone as your default test path.

## Project overview

Actions uses WIF, uploads when needed, and starts Workflow Executions. Workflows run `bmt-control` plus `bmt-task-standard` / `bmt-task-heavy` (one BMT leg per job). GCS stores plans under `triggers/` and per-project results under `results/` (including `current.json`). The bucket root mirrors `plugins/`.

Older docs describe a VM and vm_watcher. Production is Actions, Workflows, and Cloud Run. Read [docs/architecture.md](docs/architecture.md) for diagrams and the maintainer walkthrough.

The bucket root mirrors `plugins/`. The Cloud Run image bakes in `runtime/`; you sync `plugins/` to match the bucket. See [gcp/README.md](gcp/README.md) and [tools/shared/bucket_env.py](tools/shared/bucket_env.py).

**Docs index:** [docs/README.md](docs/README.md) · **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md)

## Time and clocks


| Need                       | Use                                                                                                                                       |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Wall-clock timestamps, TTL | `whenever.Instant.now()`; `.format_iso(unit="second")` or project `_now_iso()` / [tools/shared/time_utils.py](tools/shared/time_utils.py) |
| Durations, timeouts        | `time.monotonic()`                                                                                                                        |
| Sleep / backoff            | `time.sleep()`                                                                                                                            |


Avoid `time.time()` / `datetime.now()` for new code. CI and `plugins/` may use local helpers to stay self-contained when synced to the bucket.

## `tools/` layout


| Prefix             | Role                                                                                                     |
| ------------------ | -------------------------------------------------------------------------------------------------------- |
| `tools/shared/`    | Libraries (not CLI entrypoints)                                                                          |
| `tools/remote/`    | GCS: sync, upload, verify, validate                                                                      |
| `tools/bmt/`       | Local batch runner, monitor, wait verdicts                                                               |
| `tools/repo/`      | Layout policies, GitHub/repo vars, paths                                                                 |
| `tools/pulumi/`    | Pulumi → GitHub vars                                                                                     |
| `tools/terraform/` | Terraform → GitHub vars                                                                                  |
| `tools/local/`     | Local dev helpers (`mount_remote_data.sh`, etc.)                                                         |
| `tools/scripts/`   | Pre-commit hooks and preflight scripts                                                                   |
| `tools/cli/`       | Typer command modules (`bmt_cmd.py`, `bucket_cmd.py`, `build_cmd.py`, `repo_cmd.py`, `terraform_cmd.py`) |


**CLI:** `uv run python -m tools --help` (Typer). **Just** recipes are preferred wrappers:


| Recipe                                | What it does                                                           |
| ------------------------------------- | ---------------------------------------------------------------------- |
| `just deploy`                         | Sync `gcp/stage` → bucket + verify                                     |
| `just test`                           | Full pre-push suite (pytest, ruff, ty, actionlint, shellcheck, layout) |
| `just upload-data <project> <folder>` | Upload WAV dataset → `projects/<project>/inputs/<dataset>/` + manifest |
| `just ship`                           | Pre-push gate (test → preflight → deploy → image)                      |
| `just image`                          | Docker build + push to Artifact Registry                               |


**Layout tests:** `just test` runs the full pre-push suite: pytest, ruff, `ty check`, actionlint, shellcheck, and both layout policies. Run layout policies standalone: `uv run python -m tools.repo.gcp_layout_policy` / `repo_layout_policy`.

**Pulumi / vars:** `just pulumi`, `just validate`. See [infra/README.md](infra/README.md), [docs/configuration.md](docs/configuration.md).

## CI / BMT CLI

Entrypoint: `**uv run kardome-bmt <cmd>`** from repo root; implementation under `**ci/**` (workspace member `kardome-bmt` is installed by `**uv sync**` at the repo root).

Workflows in `**.github/workflows/**` call into this CLI (e.g. `**bmt-handoff.yml**`: `write-context`, `filter-upload-matrix`, `invoke-workflow`, etc.). See **[.github/README.md](.github/README.md)** for workflow layout.

## Linting and type checking

```bash
uv sync
ruff check .
ruff format --check .
uv run ty check
```

Config: [pyproject.toml](pyproject.toml), [pyrightconfig.json](pyrightconfig.json).

**Lint / types vs. code smell:** Do not “fix” Ruff or `ty` by introducing sustained smell (for example `cast()` only to appease a `Protocol` assignment, or broad `# type: ignore` / `# noqa`). Prefer honest types: a **union of concrete classes** (or an ABC) when several implementations share a call site; structural `Protocol` typing where LSP-compatible; small factories with explicit return types; narrow single-line ignores with a one-line rationale. If the only option seems to be a cast or a blanket ignore, adjust boundaries until types are honest.

**Path map:** CI → `uv run kardome-bmt` / `ci/`. Bucket tools → `tools/remote/bucket_*.py`. Local BMT → `tools/bmt/`.

## Testing

### Unit tests (no GCS)

```bash
uv run python -m pytest tests/ -v
```

Covers CI models, gate logic, pointer helpers, etc.

### Local BMT batch (no GCS)

Local **plan / task / coordinator** parity: `uv run --package bmt-runtime python -m runtime.entrypoint run-local …` (see [docs/developer-workflow.md](docs/developer-workflow.md)). Same runtime code as Cloud Run, without Actions/Workflows.

### SK `kardome_runner` runtime (debug elsewhere)

Keep **PRs into `ci/check-bmt-gate`** as the stable BMT surface. SK runner quirks (tinywav, ONNX,
counters) are isolated in **[docs/kardome_runner_SK_runtime.md](docs/kardome_runner_SK_runtime.md)**:
tuning belongs in **core-main** `Runners/params/src/run_params_SK.c`; this repo’s JSON templates
are **paths + switches**, not a second source of AFE numbers.

### Pointer / snapshot flow (real bucket)

To exercise manager-style snapshot writes and `**current.json`** against a real bucket, you can run project managers or orchestration paths **as documented** in [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/configuration.md](docs/configuration.md). Full **E2E** (Actions → Workflows → Cloud Run) is covered by CI and workflow dispatch on `bmt-handoff.yml`.

## Devtools and pre-commit

- **Install [uv](https://docs.astral.sh/uv/) first**, then `**just setup`**: bootstraps Python 3.12+, **prek** hooks, and prints a Rich setup summary. See [CONTRIBUTING.md](CONTRIBUTING.md).
- `**just deploy`** (with `GCS_BUCKET`) syncs `plugins/` to the bucket and verifies.
- Pre-commit may **block** commits that touch `plugins/` unless the bucket is in sync (`SKIP_SYNC_VERIFY=1` to bypass intentionally).

```bash
just deploy
# GCS_BUCKET="..." uv run python -m tools.remote.bucket_sync_gcp
```

### Shell CLI preferences (agents)

When searching the tree, parsing structured output, or running repo commands, **prefer** these tools if they are on `PATH`. They reduce noise (e.g. obey `.gitignore`), speed up iteration, and match common dev setups. **If a binary is missing** (minimal CI image, container, or fresh VM), use the **fallback** so scripts and instructions stay portable.


| Prefer                                                                                                             | Fallback                                                            | Role                                                                                                                  |
| ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `**rg`** ([ripgrep](https://github.com/BurntSushi/ripgrep))                                                        | `grep` (with appropriate `-r` / excludes)                           | Recursive code and text search                                                                                        |
| `**fd**` ([fd](https://github.com/sharkdp/fd))                                                                     | `find`                                                              | Files by name/path under a tree                                                                                       |
| `**jq**`                                                                                                           | *(same)*                                                            | JSON: filter and project fields in the shell                                                                          |
| `**yq*`* (mikefarah / [go-yq](https://github.com/mikefarah/yq); `yq --version` mentions `github.com/mikefarah/yq`) | `jq` on JSON, or small **Python** in-repo helpers for YAML/TOML     | YAML/JSON/XML in pipelines; **not** the Python [kislyuk/yq](https://github.com/kislyuk/yq) jq-wrapper (different CLI) |
| `**ast-grep`**                                                                                                     | `rg` / `grep`                                                       | Structure-aware search when rules exist                                                                               |
| `**sd**`                                                                                                           | `sed`                                                               | Non-interactive replace (mind `sed` escaping)                                                                         |
| `**uv**`                                                                                                           | `python3 -m venv` + `pip` per [uv docs](https://docs.astral.sh/uv/) | Python env and `uv run`                                                                                               |
| `**just**`                                                                                                         | invoke the underlying `recipe` commands manually                    | Task runner from [Justfile](Justfile)                                                                                 |


(Version numbers omitted; run `<tool> --version` to verify.)

## Architecture (short)


| Layer         | Role                                                  |
| ------------- | ----------------------------------------------------- |
| **Actions**   | Build, validate, start Workflows, post status/handoff |
| **Workflows** | Plan → parallel Cloud Run tasks → coordinator         |
| **Cloud Run** | `runtime` image: plan / task / coordinator modes      |
| **GCS**       | Plans, summaries, snapshots, `current.json`           |


Runtime code: `**runtime/`**, entry via `**runtime.entrypoint**` (Cloud Run / local parity). Plugins live under `**plugins/projects/.../plugins/**` (published bundles).

**Details:** [docs/architecture.md](docs/architecture.md).

## GCP / repo environment

**This repo (bmt-gcloud):** full infra and GitHub variables from Pulumi live in **[docs/configuration.md](docs/configuration.md)** (`GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `CLOUD_RUN_REGION`, Cloud Run job names, `GCP_SA_EMAIL`, `GCP_WIF_PROVIDER`, reporting secrets).

**Cross-repo consumer (e.g. Kardome-org/core-main) calling reusable `bmt-handoff.yml`:** set these four GitHub Actions **Variables** on the consumer repo: `GCS_BUCKET`, `GCP_PROJECT`, `GCP_SA_EMAIL`, `GCP_WIF_PROVIDER`. Pass `cloud_run_region`, `bmt_status_context`, `bmt_pex_repo`, and `force_pass` in the caller workflow job’s `with:` map (repository variables do not cover these). Pin the workflow with `uses: …/bmt-handoff.yml@bmt-handoff` or `@bmt-v*`. Branch protection should require the same **status context** string you pass as `bmt_status_context`.

### core-main reading list (bmt-gcloud)

1. **[.github/README.md](.github/README.md)**. Production handoff job shape, `permissions`, `with:` example, minimal vars.
2. **[docs/configuration.md](docs/configuration.md)**. Variable names, handoff consumer paragraph, env contract tables.
3. `**[.github/workflows/bmt-handoff.yml](.github/workflows/bmt-handoff.yml)`**. Full handoff DAG (`workflow_call` inputs, top-level `env`, jobs).
4. `**[.github/workflows/build-and-test.yml](.github/workflows/build-and-test.yml)**` (or `**build-and-test-dev.yml**`). How **this** repo calls handoff with `with:` after the build job.
5. `**[.github/actions/bmt-prepare-context/action.yml](.github/actions/bmt-prepare-context/action.yml)**`. PEX setup + required-var check + `CMakePresets.json` fetch from caller.
6. `**[.github/actions/setup-bmt-pex/action.yml](.github/actions/setup-bmt-pex/action.yml)**`. How `**bmt.pex**` is resolved from the workflow ref (`bmt-handoff` → latest `bmt-v*`).
7. `**[ci/kardome_bmt/runner.py](ci/kardome_bmt/runner.py)**`. `filter-upload-matrix` / upload vs `skip_in_gcs` (artifact names `**runner-<preset>**`, preseed / skip-publish flags).
8. `**[docs/architecture.md](docs/architecture.md)**`. End-to-end Actions → Workflows → Cloud Run → GCS when you need the big picture.

## Datasets

`inputs/` in `gcp/stage` holds only `.keep` placeholders. WAV datasets stay out of git (30–40 GB). Upload via:

```bash
GCS_BUCKET=train-kws-202311-bmt-gate just upload-data sk /path/to/false_alarms --dataset false_alarms
```

For large files (10–30 GB), use `gcloud storage cp` first then run `just upload-data --force` for manifest regen only.

## Runner metadata

`gcp/stage/projects/sk/runner_latest_meta.json` is a **placeholder** with `null` fields (intentional). It signals that a runner is configured for `sk` so CI skips the publish step and uses the bucket runner. Do not populate it with fake values.

## CI pipeline flags


| Env var                                           | Effect                                                                                                                                                                                                                                                          |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BMT_SKIP_PUBLISH_RUNNERS=1`                      | `**filter-upload-matrix` short-circuit:** emit empty publish matrices; no upload jobs; assumes runners are already in GCS.                                                                                                                                     |
| `BMT_RUNNERS_PRESEEDED_IN_GCS=1`                  | **Per-leg only:** when `runner_meta.json` already exists in GCS, treat bucket as authoritative and classify `**skip_in_gcs`** even if `source_ref` ≠ current `HEAD_SHA` (trust pre-seeded bucket). Unrelated to skip-publish; omit unless you need that escape. |
| Handoff input `force_pass: true` (caller `with:`) | Dispatch runs `kardome-bmt dispatch invoke-workflow --force-pass`. Does not change GCS or cloud BMT verdict. Actions escape hatch only. Ad-hoc: `KARDOME_BMT_FORCE_PASS` env on the PEX.                                                                       |


## Not committed

`data/`, local workspaces (`local_batch/`, etc.), `gcp-key.json`, secrets. See repo `.gitignore` and docs.