# Development

This document covers the **current** development workflow: setup, testing, lint/typecheck, Justfile recipes, and deploy (sync to bucket). For configuration and env vars see [configuration.md](configuration.md).

---

## Setup

1. **Python and uv:** Use Python 3.12 and [uv](https://docs.astral.sh/uv/) for install and run. From repo root:

   ```bash
   uv sync
   uv pip install -e .
   ```

   The editable install makes the `ci` package (and tools) available for tests and CLI.

2. **Environment:** For local BMT runs you only need local paths (no GCS). For bucket sync, runner upload, and VM-related commands, set the canonical vars (see [configuration.md](configuration.md)). Typical local use:

   ```bash
   export GCS_BUCKET="<your-bucket>"   # for bucket_* and just sync-deploy, validate-bucket, etc.
   ```

   Optional: `GCP_PROJECT`, `GCP_ZONE`, `BMT_LIVE_VM` for VM serial, validate-vm-vars, and CI workflow.

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
uv run python tools/bmt_run_local.py \
  --bmt-id 4a5b6e82-a048-5c96-8734-2f64d2288378 \
  --jobs-config gcp/image/projects/sk/bmt_jobs.json \
  --runner gcp/remote/sk/runners/kardome_runner \
  --runtime-root gcp/remote \
  --dataset-root data/sk/inputs/false_rejects \
  --workers 4
```

### Pointer/snapshot flow (with GCS)

Requires `gcloud` auth and a bucket with config/runner/dataset synced.

**1. One-off manager run** — Run the VM-side manager locally; it reads `current.json` (or bootstraps), writes under `snapshots/<run_id>/`, and emits a summary:

```bash
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

Then inspect GCS: `gs://<bucket>/runtime/<results_prefix>/snapshots/<run_id>/` should contain `latest.json`, `ci_verdict.json`, and `logs/`.

**2. Full E2E** — Run the real CI workflow (push or manual trigger). The workflow writes a trigger; the VM (or a local `vm_watcher.py` with the same bucket) picks it up, runs legs, updates `current.json`, and prunes. Verify in GCS: `current.json` at results prefix and only referenced snapshot dirs under `snapshots/`.

**3. Wait command (pointer-based polling)** — After the VM has processed a trigger, you can confirm verdict read from pointer/snapshot:

```bash
uv run python .github/scripts/ci_driver.py wait \
  --manifest '<json with legs: project, bmt_id, run_id, triggered_at>' \
  --config-root gcp/image \
  --bucket "<bucket>" \
  --timeout-sec 60
```

---

## Testing production CI locally

This is the **canonical guide** for testing production BMT CI locally using the real VM and GCS (no mocks). Follow it when you want to validate the full handoff path before pushing to production.

**Production source.** BMT uses Terraform-managed VM(s). `BMT_LIVE_VM` is set from Terraform via `just terraform-export-vars-apply` or from the **BMT VM Provision** workflow after apply. Console-created VMs are not required; Terraform is the single source.

**Prerequisites**

- **BMT VM:** Terraform-managed; create or update the VM and repo vars with `just terraform-export-vars-apply` or the **BMT VM Provision** workflow (Actions). Console-created VMs are not required.
- **Repo variables** set: at least `GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `BMT_LIVE_VM`, and the Terraform-exported vars (`just terraform-export-vars-apply`), including `BMT_STATUS_CONTEXT`, `BMT_HANDSHAKE_TIMEOUT_SEC`. Optional: `GCP_WIF_PROVIDER`, `GCP_SA_EMAIL`, `BMT_PUBSUB_TOPIC`. Use `gh variable list` or Settings → Secrets and variables → Actions → Variables.
- **gcloud** authenticated and able to access the bucket and VM (`gcloud auth list`, `gcloud storage ls gs://<bucket>`).
- **Python 3.12** and **uv** (`uv sync` and `uv pip install -e .` from repo root).

Confirm env: `gh variable list` or export `GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `BMT_LIVE_VM` as needed.

**Strict prerequisite: sync the mirror**

Before running any workflow steps, sync the local mirror to the bucket so the VM runs the same code and layout you have locally:

```bash
just deploy
```

Skipping this can cause the VM to run stale code. Re-run after changing anything under `gcp/`.

**Option A: Deploy then trigger**

After prerequisites and sync, trigger the real CI (push to your branch or use **Actions → BMT → Run workflow**). The workflow writes a trigger, starts the VM, and waits for handshake. Use `just vm-check <run_id>` to inspect trigger/ack and VM serial output.

**Option B: Manual sequence**

1. Sync mirror: `just deploy`.
2. **Matrix** — `export GITHUB_OUTPUT="$(pwd)/.local/prod-ci-matrix.out"`, `mkdir -p .local`, `BMT_CONFIG_ROOT=gcp/image uv run bmt matrix`.
3. **Trigger** — Pick `RUN_ID="local-$(date +%s)"`, set `GITHUB_RUN_ID`, `GITHUB_OUTPUT`, `FILTERED_MATRIX_JSON`, `RUN_CONTEXT`, `GITHUB_REPOSITORY`; run `uv run bmt write-run-trigger`.
4. **Sync VM metadata** — `uv run bmt sync-vm-metadata` (or the equivalent CI step).
5. **Start the VM** — `uv run bmt start-vm` (debug/maintenance only; routine starts come from the workflow).
6. **Wait for handshake** — Use the workflow or poll `runtime/triggers/acks/<run_id>.json`.
7. **Verify** — `just monitor`, `just vm-check <run_id>`, GitHub PR Checks, GCS `current.json` and `snapshots/<run_id>/`.

**Verify**

- Trigger, ack, and VM serial: `just vm-check <run_id>` (read-only; does not start the VM).
- Live TUI: `just monitor` or `just monitor --run-id <run_id>`.
- Outcome: Check Run and commit status in GitHub; `current.json` and snapshot dirs in GCS at the results prefix.

See [architecture.md](architecture.md) and [plans/high-level-design-improvements.md](plans/high-level-design-improvements.md) for strategy and rationale.

---

## Lint and type check

All of the following are run by **`just test`** (pytest, ruff check, ruff format --check, basedpyright, shellcheck, gcp layout policy, repo layout policy). To run only lint/typecheck:

```bash
ruff check .
ruff format --check .
basedpyright
shellcheck --severity=warning gcp/image/vm/*.sh .github/bmt/ci/resources/startup_entrypoint.sh tools/scripts/hooks/*.sh
```

- **ruff:** Line length 120, Python 3.12 target.
- **basedpyright:** Type checking across `.github/scripts`, `gcp/`, `tools/`.
- **shellcheck:** VM and startup scripts under `gcp/image/vm/`, `.github/bmt/ci/resources/startup_entrypoint.sh`, and `tools/scripts/hooks/`. Install shellcheck (e.g. `apt install shellcheck`) if not present.

---

## Justfile recipes

Run `just` (or `just --list`) for the full list. Key recipes:

| Recipe | Purpose |
| --- | --- |
| `just test` | **Pre-push gate:** pytest, ruff check, ruff format --check, basedpyright, shellcheck, gcp layout policy, repo layout policy. |
| `just deploy` | Sync `gcp/` to bucket and verify (sync code + runtime seed, then verify). Requires `GCS_BUCKET`. Run after changing gcp/ code. |
| `just monitor` | Live TUI for workflow/VM/GCS (e.g. `just monitor --run-id <id>`). |
| `just vm-check <run_id>` | Show trigger, ack, and VM serial tail for a run. Read-only; does not start the VM. |
| `just build-image [branch]` | Dispatch the BMT Image Build workflow (branch defaults to current). |

Other operations (sync, upload, validate, repo vars, bmt matrix/trigger, etc.) are run via `uv run python -m tools.<folder>.<module>` (e.g. `tools.remote.bucket_sync_gcp`, `tools.repo.gh_repo_vars`) or `uv run bmt <cmd>`; see [CLAUDE.md](../CLAUDE.md) and `uv run bmt --help`.

---

## Build and deploy

There is **no formal build step** for the BMT pipeline. Deployment is:

1. **Manual sync `gcp/image` to `<code-root>`** so VM boot and orchestrator fetches match local source:

   ```bash
   GCS_BUCKET="<bucket>" just deploy
   # or stepwise: just sync-gcp && just verify-sync
   ```

   Notes:
   - `gcp/image/_tools/uv/linux-x86_64/uv.sha256` is the pinned UV checksum.
   - `bucket_sync_deploy.py` uploads the local `uv` binary to `<code-root>/_tools/uv/linux-x86_64/uv` and validates it against that checksum.
   - Override local UV path during sync with `BMT_UV_TOOL_PATH=/path/to/uv`.

2. **Manual sync `gcp/remote` seed to `<runtime-root>`** when seed artifacts change:

   ```bash
   GCS_BUCKET="<bucket>" uv run python -m tools.remote.bucket_sync_runtime_seed
   GCS_BUCKET="<bucket>" uv run python -m tools.remote.bucket_verify_runtime_seed_sync
   ```

3. **Upload runner and datasets** as needed:

   ```bash
   GCS_BUCKET="<bucket>" uv run python -m tools.remote.bucket_upload_runner
   GCS_BUCKET="<bucket>" uv run python -m tools.remote.bucket_upload_wavs
   ```

Dataset policy: `data/` is the local authoritative source for large WAV corpora; `gcp/remote/**/inputs/**` must remain placeholders only (`.keep`), not local WAV storage.

4. **Validate bucket contract:**

   ```bash
   GCS_BUCKET="<bucket>" uv run python -m tools.remote.bucket_validate_contract
   ```

5. **Read-only mount for local inspection (optional):** To browse or play bucket dataset WAVs locally without downloading, use the FUSE script (requires `gcsfuse` and `gcloud` auth):

   ```bash
   GCS_BUCKET="<bucket>" tools/local/mount_remote_data.sh
   # Default mount: ./mnt/audio_data. Override with BMT_MOUNT_POINT=<path>.
   # Unmount: fusermount -u ./mnt/audio_data
   ```

   The mount is read-only (`-o ro`) so you cannot accidentally modify or delete bucket objects.

CI workflows are in `.github/workflows/`. They use the same `ci_driver.py` and `gcp/image` content; production typically copies or mirrors these workflows. VM bootstrap and auth: [../gcp/image/vm/README.md](../gcp/image/vm/README.md). Full reseed (destructive): see [../CLAUDE.md](../CLAUDE.md#full-reseed-destructive).

### VM image: rebuild when needed

The **BMT Image Build** workflow (`.github/workflows/bmt-vm-image-build.yml`) builds the VM image with Packer. To keep the image up to date:

- **Automatic:** Pushes to `main`, `ci/check-bmt-gate`, or `dev` that change `infra/packer/**` or `gcp/image/vm/**` trigger the image build. The new image is published to the same family; Terraform and **BMT VM Provision** use the latest image in the family when creating or recreating the VM.
- **Manual:** Run the workflow from the Actions tab (**BMT Image Build** → Run workflow) to rebuild with default inputs.
- **Image-up-to-date check:** The BMT workflow runs a **Check image up to date** job first. If image-affecting paths changed on your branch/commit but no successful BMT Image Build run exists for that ref, the job fails with a clear message; run BMT Image Build for the branch and re-run BMT.
- **Pre-commit:** When you commit under `infra/packer/` or `gcp/image/vm/`, a hook (optional) reminds you that an image build should run before merging; see [gcp/image/vm/README.md](../gcp/image/vm/README.md).
- **Using the new image:** New VMs get the latest image automatically. For an existing VM, run the **BMT VM Provision** workflow (with the same image family) and recreate the instance if you need the new disk image (e.g. after cloud-init or bootstrap changes).

### Cleaning GCS and VM of Python/uv bloat

To remove existing `__pycache__`, `.pyc`, `.venv`, and similar bloat from the bucket (e.g. after fixing sync excludes):

- **GCS:** Run a dry-run first, then execute:

  ```bash
  GCS_BUCKET="<bucket>" just clean-bloat              # default: code scope, dry-run
  GCS_BUCKET="<bucket>" just clean-bloat --execute    # delete bloat under code
  GCS_BUCKET="<bucket>" just clean-bloat --scope both --execute   # code + runtime
  ```

- **VM:** The startup wrapper removes bloat under `BMT_REPO_ROOT` after each code sync, so the next VM boot will clean the local tree. No extra step required.

## Bootstrap runbook

Use this when handshake ack does not appear under `<runtime-root>/triggers/acks/<run_id>.json`.

Bootstrap runbook: "just deploy" (or `uv run python -m tools.remote.bucket_sync_gcp` then verify). The pre-commit hook blocks commits that touch `gcp/` unless the bucket is in sync (or `SKIP_SYNC_VERIFY=1`), so the VM runs the same code and config as your branch.

1. **Validate local layout and code sync**

   ```bash
   uv run python -m tools.repo.gcp_layout_policy
   just deploy
   ```

2. **Validate bucket bootstrap objects**

   ```bash
   GCS_BUCKET="<bucket>" uv run python -m tools.remote.bucket_validate_contract
   gcloud storage ls "gs://<bucket>/code/pyproject.toml"
   gcloud storage ls "gs://<bucket>/code/uv.lock"
   gcloud storage ls "gs://<bucket>/code/_tools/uv/linux-x86_64/uv"
   gcloud storage cat "gs://<bucket>/code/_tools/uv/linux-x86_64/uv.sha256"
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

## PR closure and supersede behavior

For `run_context=pr`, watcher performs PR-state/head checks:

- **Closed before pickup:** run is skipped (no leg execution, no new PR check/comment writes).
- **Superseded before pickup:** run is skipped with reason `superseded_by_new_commit`.
- **Closed during execution:** current leg is allowed to finish, remaining legs are marked skipped, and pending GitHub signals are finalized as cancelled (`check_run=neutral`, `commit_status=error`).
- **Superseded during execution:** current leg is allowed to finish, remaining legs are marked skipped, run is cancelled with `superseded_by_new_commit`, and pointer promotion is skipped.
- **PR-state API failure:** fail-open (run continues).
- **PR comments:** upsert one VM-owned comment per tested SHA, including commit links (and superseding SHA link when applicable).

Use `just monitor --run-id <id>` to confirm `run_outcome` / `cancel_reason` / `superseded_by_sha` from `<runtime-root>/triggers/status/<id>.json`.

## VM start policy

- Manual VM starts are allowed only for **debugging**, **maintenance**, or **testing**.
- Routine starts should come from workflow control-plane (`bmt-handoff.yml`).
- Local/manual `start-vm` requires explicit override:
  - `--allow-manual-start`, or
  - `BMT_ALLOW_MANUAL_VM_START=1`
