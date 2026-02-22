# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**bmt-cloud-dev** is where BMT (Benchmark/Milestone Testing) logic is planned and you interface with the GCP VM/bucket. You author config/scripts here, test locally, and push assets via devtools; the CI workflow in this repo is copied to production manually. It orchestrates remote VM-based BMT execution (e.g. sk) via Google Cloud, scoring audio quality metrics (NAMUH counter values) against a baseline to gate CI.

**Conventions:** The bucket mirror and config root is `remote/`; default jobs config for local runs is `remote/sk/config/bmt_jobs.json`.

## Time and clocks

Use a single, consistent approach for time so timestamps and durations stay correct and comparable:

| Need | Use | Notes |
| ---- | --- | ------ |
| **Wall-clock “now”** (timestamps, TTL, age vs stored time) | `datetime.now(timezone.utc)` | Prefer `.timestamp()` when you need epoch float (e.g. cutoff, cache TTL). Use project helpers (`now_iso()`, `now_stamp()`, `utc_epoch()`) where available. |
| **Durations / elapsed time** (how long something took, timeouts) | `time.monotonic()` | Not comparable to wall-clock or `st_mtime`; use only for deltas. |
| **Sleep / backoff** | `time.sleep()` | For retries and polling intervals. |
| **Non-UTC display or scheduling** | `zoneinfo` (stdlib in 3.9+) | Use when you need a specific timezone; otherwise stick to UTC. |

Avoid `time.time()` for new code; use `datetime.now(timezone.utc).timestamp()` so the timezone is explicit. `devtools/time_utils.py` is used only by the local runner (`devtools/run_sk_bmt_batch.py`); CI and `remote/` use small in-file helpers so they stay self-contained when copied to the bucket.

## Linting and Type Checking

Run from repo root (config in [pyproject.toml](pyproject.toml) excludes `.venv`, `data`, `sk_runtime`, `local_batch`, `secrets`):

```bash
# Install the ci package and its dependencies (required before linting/running)
uv pip install -e .

# Lint (ruff — line length 120, Python 3.10 target)
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
python3 devtools/run_sk_bmt_batch.py \
  --bmt-id false_reject_namuh \
  --jobs-config remote/sk/config/bmt_jobs.json \
  --runner remote/sk/runners/kardome_runner \
  --dataset-root data/sk/inputs/false_rejects \
  --workers 4
```

### Testing the pointer/snapshot flow (with GCS)

To exercise the **manager** (snapshot writes, pointer read for baseline) and optionally the **watcher** (pointer update, cleanup) against a real bucket:

1. **One-off manager run** — Run the VM-side manager locally with a bucket and `run_id`. It will read `current.json` (or bootstrap), write under `snapshots/<run_id>/`, and emit a summary. Requires `gcloud` auth and a bucket with config/runner/dataset already synced.

   ```bash
   # From repo root; workspace can be a local dir
   uv run python remote/sk/bmt_manager.py \
     --bucket "<bucket>" \
     --bucket-prefix "" \
     --project-id sk \
     --bmt-id false_reject_namuh \
     --jobs-config remote/sk/config/bmt_jobs.json \
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
python3 devtools/run_sk_bmt_batch.py \
  --bmt-id false_reject_namuh \
  --jobs-config remote/sk/config/bmt_jobs.json \
  --runner remote/sk/runners/kardome_runner \
  --dataset-root data/sk/inputs/false_rejects \
  --workers 4
```

### Devtools (bucket sync, runner/wav upload, contract validation)

Bucket and prefix are read from `BUCKET` (or `GCS_BUCKET`) and `BMT_BUCKET_PREFIX`; shared helpers live in `devtools/bucket_env.py`. From repo root you can run `just sync-remote` (set BUCKET or GCS_BUCKET) to sync `remote/` to the bucket, and `just show-env` to print the env var names used by CI, VM, and local devtools.

```bash
BUCKET="<bucket>" python3 devtools/sync_remote_to_bucket.py
BUCKET="<bucket>" python3 devtools/upload_runner.py --runner-path <path>
BUCKET="<bucket>" python3 devtools/upload_wavs.py --source-dir <dir>
BUCKET="<bucket>" python3 devtools/validate_bucket_contract.py [--require-runner]
```

### Full reseed (destructive)

```bash
gcloud storage rm --recursive "gs://<bucket>/**"
BUCKET="<bucket>" python3 devtools/sync_remote_to_bucket.py --delete
BUCKET="<bucket>" python3 devtools/upload_runner.py --runner-path <binary>
BUCKET="<bucket>" python3 devtools/upload_wavs.py --source-dir <wav_root>
BUCKET="<bucket>" python3 devtools/validate_bucket_contract.py --require-runner
```

## Architecture

### CI Pipeline (trigger-and-stop — `.github/workflows/ci.yml`)

The workflow uses **uv-managed Python**: `astral-sh/setup-uv`, then `uv sync` and `uv run python ... ci_driver.py`. The VM runs the watcher with `uv run python remote/vm_watcher.py` from the repo root (same uv-managed venv).

The workflow has two jobs; it does not block for the full BMT run. All CI logic is in **`.github/scripts/ci_driver.py`**:

| Stage | Job name | Command |
| ----- | -------- | ------- |
| 01 | Discover Matrix | `ci_driver.py matrix --config-root remote` |
| 02 | Trigger | `ci_driver.py trigger` (writes **one** run trigger to GCS), **starts the BMT VM**, then posts "pending" commit status; workflow ends |

**Stage 02** writes one run trigger to GCS (`triggers/runs/<workflow_run_id>.json`) containing all legs plus repository and sha, then starts the VM. The VM boots, runs its startup script (deps, Secret Manager, watcher with `--exit-after-run`), polls GCS for the trigger, runs `root_orchestrator.py` for each leg, aggregates verdicts, posts commit status (success/failure) to GitHub, then **stops itself**. The next PR or push to dev starts the VM again. Branch protection requires the "BMT Gate" status to pass. The `wait` and `gate` subcommands remain available for local or manual use but are not used by the workflow.

### CI Package (`.github/scripts/ci/`)

Python package co-located with `ci_driver.py` at `.github/scripts/`. `ci_driver.py` is a thin `click` group that registers commands from this package.

| File | Purpose |
| ---- | ------- |
| `ci/models.py` | All constants (status, trigger, decision, reason codes), URI helpers, decision functions, and data models (`CloudVerdict`, `LegOutcome`, `AggregateRow`) |
| `ci/config.py` | Loads `bmt_projects.json` + jobs config; builds matrix; resolves `results_prefix` |
| `ci/adapters/gcloud_cli.py` | All `gcloud`/`subprocess` calls and GCS (e.g. `run_capture_retry` for upload/download/list) |
| `ci/commands/job_matrix.py` | `matrix` subcommand |
| `ci/commands/run_trigger.py` | `trigger` subcommand — writes one run trigger to GCS (all legs; VM reports status to GitHub) |
| `ci/commands/start_vm.py` | `start-vm` subcommand — starts the BMT VM (GCP_SA_EMAIL, GCP_ZONE, BMT_VM_NAME from env; project derived from SA email) |
| `ci/commands/wait_verdicts.py` | `wait` subcommand — polls GCS for verdicts, aggregates (for manual/local use; not used by workflow) |
| `ci/commands/verdict_gate.py` | `gate` subcommand — enforces final pass/fail |

### VM-side Execution (`remote/`)

The `remote/` directory mirrors the GCS bucket structure exactly (`gs://<bucket>/`). On the VM:

- **vm_watcher.py** — Polls GCS for run triggers (or pulls Pub/Sub). For each trigger: posts pending status, runs `root_orchestrator.py` once per leg, reads verdicts from manager summaries (in-memory), updates each leg's `current.json` pointer and cleans up stale snapshots, posts final commit status, deletes trigger. Optionally exits after one run (`--exit-after-run`) so the VM can stop.
- **root_orchestrator.py** — Per leg: downloads `bmt_projects.json`, jobs config, and the project’s manager script from the bucket; invokes the manager with bucket, project, bmt_id, run_id, run_context; writes root summary to GCS.
- **Per-project managers** — Each project has its own **bmt_manager.py** under its folder (e.g. `sk/bmt_manager.py`, `other_project/bmt_manager.py`). They load BMT job config, cache runner/template/dataset from GCS, run the runner binary per WAV in a thread pool, parse scores, evaluate gate, and write all outputs under `{results_prefix}/snapshots/{run_id}/` (latest.json, ci_verdict.json, logs). Baseline for the gate is read by resolving the `current.json` pointer to the last-passing snapshot.

See **ARCHITECTURE.md** for the full client-side and VM-side script reference.

### Config Files

- **`remote/bmt_projects.json`** — project registry; maps project name → `manager_script` (e.g. `sk/bmt_manager.py`) + `jobs_config`.
- **`remote/sk/config/bmt_jobs.json`** — BMT definitions: runner URI, template URI, dataset paths, gate comparison, score parsing regex, caching TTLs.
- **`remote/sk/config/input_template.json`** — runner JSON config template with path placeholders (`/tmp/dummy/*`) for REF_PATH, MICS_PATH, output path, and all audio processing parameters.

### GCS result layout (pointer-based)

Each (project, bmt_id) has a **canonical pointer** at `{results_prefix}/current.json`. The manager never writes to the pointer; it writes all outputs under `{results_prefix}/snapshots/{run_id}/` (latest.json, ci_verdict.json, logs). After all legs complete, the watcher updates `current.json` (latest + last_passing run_ids) and deletes snapshots not referenced by the pointer. The gate reads baseline by resolving the pointer to the last-passing snapshot.

**Check Run and PR comment** implementations must run **after** the watcher updates `current.json` (after all legs complete). They must read result data from the pointer-resolved snapshot path or from in-memory aggregation; they must not assume any file exists at the bare `results_prefix/` root other than `current.json`.

### Key Result Paths

- **`{results_prefix}/current.json`** — pointer (latest run_id, last_passing run_id, updated_at). The only canonical file at the results root.
- **`{results_prefix}/snapshots/<run_id>/latest.json`** — full BMT outcome for that run.
- **`{results_prefix}/snapshots/<run_id>/ci_verdict.json`** — CI verdict for that run (source of truth for the gate).
- **`{results_prefix}/snapshots/<run_id>/logs/`** — logs for that run.

### Not Committed

- `data/` — WAV datasets
- `sk_runtime/` / `local_batch/` — local execution workspaces
- `gcp-key.json` — GCP credentials
- `remote/sk/runners/lib/` runner dependency shared libraries (present locally but `.gitignore`'d in practice)

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
| `GCP_SA_EMAIL` | Service account email (GCP project for start-vm is derived from this) |
| `GCP_ZONE` | VM zone (e.g. `europe-west4-a`) |
| `BMT_VM_NAME` | VM instance name (workflow starts it; VM stops itself after one run) |

**Optional** (leave unset for defaults): `GCP_PROJECT` (derived from `GCP_SA_EMAIL`), `BMT_BUCKET_PREFIX` (empty), `BMT_PROJECTS` (empty = all). **Status (repo-specific):** `BMT_STATUS_CONTEXT` (default `BMT Gate`; must match branch protection), `BMT_DESCRIPTION_PENDING` (default: "BMT running on VM; status will update when complete."). Optional `BMT_DESCRIPTION_SUCCESS` / `BMT_DESCRIPTION_FAILURE` for VM payload.

For **local** use (e.g. `remote/bootstrap/audit_vm_and_bucket.sh`, `ssh_install.sh`), use the same vars or rely on `gcloud config` for project/zone.

### VM-side (for trigger-and-stop gating)

| Variable | Purpose |
| -------- | ------- |
| `GITHUB_STATUS_TOKEN` | PAT or token with `repo:status` (or GitHub App installation token). Used by `vm_watcher.py` to post commit status. Set per repo (e.g. test app token in test repo). |

**Branch protection:** Require the status check named by `BMT_STATUS_CONTEXT` to pass before merge.
