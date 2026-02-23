# VM Setup For BMT Watcher

This directory contains scripts to bootstrap and run `remote/vm_watcher.py` on a GCP VM.

Current runtime model:

1. VM boots (or service starts).
2. Startup script installs deps if needed.
3. Startup script fetches GitHub App secrets from Secret Manager into env vars.
4. Startup script runs watcher with `--exit-after-run`.
5. Watcher processes one run trigger, posts final GitHub status/check run, exits.
6. Startup script stops the VM instance.

## Auth Model Used By Watcher

Watcher auth resolution is repository-aware:

1. `remote/lib/github_auth.py` loads `remote/config/github_repos.json`.
2. For a repository, it reads `secret_prefix` (for example `GITHUB_APP_TEST` or `GITHUB_APP_PROD`).
3. It expects environment variables:
`<secret_prefix>_ID`, `<secret_prefix>_INSTALLATION_ID`, `<secret_prefix>_PRIVATE_KEY`.
4. It mints an installation token (JWT flow) and calls GitHub APIs.
5. If unavailable, it falls back to PAT (`GITHUB_STATUS_TOKEN`) when enabled.

`startup_example.sh` currently fetches these Secret Manager IDs when present:

- `GITHUB_APP_TEST_ID`
- `GITHUB_APP_TEST_INSTALLATION_ID`
- `GITHUB_APP_TEST_PRIVATE_KEY`
- `GITHUB_APP_PROD_ID`
- `GITHUB_APP_PROD_INSTALLATION_ID`
- `GITHUB_APP_PROD_PRIVATE_KEY`

## Prerequisites

- `uv` installed on VM.
- Repo cloned on persistent disk (for example `/opt/bmt`) with `pyproject.toml`, `uv.lock`, `remote/`.
- Secret Manager enabled.
- VM service account permissions:
`roles/secretmanager.secretAccessor` for GitHub App secrets.
- VM service account permissions:
`compute.instances.stop` (for self-stop after run).
- GCP metadata/environment values available:
`GCS_BUCKET`, optional `BMT_BUCKET_PREFIX`, optional `BMT_REPO_ROOT`.

## Scripts

| Script | Purpose |
|--------|---------|
| `install_deps.sh` | `uv sync --extra vm --frozen` in repo root. |
| `ssh_install.sh` | Run `install_deps.sh` remotely over `gcloud compute ssh`. |
| `setup_vm_startup.sh` | Set VM metadata and startup-script (`startup_wrapper.sh`). |
| `startup_wrapper.sh` | Minimal metadata reader that execs `startup_example.sh`. |
| `startup_example.sh` | Fetch secrets, run watcher, stop VM on success. |
| `audit_vm_and_bucket.sh` | Audit VM files and bucket trigger/results layout. |
| `bmt-watcher.service.example` | Example systemd unit using startup script. |

## Quick Start

1. Install `uv` once on VM.
2. Put repo on VM at persistent path (recommended `/opt/bmt`).
3. Install deps once:
`./remote/bootstrap/install_deps.sh /opt/bmt`.
4. Configure startup metadata from laptop:
set `GCP_ZONE`, `VM_NAME` or `BMT_VM_NAME`, `GCS_BUCKET`, and `GCP_PROJECT` or `GCP_SA_EMAIL`, then run:
`./remote/bootstrap/setup_vm_startup.sh`.
5. On next boot, VM runs watcher for one trigger and then stops itself.

## Configuration Variables

Required:

- `GCS_BUCKET`
- `GCP_ZONE`
- `VM_NAME` or `BMT_VM_NAME`
- `GCP_PROJECT` or `GCP_SA_EMAIL` (project derived from SA email when omitted)

Optional:

- `BMT_BUCKET_PREFIX`
- `BMT_REPO_ROOT` (default `/opt/bmt`)
- `BMT_WORKSPACE_ROOT`

## PAT Fallback

If GitHub App credentials are missing, watcher can still post commit status with `GITHUB_STATUS_TOKEN` (subject to `remote/config/github_repos.json` fallback settings).
Check Run APIs generally require token scopes/permissions typically provided by GitHub App installation tokens.
