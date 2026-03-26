# VM Setup For BMT Watcher

Bootstrap scripts here configure the VM to run the pre-baked watcher runtime from local disk and execute one run per boot.

## Correct image rule

When **image-affecting paths** change (`infra/packer/**` or `backend/**`), a **BMT Image Build** run must succeed for that ref before BMT is considered valid. The BMT workflow enforces this: the **Check image up to date** job fails if those paths changed and no successful [BMT Image Build](../../../.github/workflows/bmt-vm-image-build.yml) run exists for the branch/commit. Run the workflow from the Actions tab or push to trigger it; then re-run BMT. A pre-commit hook (optional) warns when you commit under those paths.

## Boot flow

1. Workflow `sync-vm-metadata` sets VM metadata (`GCS_BUCKET`, `BMT_REPO_ROOT`) and inline `startup-script` from `startup_entrypoint.sh`.
2. `startup_entrypoint.sh` runs optional bucket validation (`validate_bucket_contract.py`), then executes baked `BMT_REPO_ROOT/scripts/run_watcher.py` via the venv Python.
3. `run_watcher.py` validates baked runtime dependencies, fetches GitHub App secrets, runs the watcher with `--exit-after-run`, then stops the VM.

## Namespace model

- Code root: `gs://<bucket>/code`
- Runtime root: `gs://<bucket>/runtime`

`backend` sync is used for image baking inputs and tooling. Runtime VM boot does not sync code from GCS.

## Scripts

Scripts under `scripts/` expect the **root project to be installed** so `backend` is importable (e.g. run from repo root with `uv run python backend/scripts/<script>.py` or `uv run python -m backend.scripts.<module>` where the module is a package). On the VM, the same holds: install with `pip install -e .` or `uv sync` from the image code root so imports work without path hacks.

| Script | Purpose |
| --- | --- |
| `vm_deps.txt` | Legacy list of VM runtime pip deps; kept for Packer/image-build checks. Runtime install uses `pip install -e ".[vm]"` from pyproject. |
| `startup_entrypoint.sh` | **Only shell script** executed by GCP; runs optional validation then `run_watcher.py` via venv. |
| `run_watcher.py` | Validate baked runtime, load secrets, run watcher, self-stop VM. |
| `validate_bucket_contract.py` | VM-side bucket contract validation (required code objects). |
| `install_deps.py` | Install the backend project in editable mode with `[vm]` extra; import check verifies `config.bmt_config` and runtime deps. |
| `set_startup_script_url.py` | Optional/manual: set VM to `startup-script-url` mode using entrypoint in GCS. |
| `rollback_startup_to_inline.py` | Restore legacy inline startup-script mode. |
| `export_vm_spec.py` | Export current VM spec (JSON + summary) for rollback/auditing. |
| `build_bmt_image.py` (in infra) | Build pre-baked runtime image from local backend; see `infra/scripts/build_bmt_image.py` (legacy; prefer Packer / BMT Image Build workflow). |
| `create_bmt_green_vm.py` | Create `<base>-green` VM from baked image using source (blue) VM settings; source is `BMT_LIVE_VM`. |
| `cutover_bmt_vm.py` | Cut over repo `BMT_LIVE_VM` GitHub variable to green VM. |
| `rollback_bmt_vm.py` | Roll back repo `BMT_LIVE_VM` to blue VM (defaults to `<base>-blue` when current ends with `-green`). |
| `audit_vm_and_bucket.py` | Audit VM paths and bucket trigger/results layout. |
| `ssh_install.py` | SSH into VM and run `install_deps.py` for persistent deps. |
| `bmt-watcher.service.example` | Optional systemd service example (ExecStart runs `run_watcher.py` via venv). |

For blue/green, names are `<base>-blue` and `<base>-green` (e.g. `bmt-gate-blue`, `bmt-gate-green`). Terraform creates the **blue** VM by default. When running `create_bmt_green_vm.py`, set `BMT_LIVE_VM` to the blue VM name so the script creates `<base>-green` from the Packer image.

Path constants (on-image and bucket) live in `backend/path_utils.py`.

## Required variables

- `GCP_PROJECT`
- `GCP_ZONE`
- `BMT_LIVE_VM`
- `GCS_BUCKET`

Optional:

- `BMT_REPO_ROOT` (default `/opt/bmt`)
- `BMT_WORKSPACE_ROOT` (defaults to `~/bmt_workspace`, fallback to legacy `~/sk_runtime`)
- `BMT_SELF_STOP` (default `1`; set `0` to disable auto-stop for manual maintenance/debug sessions)
- `BMT_UV_BIN` (optional for build/maintenance scripts; not used by runtime startup)
- `BMT_IMAGE_FAMILY` (optional image family, default `bmt-runtime`, used by image scripts)
- `BMT_IMAGE_NAME` (optional explicit image name for green VM creation)
- `TARGET_REPO` (required by cutover/rollback scripts when updating GitHub repo vars)
- `BMT_DEBUG` (optional; set `1` in VM metadata or env for extra trace in run_watcher.py)

## Blue/green

- **Blue** = `<base>-blue` (e.g. `bmt-gate-blue`), created by Terraform.
- **Green** = `<base>-green`, created by `create_bmt_green_vm.py` from Packer image using blue's settings.
- **Cutover** = `cutover_bmt_vm.py` sets repo `BMT_LIVE_VM` to the green VM name.
- **Rollback** = `rollback_bmt_vm.py` sets repo `BMT_LIVE_VM` back to blue; if current is `*-green`, rollback defaults to `<base>-blue`.

**Logging:** Startup and entrypoint scripts emit timestamped lines `[YYYY-MM-DDTHH:MM:SSZ] [script_name] message` so serial console and log files are debuggable. Errors use `::error::` prefix; warnings use `Warning:`. Startup log is also written to `/tmp/bmt-startup-*.log` and uploaded to GCS on exit (best-effort).

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

1. Sync code: `just deploy`
2. Optional/manual URL-mode setup:
   - `uv run python -m backend.scripts.set_startup_script_url` (or `python backend/scripts/set_startup_script_url.py`)
3. Roll back startup script if needed:
   - `uv run python -m backend.scripts.rollback_startup_to_inline`

## Auth model

Watcher token resolution is repository-aware via `backend/github/github_auth.py` + `backend/config/github_repos.json`.

- Required: GitHub App env vars (`<prefix>_ID`, `<prefix>_INSTALLATION_ID`, `<prefix>_PRIVATE_KEY`)
