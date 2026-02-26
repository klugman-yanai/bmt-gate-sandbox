# Development

This document covers the **current** development workflow: setup, testing, lint/typecheck, Justfile recipes, and deploy (sync to bucket). For configuration and env vars see [configuration.md](configuration.md).

---

## Setup

1. **Python and uv:** Use Python 3.12 and [uv](https://docs.astral.sh/uv/) for install and run. From repo root:

   ```bash
   uv sync
   uv pip install -e .
   ```

   The editable install makes the `ci` package (and devtools) available for tests and CLI.

2. **Environment:** For local BMT runs you only need local paths (no GCS). For bucket sync, runner upload, and VM-related commands, set the canonical vars (see [configuration.md](configuration.md)). Typical local use:

   ```bash
   export GCS_BUCKET="<your-bucket>"   # for bucket_* and just sync-remote, validate-bucket, etc.
   export BMT_BUCKET_PREFIX=""         # optional parent prefix (code/runtime are derived)
   ```

   Optional: `GCP_PROJECT`, `GCP_ZONE`, `BMT_VM_NAME` for VM serial, validate-vm-vars, and CI workflow.

3. **Local diagnostics location:** Keep ad-hoc logs and snapshots under `.local/diagnostics/`. Do not use a root-level `debug/` directory.

---

## Testing

### Unit tests (no GCS or VM)

From repo root:

```bash
uv run python -m pytest tests/ -v
```

Covers: pointer resolution and path construction in the manager (`tests/sk/test_bmt_manager_pointer.py`), VM watcher helpers (`tests/test_vm_watcher_pointer.py`), CI models and gate logic (`tests/test_ci_models.py`, `tests/test_gate.py`, `tests/test_counter_regex.py`). No bucket or VM required.

### Local BMT batch (no GCS)

Runs the **local** batch runner (different code path from the VM manager). Useful for runner/config/score logic without cloud:

```bash
uv run python devtools/bmt_run_local.py \
  --bmt-id false_reject_namuh \
  --jobs-config remote/code/sk/config/bmt_jobs.json \
  --runner remote/runtime/sk/runners/kardome_runner \
  --runtime-root remote/runtime \
  --dataset-root data/sk/inputs/false_rejects \
  --workers 4
```

### Pointer/snapshot flow (with GCS)

Requires `gcloud` auth and a bucket with config/runner/dataset synced.

**1. One-off manager run** — Run the VM-side manager locally; it reads `current.json` (or bootstraps), writes under `snapshots/<run_id>/`, and emits a summary:

```bash
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

Then inspect GCS: `gs://<bucket>/<parent>/runtime/<results_prefix>/snapshots/<run_id>/` should contain `latest.json`, `ci_verdict.json`, and `logs/` (use `runtime/` when parent is empty).

**2. Full E2E** — Run the real CI workflow (push or manual trigger). The workflow writes a trigger; the VM (or a local `vm_watcher.py` with the same bucket) picks it up, runs legs, updates `current.json`, and prunes. Verify in GCS: `current.json` at results prefix and only referenced snapshot dirs under `snapshots/`.

**3. Wait command (pointer-based polling)** — After the VM has processed a trigger, you can confirm verdict read from pointer/snapshot:

```bash
uv run python .github/scripts/ci_driver.py wait \
  --manifest '<json with legs: project, bmt_id, run_id, triggered_at>' \
  --config-root remote/code \
  --bucket "<bucket>" \
  --timeout-sec 60
```

---

## Lint and type check

Config: [../pyproject.toml](../pyproject.toml) (excludes `.venv`, `data`, `bmt_workspace`, `sk_runtime`, `local_batch`, `secrets`).

```bash
ruff check .
ruff format --check .
basedpyright
```

Or:

```bash
just lint
```

- **ruff:** Line length 120, Python 3.12 target.
- **basedpyright:** Type checking across `.github/scripts`, `remote/`, `devtools/`.

---

## Justfile recipes

Run `just` (or `just --list`) for the full list. Key recipes:

| Recipe | Purpose |
|--------|---------|
| `just test` | Unit tests (pytest). |
| `just lint` | ruff check + format check + basedpyright. |
| `just monitor` | Live TUI for workflow/VM/GCS (e.g. `just monitor --auto`). |
| `just sync-remote` | Sync `remote/code` to `<code-root>` (requires `GCS_BUCKET`). |
| `just sync-runtime-seed` | Sync `remote/runtime` to `<runtime-root>`. |
| `just verify-sync` | Verify `remote/code` and `remote/runtime` match bucket manifests. |
| `just validate-layout` | Validate canonical `remote/` mirror policy. |
| `just validate-repo-layout` | Validate repo top-level layout policy (root clutter + tracked path policy). |
| `just upload-runner` | Upload runner to bucket. |
| `just upload-wavs <source_dir>` | Upload wav dataset to bucket (explicit source path, e.g. `data/sk/inputs/false_rejects`). |
| `just validate-bucket` | Validate bucket contract (optional `--require-runner` via script). |
| `just sync-vm-metadata` | Sync startup-critical VM metadata from repo configuration. |
| `just start-vm [args]` | Manual VM start wrapper for debug/maintenance/testing. |
| `just wait-handshake <workflow_run_id>` | Wait for VM ack under runtime triggers. |
| `just show-env` | Print env var names used by CI, VM, and devtools. |
| `just repo-vars-check` | Check repo vars against contract + optional overrides. |
| `just repo-vars-apply` | Apply vars to GitHub (with optional args). |
| `just validate-vm-vars` | Ensure repo vars match VM metadata. |
| `just gcs-trigger <run_id>` | Show trigger and ack JSON for a workflow run. |
| `just vm-serial` | Stream VM serial output. |
| `just check-vm-gcs <run_id>` | Trigger/ack + VM serial tail. |

---

## Build and deploy

There is **no formal build step** for the BMT pipeline. Deployment is:

1. **Manual sync `remote/code` to `<code-root>`** so VM boot and orchestrator fetches match local source:

   ```bash
   GCS_BUCKET="<bucket>" uv run python devtools/bucket_sync_remote.py
   GCS_BUCKET="<bucket>" uv run python devtools/bucket_verify_remote_sync.py
   # or: just sync-remote && just verify-sync
   ```

   Notes:
   - `remote/code/_tools/uv/linux-x86_64/uv.sha256` is the pinned UV checksum.
   - `bucket_sync_remote.py` uploads the local `uv` binary to `<code-root>/_tools/uv/linux-x86_64/uv` and validates it against that checksum.
   - Override local UV path during sync with `BMT_UV_TOOL_PATH=/path/to/uv`.

2. **Manual sync `remote/runtime` seed to `<runtime-root>`** when seed artifacts change:

   ```bash
   GCS_BUCKET="<bucket>" uv run python devtools/bucket_sync_runtime_seed.py
   GCS_BUCKET="<bucket>" uv run python devtools/bucket_verify_runtime_seed_sync.py
   # or: just sync-runtime-seed && just verify-sync
   ```

3. **Upload runner and datasets** as needed:

```bash
GCS_BUCKET="<bucket>" uv run python devtools/bucket_upload_runner.py --runner-path <path>
GCS_BUCKET="<bucket>" uv run python devtools/bucket_upload_wavs.py --source-dir data/sk/inputs/false_rejects
```

Dataset policy:
- `data/` is the local authoritative source for large WAV corpora.
- `remote/runtime/**/inputs/**` must remain placeholders only (`.keep`), not local WAV storage.

4. **Validate bucket contract:**

   ```bash
   GCS_BUCKET="<bucket>" uv run python devtools/bucket_validate_contract.py [--require-runner]
   # or: just validate-bucket
   ```

CI workflows are in `.github/workflows/`. They use the same `ci_driver.py` and `remote/code` content; production typically copies or mirrors these workflows. VM bootstrap and auth: [../remote/code/bootstrap/README.md](../remote/code/bootstrap/README.md). Full reseed (destructive): see [../CLAUDE.md](../CLAUDE.md#full-reseed-destructive).

## Bootstrap runbook

Use this when handshake ack does not appear under `<runtime-root>/triggers/acks/<run_id>.json`.

1. **Validate local layout and code sync**

   ```bash
   just validate-layout
   just sync-remote
   just verify-sync
   ```

2. **Validate bucket bootstrap objects**

   ```bash
   GCS_BUCKET="<bucket>" uv run python devtools/bucket_validate_contract.py
   gcloud storage ls "gs://<bucket>/<parent>/code/pyproject.toml"
   gcloud storage ls "gs://<bucket>/<parent>/code/uv.lock"
   gcloud storage ls "gs://<bucket>/<parent>/code/_tools/uv/linux-x86_64/uv"
   gcloud storage cat "gs://<bucket>/<parent>/code/_tools/uv/linux-x86_64/uv.sha256"
   ```

3. **Resync VM metadata and run controlled live check**

   ```bash
   uv run python .github/scripts/ci_driver.py sync-vm-metadata
   uv run python .github/scripts/ci_driver.py start-vm --allow-manual-start
   # write trigger + wait-handshake via ci_driver.py trigger / wait-handshake
   ```

4. **Temporary mitigation**
   - Set `BMT_UV_BIN` on VM metadata/runtime env to a known executable UV path.
   - Keep `BMT_SELF_STOP=1` unless explicitly doing maintenance with `BMT_SELF_STOP=0`.

## PR closure behavior

For `run_context=pr`, watcher performs PR-state checks:

- **Closed before pickup:** run is skipped (no leg execution, no new PR check/comment writes).
- **Closed during execution:** current leg is allowed to finish, remaining legs are marked skipped, and pending GitHub signals are finalized as cancelled (`check_run=neutral`, `commit_status=error`).
- **PR-state API failure:** fail-open (run continues).

Use `just monitor --run-id <id>` to confirm `run_outcome` / `cancel_reason` from `<runtime-root>/triggers/status/<id>.json`.

## VM start policy

- Manual VM starts are allowed only for **debugging**, **maintenance**, or **testing**.
- Routine starts should come from workflow control-plane (`bmt.yml`).
- Local/manual `start-vm` requires explicit override:
  - `--allow-manual-start`, or
  - `BMT_ALLOW_MANUAL_VM_START=1`
