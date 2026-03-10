# VM Setup For BMT Watcher

Bootstrap scripts here configure the VM to load watcher code from GCS and execute one run per boot.

## Boot flow

1. Workflow `sync-vm-metadata` validates required code objects in `<code-root>`, then sets VM metadata: `GCS_BUCKET`, `BMT_REPO_ROOT`, and inline `startup-script` from `startup_wrapper.sh`.
2. `startup_wrapper.sh` syncs `<code-root>/` into `BMT_REPO_ROOT` (fixed `code/` namespace).
3. `startup_wrapper.sh` then execs `startup_example.sh`.
4. `startup_example.sh` resolves `uv` (override -> PATH -> pinned code artifact), installs deps (if needed), fetches GitHub App secrets, runs watcher with `--exit-after-run`, then stops the VM.

## Namespace model

- Code root: `gs://<bucket>/code`
- Runtime root: `gs://<bucket>/runtime`

`remote/code` manual sync should populate `<code-root>` before VM runs.

## Scripts

| Script | Purpose |
| --- | --- |
| `setup_vm_startup.sh` | Optional/manual: set VM to `startup-script-url` mode using wrapper in GCS. |
| `rollback_vm_startup_to_inline.sh` | Restore legacy inline startup-script mode. |
| `startup_wrapper.sh` | Sync code into `BMT_REPO_ROOT`, then run `startup_example.sh`. |
| `ensure_uv.sh` | Resolve `uv` from `BMT_UV_BIN`, PATH, or pinned code artifact + checksum. |
| `startup_example.sh` | Install deps only when fingerprint changes, load secrets, run watcher, self-stop VM. |
| `install_deps.sh` | Run `uv sync --extra vm` and write dependency fingerprint stamp under `.venv/.bmt_dep_fingerprint`. |
| `export_vm_spec.sh` | Export current VM spec (JSON + summary) for rollback/auditing. |
| `build_bmt_image.sh` | Build pre-baked runtime image from bucket code (`code/`) with deps preinstalled. |
| `create_bmt_green_vm.sh` | Create `${BMT_VM_NAME}-v2` from baked image using source VM settings. |
| `cutover_bmt_vm.sh` | Cut over repo `BMT_VM_NAME` GitHub variable to green VM. |
| `rollback_bmt_vm.sh` | Roll back repo `BMT_VM_NAME` GitHub variable to blue VM. |
| `audit_vm_and_bucket.sh` | Audit VM paths and bucket trigger/results layout. |
| `bmt-watcher.service.example` | Optional systemd service example. |

## Required variables

- `GCP_PROJECT`
- `GCP_ZONE`
- `BMT_VM_NAME`
- `GCS_BUCKET`

**GitHub App secrets (VM):** Stored in GCP Secret Manager in region **europe-west4**, labeled TEST vs PROD. bmt-gate-sandbox uses `GITHUB_APP_TEST_*`; core-main uses `GITHUB_APP_PROD_*`. Bootstrap derives `BMT_SECRETS_LOCATION` from the VM zone so `gcloud secrets` uses the regional endpoint (`--location=europe-west4`).

Optional:

- `BMT_REPO_ROOT` (default `/opt/bmt`)
- `BMT_WORKSPACE_ROOT` (defaults to `~/bmt_workspace`, fallback to legacy `~/sk_runtime`)
- `BMT_SELF_STOP` (default `1`; set `0` to disable auto-stop for manual maintenance/debug sessions)
- `BMT_UV_BIN` (optional debug override for uv binary path)
- `BMT_IMAGE_FAMILY` (optional image family, default `bmt-runtime`, used by image scripts)
- `BMT_IMAGE_NAME` (optional explicit image name for green VM creation)
- `TARGET_REPO` (required by cutover/rollback scripts when updating GitHub repo vars)

Pinned uv artifact contract under `<code-root>`:

- `_tools/uv/linux-x86_64/uv`
- `_tools/uv/linux-x86_64/uv.sha256`
- `pyproject.toml` (VM runtime dependency contract)
- `uv.lock` (pinned dependency lock for frozen sync)

## Manual operations

1. Sync code:
   - `just sync-remote`
   - `just verify-sync`
2. Optional/manual URL-mode setup:
   - `./remote/code/bootstrap/setup_vm_startup.sh`
3. Roll back bootstrap mode if needed:
   - `./remote/code/bootstrap/rollback_vm_startup_to_inline.sh`

## Auth model

Watcher token resolution is repository-aware via `remote/code/lib/github_auth.py` + `remote/code/config/github_repos.json`.

- Required: GitHub App env vars (`<prefix>_ID`, `<prefix>_INSTALLATION_ID`, `<prefix>_PRIVATE_KEY`)
