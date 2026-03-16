# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**bmt-gcloud** (this repo) exists to give you a **reliable way to test production CI locally using the real VM and GCS** — no mocks. That is the main purpose. Everything in the repo supports it:

- **Mirror `gcp/`** — Local mirror of the bucket namespace (code + runtime seed). Sync/pull from GCS so you develop against the same layout the VM uses; see `gcp/README.md`.
- **Test suite** — Unit and integration tests for BMT logic, gate, pointer/snapshot flow, and CI commands. Use real VM/GCS when you need to validate the full production path.
- **Dev QoL** — Devtools (bucket sync, upload, validate, local BMT, monitor), Just recipes, repo-vars and VM helpers for managing BMTs and debugging handoff.

You author config/scripts here, test locally against real infra, and push assets via devtools; the CI workflow in this repo is copied to production manually. It orchestrates remote VM-based BMT execution (e.g. sk) via Google Cloud, scoring audio quality metrics (NAMUH counter values) against a baseline to gate CI.

**Bucket layout:** The bucket (or the mounted prefix) is a **1:1 mirror of `gcp/stage`** (see `gcp/README.md`, `tools/shared/bucket_env.py`). Paths under that root follow the same structure as `gcp/stage` (e.g. `config/`, `triggers/`, `projects/<name>/...`). Current deployment may still use `code/` and `runtime/` prefixes in the bucket (gcp/image → code/, gcp/stage → runtime/); target layout is bucket root = gcp/stage, no code in GCS (code is baked in the image).

**Conventions:** `gcp/image` is the source of truth for deployable VM/image code and config; it is **baked into the image** (not uploaded to the bucket in the target layout). `gcp/stage` is the local mirror of bucket content. Default jobs config for local runs is `gcp/image/projects/sk/bmt_jobs.json`.

**Canonical flow for testing production CI locally:** [docs/development.md](docs/development.md#testing-production-ci-locally).

**Docs index:** [docs/README.md](docs/README.md).

## Time and clocks

Use a single, consistent approach for time so timestamps and durations stay correct and comparable:

| Need | Use | Notes |
| ---- | --- | ------ |
| **Wall-clock “now”** (timestamps, TTL, age vs stored time) | `whenever.Instant.now()` | Use `.format_iso(unit="second")` for ISO8601 or `.format_iso(unit="second", basic=True)` for compact. Use project helpers (`_now_iso()`, `_now_stamp()`, `tools.shared.time_utils.now_iso()` / `now_stamp()`) where available. |
| **Durations / elapsed time** (how long something took, timeouts) | `time.monotonic()` | Not comparable to wall-clock or `st_mtime`; use only for deltas. `whenever` does not replace monotonic timing. |
| **Sleep / backoff** | `time.sleep()` | For retries and polling intervals. |
| **Non-UTC display or scheduling** | `zoneinfo` (stdlib in 3.9+) | Use when you need a specific timezone; otherwise stick to UTC. |

Avoid `time.time()` and `datetime.now()` for new code; use `Instant.now()` (and `.timestamp()` when you need epoch float). `tools/shared/time_utils.py` is used by the local runner; CI and `gcp/` use in-file helpers or `gcp.image.utils` so they stay self-contained when copied to the bucket.

## tools Structure

Scripts organized by category prefix:

| Prefix | Category | Description |
| ------ | -------- | ----------- |
| `tools/shared/` | Shared libraries | Not executed directly; imported by other tools |
| `tools/remote/` | GCS / bucket | Sync, upload, verify, validate bucket; `bucket_*` only |
| `tools/bmt/` | BMT execution | Local batch runner, live monitor, wait verdicts |
| `tools/repo/` | Repo / GitHub | Layout policies, gh_* (env, app perms, repo vars, validate VM vars), paths, vars_contract, results_prefix |
| `tools/pulumi/` | Pulumi | Export Pulumi outputs to GitHub repo vars |

**Unified CLI:** `uv run python -m tools --help` is the single entry point (Typer). All dev commands are under `tools bucket`, `tools pulumi`, `tools repo`, `tools build`, `tools bmt`. **Just recipes** are thin wrappers (e.g. `just deploy` → `tools bucket deploy`); use `just` for the recommended interface.

**Run tools** via `uv run python -m tools.<folder>.<module>` (e.g. `uv run python -m tools.remote.bucket_sync_gcp`) or `just` recipes. Key modules:

- **shared/** — `bucket_env.py`, `bucket_sync.py`, `layout_patterns.py`, `gh.py`, `verdict.py`, `time_utils.py`, `env_contract.py`
- **remote/** — `bucket_sync_gcp.py`, `bucket_verify_gcp_sync.py`, `bucket_verify_runtime_seed_sync.py`, `bucket_sync_runtime_seed.py`, `bucket_upload_runner.py`, `bucket_upload_wavs.py`, `bucket_validate_contract.py`, `bucket_clean_bloat.py`
- **bmt/** — `bmt_run_local.py`, `bmt_monitor.py`, `bmt_wait_verdicts.py`, `vm_check.py` (use for `just monitor`, local batch, wait, `just vm-check`)
- **repo/** — `gcp_layout_policy.py`, `repo_layout_policy.py`, `gh_show_env.py`, `gh_app_perms.py`, `gh_repo_vars.py`, `gh_validate_vm_vars.py`, `paths.py`, `vars_contract.py`, `results_prefix.py`
- **pulumi/** — `pulumi_repo_vars.py`, `pulumi_preflight.py`, `pulumi_apply.py`

**Layout validators:** Run **`just test`** to run both layout policies (gcp + repo). Or run `uv run python -m tools.repo.gcp_layout_policy` and `uv run python -m tools.repo.repo_layout_policy` separately when changing layout or adding root-level entries.

**Config vs repo vars:** **Pulumi** (infra/pulumi) is the source of truth for all non-secret configuration. Run **`just pulumi`** to apply and push GitHub repo variables. **infra/bootstrap/** holds shell bootstrap (`.env.example`, `bootstrap_gh_vars.sh`) for secrets and one-off `gh variable set` / `gh secret set`. Use **`just validate`** to check repo vars vs Pulumi/contract and VM metadata. See [infra/README.md](infra/README.md).

Tools are **Python classes** with a `run()` method (and optional attributes). When run as scripts they read configuration from **environment variables only** (no CLI flags). Use `just` to see and run recipes.

## Linting and Type Checking

Run from repo root (config in [pyproject.toml](pyproject.toml) excludes `.venv`, `data`, `bmt_workspace`, `sk_runtime`, `local_batch`, `secrets`):

```bash
# Install the ci package and its dependencies (required before linting/running)
uv pip install -e .

# Lint (ruff — line length 120, Python 3.12 target)
ruff check .

# Format check
ruff format --check .

# Type check (basedpyright — covers whole repo: .github/bmt, gcp/, tools/)
basedpyright
```

**Path map (doc/code):** CI entrypoint: `uv run bmt <cmd>` / `.github/bmt/ci/`. Bucket tools: `tools/remote/bucket_*.py` (invoke via `tools bucket` or `uv run python -m tools.remote.bucket_*`). BMT run/monitor/wait: `tools/bmt/` only. VM scripts: `gcp/image/scripts/` (not `gcp/image/vm/`).

## Testing

### Unit tests (no GCS or VM)

From the repo root (with `uv pip install -e .` so the package is available):

```bash
uv run python -m pytest tests/ -v
```

These cover: pointer resolution and path construction in the manager (`tests/sk/test_bmt_manager_pointer.py`), VM watcher helpers (`tests/test_vm_watcher_pointer.py`), CI models and gate logic (`tests/test_ci_models.py`, `tests/test_gate.py`, `tests/test_counter_regex.py`). No bucket or VM required.

### Local BMT batch (no GCS)

Runs the **local** batch runner (different code path from the VM manager); useful for runner/config/score logic only. Set env and run (or call `BmtRunLocal().run(...)` from Python):

```bash
BMT_ID=4a5b6e82-a048-5c96-8734-2f64d2288378 \
BMT_JOBS_CONFIG=gcp/image/projects/sk/bmt_jobs.json \
BMT_RUNNER=gcp/stage/projects/sk/kardome_runner \
BMT_DATASET_ROOT=data/sk/inputs/false_rejects \
BMT_WORKERS=4 \
uv run python tools/bmt_run_local.py
```

### Testing the pointer/snapshot flow (with GCS)

To exercise the **manager** (snapshot writes, pointer read for baseline) and optionally the **watcher** (pointer update, cleanup) against a real bucket:

1. **One-off manager run** — Run the VM-side manager locally with a bucket and `run_id`. It will read `current.json` (or bootstrap), write under `snapshots/<run_id>/`, and emit a summary. Requires `gcloud` auth and a bucket with config/runner/dataset already synced.

   ```bash
   # From repo root; workspace can be a local dir
   uv run python gcp/image/projects/sk/bmt_manager.py \
     --bucket "<bucket>" \
     --project-id sk \
     --bmt-id 4a5b6e82-a048-5c96-8734-2f64d2288378 \
     --jobs-config gcp/image/projects/sk/bmt_jobs.json \
     --workspace-root ./local_batch \
     --run-context dev \
     --run-id test-run-$(date +%s) \
     --summary-out ./local_batch/manager_summary.json
   ```

   Then inspect GCS: under the bucket root (or `runtime/` prefix if used), `{results_prefix}/snapshots/<run_id>/` should contain `latest.json`, `ci_verdict.json`, and `logs/`. `results_prefix` is per-BMT from jobs config (e.g. `projects/sk/results/false_rejects`). If you had written a `current.json` beforehand, the manager uses it for baseline.

2. **Full E2E (trigger → VM → pointer)** — Run the real CI workflow (e.g. push to a branch or trigger manually). The workflow writes a run trigger; the VM (or a local process running `vm_watcher.py` with the same bucket and a local workspace) picks it up, runs the orchestrator per leg, then updates `current.json` and cleans snapshots. Verify in GCS: `current.json` at `results_prefix`, and only the latest/last-passing snapshot dirs under `snapshots/`.

3. **Wait command (pointer-based polling)** — With a trigger that has already been processed by the VM, the `wait` subcommand can be used to confirm it reads from the pointer and snapshot verdict path:

   ```bash
   uv run bmt wait \
     --manifest '<json with legs: project, bmt_id, run_id, triggered_at>' \
     --config-root gcp/image \
     --bucket "<bucket>" \
     --timeout-sec 60
   ```

   It resolves `results_prefix` from config, reads `current.json`, and when `latest` matches the leg’s `run_id`, downloads `snapshots/<run_id>/ci_verdict.json`.

## Local Development

### Run a local BMT batch (config-driven, no cloud VM needed)

```bash
uv run python -m tools.bmt.bmt_run_local \
  --bmt-id 4a5b6e82-a048-5c96-8734-2f64d2288378 \
  --jobs-config gcp/image/projects/sk/bmt_jobs.json \
  --runner gcp/stage/projects/sk/kardome_runner \
  --dataset-root data/sk/inputs/false_rejects \
  --workers 4
```

### Devtools (bucket sync, runner/wav upload, contract validation)

Bucket is read from canonical `GCS_BUCKET`. Bucket layout mirrors **`gcp/stage`** (see `tools/shared/bucket_env.py`: bucket root = gs://&lt;bucket&gt; with no prefix in the target layout; current deployment may use `code/` and `runtime/` prefixes). From repo root use **`just deploy`** (with `GCS_BUCKET`) to sync and verify, and `just show-env` to print the env var names used by CI, VM, and local tools.

**Pre-commit:** The workflow does not sync `gcp/` to GCS. The pre-commit hook (`verify-gcp-bucket-sync`) **blocks** commits that touch `gcp/` unless the bucket is in sync (or `SKIP_SYNC_VERIFY=1`). Run `just deploy` before committing gcp changes so the VM has the same code.

```bash
just deploy
# or: GCS_BUCKET="<bucket>" uv run python -m tools.remote.bucket_sync_gcp
# GCS_BUCKET="<bucket>" uv run python -m tools bucket upload-runner --runner-path <path>
# GCS_BUCKET="<bucket>" uv run python -m tools bucket upload-wavs --source-dir <dir>
# GCS_BUCKET="<bucket>" uv run python -m tools bucket validate-contract [--require-runner]
```

### Full reseed (destructive)

```bash
gcloud storage rm --recursive "gs://<bucket>/**"
GCS_BUCKET="<bucket>" uv run python -m tools bucket deploy
# Or run sync then verify-code and verify-runtime-seed separately via `tools bucket sync`, etc.
```

## Architecture

### CI Pipeline (trigger-and-stop — `.github/workflows/dummy-build-and-test.yml`)

The workflow uses **uv-managed Python**: `astral-sh/setup-uv`, then `uv sync` and `uv run bmt <cmd>`. The VM runs the watcher with `uv run python gcp/image/vm_watcher.py` from the repo root (same uv-managed venv).

The workflow has two jobs; it does not block for the full BMT run. All CI logic is in **`.github/bmt/`**; workflows run **`uv run bmt <cmd>`** from repo root.

| Stage | Job name | Command |
| ----- | -------- | ------- |
| 01 | Discover Matrix | `uv run bmt matrix --config-root gcp/image` |
| 02 | Trigger | `uv run bmt write-run-trigger` (and related steps: writes **one** run trigger to GCS), **starts the BMT VM**, then posts "pending" commit status; workflow ends |

**Stage 02** writes one run trigger to the bucket under `triggers/runs/<workflow_run_id>.json` (path relative to the bucket root that mirrors gcp/stage; current deployment may use a `runtime/` prefix). The VM boots, uses image-baked code (or syncs from bucket in current layout), polls triggers, runs `root_orchestrator.py` for each leg, aggregates verdicts, posts commit status (success/failure) to GitHub, then **stops itself**. The next PR or push to dev starts the VM again. Branch protection requires the "BMT Gate" status to pass. The `wait` and `gate` subcommands remain available for local or manual use but are not used by the workflow.

### CI Package (`.github/bmt/ci/`)

Python package under `.github/bmt/`; entrypoint is the **`bmt`** CLI (`uv run bmt <cmd>`).

| File | Purpose |
| ---- | ------- |
| `ci/models.py` | Constants (status, trigger, decision, reason codes), URI helpers, decision functions; **dataclasses** for verdicts/legs: `CloudVerdict`, `LegOutcome`, `AggregateRow`, `TriggerLeg`, `RunnerIdentity` (no Pydantic) |
| `ci/config.py` | Loads `bmt_projects.json` + jobs config; builds matrix; resolves `results_prefix` |
| `ci/adapters/gcloud_cli.py` | All GCP interaction via **subprocess** and **gcloud** CLI (upload/download/list, VM start); no Google Cloud SDK |
| `ci/commands/job_matrix.py` | `matrix` subcommand |
| `ci/commands/run_trigger.py` | `trigger` — writes one run trigger to runtime namespace (all legs; VM reports status to GitHub) |
| `ci/commands/sync_vm_metadata.py` | `sync-vm-metadata` — pushes bucket and repo root from workflow to VM metadata |
| `ci/commands/start_vm.py` | `start-vm` — starts the BMT VM (requires `GCP_PROJECT`, `GCP_ZONE`, `BMT_VM_NAME`) |
| `ci/commands/wait_handshake.py` | `wait-handshake` — waits for VM ack at `runtime/triggers/acks/<workflow_run_id>.json` |
| `ci/commands/upload_runner.py` | `upload-runner` — uploads runner artifacts to GCS |
| `ci/commands/wait_verdicts.py` | `wait` — polls GCS for verdicts, aggregates (manual/local only; not used by workflow) |
| `ci/commands/verdict_gate.py` | `gate` — enforces final pass/fail (manual/local only) |

### VM-side Execution (`gcp/`)

The `gcp/` directory has `gcp/image` (VM/image code and config; baked into the image, not uploaded to the bucket in the target layout) and `gcp/stage` (local mirror of bucket content; bucket layout mirrors this 1:1 per `gcp/README.md`). On the VM:

- **vm_watcher.py** — Polls GCS (or Pub/Sub) for run triggers. For each trigger: posts pending commit status, creates/updates a **GitHub Check Run** (implemented), runs `root_orchestrator.py` once per leg, reads verdicts from manager summaries (in-memory), updates each leg's `current.json` pointer and cleans stale snapshots, posts final commit status, completes the Check Run, deletes trigger. With `--exit-after-run`, after each run the VM idles for `--idle-timeout-sec` (default 600) waiting for another trigger; if none arrives, it exits so the startup script can stop the instance. The workflow reuses RUNNING VMs (no stop/start) so consecutive runs avoid cold boot. **PR comments are not implemented.**
- **root_orchestrator.py** — Per leg: loads registry (`bmt_projects.json`) and jobs config from the bucket (e.g. under `config/` and `projects/<name>/bmt_jobs.json`); invokes the manager (from image or bucket) with bucket, project, bmt_id, run_id, run_context; writes root summary to GCS.
- **Per-project managers** — Each project has its own **bmt_manager.py** (e.g. `projects/sk/bmt_manager.py`). They load BMT job config (dict/JSON), cache runner/template/dataset from GCS via `gcloud` CLI, run the runner binary per WAV in a thread pool, parse scores, evaluate gate, and write outputs under `{results_prefix}/snapshots/{run_id}/` (latest.json, ci_verdict.json, logs). Baseline is read by resolving `current.json` to the last-passing snapshot.
- **gcp/image/lib/** — Shared VM-side code only: `github_auth.py` (GitHub App JWT + installation token), `github_checks.py` (Check Run create/update), `status_file.py`. No `bmt_lib/` or `github_api.py` in the current implementation.

See **docs/architecture.md** for the full script reference, data flow, and limitations. Planned changes: see [ROADMAP.md](ROADMAP.md) and [docs/roadmap/](docs/roadmap/).

### Config Files

- **Project registry** — In GCS at a well-known path under the bucket root (e.g. `config/bmt_projects.json` when bucket root = gcp/stage). Maps project name → `manager_script` (e.g. `projects/sk/bmt_manager.py`) + `jobs_config` (e.g. `projects/sk/bmt_jobs.json`). Not baked into the image; loaded at runtime.
- **`gcp/image/projects/<name>/bmt_jobs.json`** — Per-project BMT definitions: runner URI, template URI, dataset paths, gate comparison, score parsing, caching. Example: `gcp/image/projects/sk/bmt_jobs.json`. Paths in the file are relative to the bucket/mount root (e.g. `projects/sk/results/false_rejects`).
- **`gcp/image/projects/shared/input_template.json`** — Single shared runner JSON config template with path placeholders (`/tmp/dummy/*`) for REF_PATH, MICS_PATH, output path, and all audio processing parameters. All projects reference it via `template_uri`: `projects/shared/input_template.json`.

### GCS result layout (pointer-based)

Paths are relative to the bucket root that mirrors gcp/stage (or the `runtime/` prefix if used). Each (project, bmt_id) has a **canonical pointer** at `{results_prefix}/current.json` (e.g. `projects/sk/results/false_rejects/current.json`). The manager never writes to the pointer; it writes all outputs under `{results_prefix}/snapshots/{run_id}/` (latest.json, ci_verdict.json, logs). After all legs complete, the watcher updates `current.json` (latest + last_passing run_ids) and deletes snapshots not referenced by the pointer. The gate reads baseline by resolving the pointer to the last-passing snapshot.

The **Check Run** is implemented and runs after the watcher updates `current.json` (after all legs complete); it reads from in-memory aggregation. PR comments are **not** implemented. Commit status and Check Run must not assume any file exists at the bare `results_prefix/` root other than `current.json`. Every outcome must produce a clear commit status and Check Run; see `docs/github-and-ci.md`.

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

**Required (from Pulumi):** `GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `BMT_VM_NAME`, `GCP_SA_EMAIL`, `BMT_STATUS_CONTEXT`, `BMT_HANDSHAKE_TIMEOUT_SEC`. Run `just pulumi` to apply and push repo vars. **Secrets:** `GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID`, `BMT_DISPATCH_APP_PRIVATE_KEY`. **VM-side:** per-repo `<prefix>_ID`, `<prefix>_INSTALLATION_ID`, `<prefix>_PRIVATE_KEY` in `gcp/image/config/github_repos.json`. Full reference: [docs/configuration.md](docs/configuration.md). Branch protection must require `BMT_STATUS_CONTEXT`.
