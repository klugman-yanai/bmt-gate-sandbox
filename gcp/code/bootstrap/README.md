# VM Setup For BMT Watcher

Bootstrap scripts here configure the VM to run the pre-baked watcher runtime from local disk and execute one run per boot.

## Boot flow

1. Workflow `sync-vm-metadata` sets VM metadata (`GCS_BUCKET`, `BMT_REPO_ROOT`) and inline `startup-script` from `startup_wrapper.sh`.
2. `startup_wrapper.sh` executes baked `BMT_REPO_ROOT/bootstrap/startup_example.sh`.
3. `startup_example.sh` validates baked runtime dependencies, fetches GitHub App secrets, runs watcher with `--exit-after-run`, then stops the VM.

## Namespace model

- Code root: `gs://<bucket>/code`
- Runtime root: `gs://<bucket>/runtime`

`gcp/code` sync is used for image baking inputs and tooling. Runtime VM boot does not sync code from GCS.

## Scripts

| Script | Purpose |
| --- | --- |
| `setup_vm_startup.sh` | Optional/manual: set VM to `startup-script-url` mode using wrapper in GCS. |
| `rollback_vm_startup_to_inline.sh` | Restore legacy inline startup-script mode. |
| `startup_wrapper.sh` | Execute baked `startup_example.sh` from local `BMT_REPO_ROOT`. |
| `startup_example.sh` | Validate baked runtime, load secrets, run watcher, self-stop VM. |
| `ensure_uv.sh` | Resolve `uv` from `BMT_UV_BIN`, PATH, or pinned code artifact + checksum (build/maintenance tooling). |
| `install_deps.sh` | Install VM deps into `.venv` (image build/maintenance tooling, not runtime boot). |
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

Optional:

- `BMT_REPO_ROOT` (default `/opt/bmt`)
- `BMT_WORKSPACE_ROOT` (defaults to `~/bmt_workspace`, fallback to legacy `~/sk_runtime`)
- `BMT_SELF_STOP` (default `1`; set `0` to disable auto-stop for manual maintenance/debug sessions)
- `BMT_UV_BIN` (optional for build/maintenance scripts; not used by runtime startup)
- `BMT_IMAGE_FAMILY` (optional image family, default `bmt-runtime`, used by image scripts)
- `BMT_IMAGE_NAME` (optional explicit image name for green VM creation)
- `TARGET_REPO` (required by cutover/rollback scripts when updating GitHub repo vars)

Pinned uv artifact contract under `<code-root>` (image build path):

- `_tools/uv/linux-x86_64/uv`
- `_tools/uv/linux-x86_64/uv.sha256`
- `pyproject.toml` (runtime dependency contract baked into image)
- `uv.lock` (dependency lock baked into image)

## Runtime invariants

- VM startup does not install dependencies.
- VM startup does not resolve or execute `uv`.
- Dependency/code changes require baking a new runtime image and reprovisioning VM.

## Manual operations

1. Sync code:
   - `just sync-gcp`
   - `just verify-sync`
2. Optional/manual URL-mode setup:
   - `./gcp/code/bootstrap/setup_vm_startup.sh`
3. Roll back bootstrap mode if needed:
   - `./gcp/code/bootstrap/rollback_vm_startup_to_inline.sh`

## Auth model

Watcher token resolution is repository-aware via `gcp/code/lib/github_auth.py` + `gcp/code/config/github_repos.json`.

- Required: GitHub App env vars (`<prefix>_ID`, `<prefix>_INSTALLATION_ID`, `<prefix>_PRIVATE_KEY`)
