# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**bmt-cloud-dev** is where BMT (Benchmark/Milestone Testing) logic is planned and you interface with the GCP VM/bucket. You author config/scripts here, test locally, and push assets via devtools; the CI workflow in this repo is copied to production manually. It orchestrates remote VM-based BMT execution (e.g. sk) via Google Cloud, scoring audio quality metrics (NAMUH counter values) against a baseline to gate CI.

**Conventions:** `remote/` is the source of truth for deployable VM code/config/templates and syncs manually to bucket `code/`; runtime artifacts live under bucket `runtime/`. Default jobs config for local runs is `remote/code/sk/config/bmt_jobs.json`.

## Time and clocks

Use a single, consistent approach for time so timestamps and durations stay correct and comparable:

| Need | Use | Notes |
| ---- | --- | ------ |
| **Wall-clock “now”** (timestamps, TTL, age vs stored time) | `datetime.now(timezone.utc)` | Prefer `.timestamp()` when you need epoch float (e.g. cutoff, cache TTL). Use project helpers (`now_iso()`, `now_stamp()`, `utc_epoch()`) where available. |
| **Durations / elapsed time** (how long something took, timeouts) | `time.monotonic()` | Not comparable to wall-clock or `st_mtime`; use only for deltas. |
| **Sleep / backoff** | `time.sleep()` | For retries and polling intervals. |
| **Non-UTC display or scheduling** | `zoneinfo` (stdlib in 3.9+) | Use when you need a specific timezone; otherwise stick to UTC. |

Avoid `time.time()` for new code; use `datetime.now(timezone.utc).timestamp()` so the timezone is explicit. `devtools/shared_time_utils.py` is used only by the local runner (`devtools/bmt_run_local.py`); CI and `remote/` use small in-file helpers so they stay self-contained when copied to the bucket.

## devtools Structure

Scripts organized by category prefix:

| Prefix | Category | Description |
| ------ | -------- | ----------- |
| `shared_*` | Shared libraries | Not executed directly; imported by other scripts |
| `bucket_*` | GCS operations | Sync, upload, validate bucket contents |
| `bmt_*` | BMT execution | Local batch runner, live monitor |
| `gh_*` | GitHub/debug | Env inspection, app permissions |

**Files:**
- `shared_bucket_env.py` — Bucket URI helpers, click options for `--bucket`/`--bucket-prefix`
- `shared_time_utils.py` — UTC timestamp helpers (`now_iso`, `now_stamp`, `utc_epoch`)
- `bucket_sync_remote.py` — Sync `remote/` to GCS
- `bucket_upload_runner.py` — Upload runner binary with rotation
- `bucket_upload_wavs.py` — Upload wav datasets
- `bucket_validate_contract.py` — Validate required bucket objects
- `bmt_run_local.py` — Local batch runner (no GCS/VM)
- `bmt_monitor.py` — Live TUI dashboard for workflow/VM/GCS status
- `gh_show_env.py` — Show env vars used by CI, VM, and devtools
- `gh_app_perms.py` — Fetch GitHub App permissions via JWT

All scripts use `click` for CLI parsing. Run `just` to see available recipes.

## Linting and Type Checking

Run from repo root (config in [pyproject.toml](pyproject.toml) excludes `.venv`, `data`, `bmt_workspace`, `sk_runtime`, `local_batch`, `secrets`):

```bash
# Install the ci package and its dependencies (required before linting/running)
uv pip install -e .

# Lint (ruff — line length 120, Python 3.12 target)
ruff check .

# Format check
ruff format --check .

# Type check (basedpyright — covers whole repo: .github/scripts, remote/, devtools/)
basedpyright
```

## Testing

### Unit tests (no GCS or VM)

From the repo root (with `uv pip install -e .` so the package is available):

```bash
uv run python -m pytest tests/ -v
```

These cover: pointer resolution and path construction in the manager (`tests/sk/test_bmt_manager_pointer.py`), VM watcher helpers (`tests/test_vm_watcher_pointer.py`), CI models and gate logic (`tests/test_ci_models.py`, `tests/test_gate.py`, `tests/test_counter_regex.py`). No bucket or VM required.

### Local BMT batch (no GCS)

Runs the **local** batch runner (different code path from the VM manager); useful for runner/config/score logic only:

```bash
python3 devtools/bmt_run_local.py \
  --bmt-id false_reject_namuh \
  --jobs-config remote/code/sk/config/bmt_jobs.json \
  --runner remote/runtime/sk/runners/kardome_runner \
  --dataset-root data/sk/inputs/false_rejects \
  --workers 4
```

### Testing the pointer/snapshot flow (with GCS)

To exercise the **manager** (snapshot writes, pointer read for baseline) and optionally the **watcher** (pointer update, cleanup) against a real bucket:

1. **One-off manager run** — Run the VM-side manager locally with a bucket and `run_id`. It will read `current.json` (or bootstrap), write under `snapshots/<run_id>/`, and emit a summary. Requires `gcloud` auth and a bucket with config/runner/dataset already synced.

   ```bash
   # From repo root; workspace can be a local dir
   uv run python remote/code/sk/bmt_manager.py \
     --bucket "<bucket>" \
     --bucket-prefix "" \
     --project-id sk \
     --bmt-id false_reject_namuh \
     --jobs-config remote/code/sk/config/bmt_jobs.json \
     --workspace-root ./local_batch \
     --run-context dev \
     --run-id test-run-$(date +%s) \
     --summary-out ./local_batch/manager_summary.json
   ```

   Then inspect GCS: `gs://<bucket>/<results_prefix>/snapshots/<run_id>/` should contain `latest.json`, `ci_verdict.json`, and `logs/`. If you had written a `current.json` beforehand, the manager uses it for baseline.

2. **Full E2E (trigger → VM → pointer)** — Run the real CI workflow (e.g. push to a branch or trigger manually). The workflow writes a run trigger; the VM (or a local process running `vm_watcher.py` with the same bucket and a local workspace) picks it up, runs the orchestrator per leg, then updates `current.json` and cleans snapshots. Verify in GCS: `current.json` at `results_prefix`, and only the latest/last-passing snapshot dirs under `snapshots/`.

3. **Wait command (pointer-based polling)** — With a trigger that has already been processed by the VM, the `wait` subcommand can be used to confirm it reads from the pointer and snapshot verdict path:

   ```bash
   uv run python .github/scripts/ci_driver.py wait \
     --manifest '<json with legs: project, bmt_id, run_id, triggered_at>' \
     --config-root remote \
     --bucket "<bucket>" \
     --timeout-sec 60
   ```

   It resolves `results_prefix` from config, reads `current.json`, and when `latest` matches the leg’s `run_id`, downloads `snapshots/<run_id>/ci_verdict.json`.

## Local Development

### Run a local BMT batch (config-driven, no cloud VM needed)

```bash
python3 devtools/bmt_run_local.py \
  --bmt-id false_reject_namuh \
  --jobs-config remote/code/sk/config/bmt_jobs.json \
  --runner remote/runtime/sk/runners/kardome_runner \
  --dataset-root data/sk/inputs/false_rejects \
  --workers 4
```

### Devtools (bucket sync, runner/wav upload, contract validation)

Bucket and prefix are read from canonical `GCS_BUCKET` and `BMT_BUCKET_PREFIX`; shared helpers live in `devtools/shared_bucket_env.py`. From repo root use `just sync-remote && just verify-sync` (with `GCS_BUCKET`) to update code root manually, and `just show-env` to print the env var names used by CI, VM, and local devtools.

**Pre-commit assist:** The prod workflow does not sync `remote/` to GCS. `.pre-commit-config.yaml` provides an advisory (non-blocking) `remote/` sync helper.

```bash
GCS_BUCKET="<bucket>" python3 devtools/bucket_sync_remote.py
GCS_BUCKET="<bucket>" python3 devtools/bucket_upload_runner.py --runner-path <path>
GCS_BUCKET="<bucket>" python3 devtools/bucket_upload_wavs.py --source-dir <dir>
GCS_BUCKET="<bucket>" python3 devtools/bucket_validate_contract.py [--require-runner]
```

### Full reseed (destructive)

```bash
gcloud storage rm --recursive "gs://<bucket>/**"
GCS_BUCKET="<bucket>" python3 devtools/bucket_sync_remote.py --delete
GCS_BUCKET="<bucket>" python3 devtools/bucket_upload_runner.py --runner-path <binary>
GCS_BUCKET="<bucket>" python3 devtools/bucket_upload_wavs.py --source-dir <wav_root>
GCS_BUCKET="<bucket>" python3 devtools/bucket_validate_contract.py --require-runner
```

## Architecture

### CI Pipeline (trigger-and-stop — `.github/workflows/ci.yml`)

The workflow uses **uv-managed Python**: `astral-sh/setup-uv`, then `uv sync` and `uv run python ... ci_driver.py`. The VM runs the watcher with `uv run python remote/vm_watcher.py` from the repo root (same uv-managed venv).

The workflow has two jobs; it does not block for the full BMT run. All CI logic is in **`.github/scripts/ci_driver.py`**:

| Stage | Job name | Command |
| ----- | -------- | ------- |
| 01 | Discover Matrix | `ci_driver.py matrix --config-root remote` |
| 02 | Trigger | `ci_driver.py trigger` (writes **one** run trigger to GCS), **starts the BMT VM**, then posts "pending" commit status; workflow ends |

**Stage 02** writes one run trigger to `runtime/triggers/runs/<workflow_run_id>.json` containing all legs plus repository and sha, then starts the VM. The VM boots, syncs `code/` via startup wrapper, polls runtime triggers, runs `root_orchestrator.py` for each leg, aggregates verdicts, posts commit status (success/failure) to GitHub, then **stops itself**. The next PR or push to dev starts the VM again. Branch protection requires the "BMT Gate" status to pass. The `wait` and `gate` subcommands remain available for local or manual use but are not used by the workflow.

### CI Package (`.github/scripts/ci/`)

Python package co-located with `ci_driver.py` at `.github/scripts/`. `ci_driver.py` is a thin `click` group that registers commands from this package.

| File | Purpose |
| ---- | ------- |
| `ci/models.py` | Constants (status, trigger, decision, reason codes), URI helpers, decision functions; **dataclasses** for verdicts/legs: `CloudVerdict`, `LegOutcome`, `AggregateRow`, `TriggerLeg`, `RunnerIdentity` (no Pydantic) |
| `ci/config.py` | Loads `bmt_projects.json` + jobs config; builds matrix; resolves `results_prefix` |
| `ci/adapters/gcloud_cli.py` | All GCP interaction via **subprocess** and **gcloud** CLI (upload/download/list, VM start); no Google Cloud SDK |
| `ci/commands/job_matrix.py` | `matrix` subcommand |
| `ci/commands/run_trigger.py` | `trigger` — writes one run trigger to runtime namespace (all legs; VM reports status to GitHub) |
| `ci/commands/sync_vm_metadata.py` | `sync-vm-metadata` — pushes bucket/prefix from workflow to VM metadata |
| `ci/commands/start_vm.py` | `start-vm` — starts the BMT VM (requires `GCP_PROJECT`, `GCP_ZONE`, `BMT_VM_NAME`) |
| `ci/commands/wait_handshake.py` | `wait-handshake` — waits for VM ack at `runtime/triggers/acks/<workflow_run_id>.json` |
| `ci/commands/upload_runner.py` | `upload-runner` — uploads runner artifacts to GCS |
| `ci/commands/wait_verdicts.py` | `wait` — polls GCS for verdicts, aggregates (manual/local only; not used by workflow) |
| `ci/commands/verdict_gate.py` | `gate` — enforces final pass/fail (manual/local only) |

### VM-side Execution (`remote/`)

The `remote/` directory mirrors the bucket `code/` namespace. On the VM:

- **vm_watcher.py** — Polls GCS for run triggers. For each trigger: posts pending commit status, creates/updates a **GitHub Check Run** (implemented), runs `root_orchestrator.py` once per leg, reads verdicts from manager summaries (in-memory), updates each leg's `current.json` pointer and cleans stale snapshots, posts final commit status, completes the Check Run, deletes trigger. Optionally exits after one run (`--exit-after-run`) so the VM can stop. **PR comments are not implemented.**
- **root_orchestrator.py** — Per leg: downloads `bmt_projects.json`, jobs config, and the project’s manager script from the bucket; invokes the manager with bucket, project, bmt_id, run_id, run_context; writes root summary to GCS.
- **Per-project managers** — Each project has its own **bmt_manager.py** (e.g. `sk/bmt_manager.py`). They load BMT job config (dict/JSON), cache runner/template/dataset from GCS via `gcloud` CLI, run the runner binary per WAV in a thread pool, parse scores, evaluate gate, and write outputs under `{results_prefix}/snapshots/{run_id}/` (latest.json, ci_verdict.json, logs). Baseline is read by resolving `current.json` to the last-passing snapshot.
- **remote/lib/** — Shared VM-side code only: `github_auth.py` (GitHub App JWT + installation token, PAT fallback), `github_checks.py` (Check Run create/update), `status_file.py`. No `bmt_lib/` or `github_api.py` in the current implementation.

See **docs/architecture.md** for the full script reference; **docs/implementation.md** for current data flow and limitations. Planned changes (SDK, Pydantic, bmt_lib, PR comments): **docs/plans/future-architecture.md**.

### Config Files

- **`remote/bmt_projects.json`** — project registry; maps project name → `manager_script` (e.g. `sk/bmt_manager.py`) + `jobs_config`.
- **`remote/code/sk/config/bmt_jobs.json`** — BMT definitions: runner URI, template URI, dataset paths, gate comparison, score parsing regex, caching TTLs.
- **`remote/code/sk/config/input_template.json`** — runner JSON config template with path placeholders (`/tmp/dummy/*`) for REF_PATH, MICS_PATH, output path, and all audio processing parameters.

### GCS result layout (pointer-based)

Each (project, bmt_id) has a **canonical pointer** at `{results_prefix}/current.json`. The manager never writes to the pointer; it writes all outputs under `{results_prefix}/snapshots/{run_id}/` (latest.json, ci_verdict.json, logs). After all legs complete, the watcher updates `current.json` (latest + last_passing run_ids) and deletes snapshots not referenced by the pointer. The gate reads baseline by resolving the pointer to the last-passing snapshot.

The **Check Run** is implemented and runs after the watcher updates `current.json` (after all legs complete); it reads from in-memory aggregation. PR comments are **not** implemented. Commit status and Check Run must not assume any file exists at the bare `results_prefix/` root other than `current.json`. Every outcome must produce a clear commit status and Check Run; see `docs/communication-flow.md`.

### Key Result Paths

- **`{results_prefix}/current.json`** — pointer (latest run_id, last_passing run_id, updated_at). The only canonical file at the results root.
- **`{results_prefix}/snapshots/<run_id>/latest.json`** — full BMT outcome for that run.
- **`{results_prefix}/snapshots/<run_id>/ci_verdict.json`** — CI verdict for that run (source of truth for the gate).
- **`{results_prefix}/snapshots/<run_id>/logs/`** — logs for that run.

### Not Committed

- `data/` — WAV datasets
- `sk_runtime/` / `local_batch/` — local execution workspaces
- `gcp-key.json` — GCP credentials
- `.local/diagnostics/` — local diagnostics snapshots and ad-hoc incident artifacts

## GCP Environment Variables (CI)

Configure via **GitHub repository or organization variables** (Settings → Secrets and variables → Actions → Variables), or with `gh`:

```bash
gh variable set GCS_BUCKET "<bucket>"
gh variable set GCP_WIF_PROVIDER "<wif-provider>"
gh variable set GCP_SA_EMAIL "<sa-email>"
gh variable set GCP_ZONE "<zone>"
gh variable set BMT_VM_NAME "<vm-name>"
# Optional (test repo / overrides):
gh variable set BMT_STATUS_CONTEXT "BMT Gate (test)"
gh variable set BMT_DESCRIPTION_PENDING "BMT running (test)..."
```

| Variable | Purpose |
| -------- | ------- |
| `GCS_BUCKET` | GCS bucket name |
| `GCP_WIF_PROVIDER` | Workload Identity Federation provider |
| `GCP_SA_EMAIL` | Service account email for WIF auth |
| `GCP_PROJECT` | GCP project ID for VM operations |
| `GCP_ZONE` | VM zone (e.g. `europe-west4-a`) |
| `BMT_VM_NAME` | VM instance name (workflow starts it; VM stops itself after one run) |

**Optional** (leave unset for defaults): `BMT_BUCKET_PREFIX` (empty), `BMT_PROJECTS` (`all release runners`). **Status (repo-specific):** `BMT_STATUS_CONTEXT` (default `BMT Gate`; must match branch protection), `BMT_DESCRIPTION_PENDING` (default: "BMT running on VM; status will update when complete.").

For **local** use (e.g. `remote/code/bootstrap/audit_vm_and_bucket.sh`, `ssh_install.sh`), set the same canonical vars explicitly (`GCP_PROJECT`, `GCP_ZONE`, `BMT_VM_NAME`, `GCS_BUCKET`).

### CI workflow (trigger BMT from CI)

| Secret | Purpose |
| ------ | ------- |
| `GH_WORKFLOW_DISPATCH_TOKEN` | PAT with **Actions: read and write**. Used by the CI workflow to trigger the BMT workflow via `workflow_dispatch` (default `GITHUB_TOKEN` cannot trigger other workflows). Add in Settings → Secrets and variables → Actions → Secrets. |

### VM-side (for trigger-and-stop gating)

| Variable | Purpose |
| -------- | ------- |
| `GITHUB_STATUS_TOKEN` | PAT or token with `repo:status` (or GitHub App installation token). Used by `vm_watcher.py` to post commit status. Set per repo (e.g. test app token in test repo). |

**Branch protection:** Require the status check named by `BMT_STATUS_CONTEXT` to pass before merge.
