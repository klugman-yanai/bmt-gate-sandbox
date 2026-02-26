# VM Setup For BMT Watcher

Bootstrap scripts here configure the VM to load watcher code from GCS and execute one run per boot.

## Boot flow

1. Workflow `sync-vm-metadata` validates required code objects in `<code-root>`, then sets VM metadata: `GCS_BUCKET`, `BMT_BUCKET_PREFIX`, `BMT_REPO_ROOT`, and inline `startup-script` from `startup_wrapper.sh`.
2. `startup_wrapper.sh` syncs `<code-root>/` into `BMT_REPO_ROOT` (strict `code/` namespace).
3. `startup_wrapper.sh` then execs `startup_example.sh`.
4. `startup_example.sh` resolves `uv` (override -> PATH -> pinned code artifact), installs deps (if needed), fetches GitHub App secrets, runs watcher with `--exit-after-run`, then stops the VM.

## Prefix model

- Parent: `BMT_BUCKET_PREFIX` (may be empty)
- Code prefix: `<parent>/code` (or `code`)
- Runtime prefix: `<parent>/runtime` (or `runtime`)

`remote/code` manual sync should populate `<code-root>` before VM runs.

## Scripts

| Script | Purpose |
| --- | --- |
| `setup_vm_startup.sh` | Optional/manual: set VM to `startup-script-url` mode using wrapper in GCS. |
| `rollback_vm_startup_to_inline.sh` | Restore legacy inline startup-script mode. |
| `startup_wrapper.sh` | Sync code into `BMT_REPO_ROOT`, then run `startup_example.sh`. |
| `ensure_uv.sh` | Resolve `uv` from `BMT_UV_BIN`, PATH, or pinned code artifact + checksum. |
| `startup_example.sh` | Install deps, load secrets, run watcher, self-stop VM. |
| `install_deps.sh` | Run `uv sync --extra vm` from code-root `pyproject.toml` (`--frozen` when `uv.lock` exists). |
| `audit_vm_and_bucket.sh` | Audit VM paths and bucket trigger/results layout. |
| `bmt-watcher.service.example` | Optional systemd service example. |

## Required variables

- `GCP_PROJECT`
- `GCP_ZONE`
- `BMT_VM_NAME`
- `GCS_BUCKET`

Optional:

- `BMT_BUCKET_PREFIX`
- `BMT_REPO_ROOT` (default `/opt/bmt`)
- `BMT_WORKSPACE_ROOT` (defaults to `~/bmt_workspace`, fallback to legacy `~/sk_runtime`)
- `BMT_SELF_STOP` (default `1`; set `0` to disable auto-stop for manual maintenance/debug sessions)
- `BMT_UV_BIN` (optional debug override for uv binary path)

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
