# VM setup for BMT watcher (GitHub App + JWT)

This folder contains scripts and instructions to run `vm_watcher.py` on a GCP VM with GitHub App authentication (JWT to installation token) for posting commit status and Check Runs.

## Recommendation: run setup at startup (gcloud)

**Use a startup script** (via gcloud VM metadata or a systemd one-shot) that:

1. Installs VM dependencies once (`uv sync --extra vm` from `uv.lock`; `.venv` under repo root is persistent across VM stop/start if repo is on persistent disk, e.g. `/opt/bmt`).
2. Fetches App credentials from GCP Secret Manager and exports them as env vars.
3. Starts `vm_watcher.py`.

The **watcher** then reads `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, and `GITHUB_APP_PRIVATE_KEY` from the environment and generates the installation token (JWT) when it needs to call the GitHub API. It does **not** run the install or fetch secrets itself.

**Why startup script instead of "everything in the watcher"?**

- Dependency install (`uv sync`) should run once per VM (or per image); the watcher is run with `uv run python` and should not run package installs itself.
- Fetching secrets via `gcloud` in a small startup script keeps the watcher simple: it only reads env and does JWT. No Secret Manager client library in the watcher.
- If the watcher restarts (e.g. systemd), run the same "fetch secrets + exec watcher" wrapper so env is fresh.

## Prerequisites

- **uv** installed on the VM (install once via SSH, e.g. `curl -LsSf https://astral.sh/uv/install.sh | sh`).
- GCP project with Secret Manager enabled.
- Three secrets in Secret Manager (regional in the VM's region, e.g. `europe-west4`):
  - `GITHUB_APP_ID` (numeric App ID).
  - `GITHUB_APP_INSTALLATION_ID` (numeric Installation ID).
  - `GITHUB_APP_PRIVATE_KEY` (full .pem file contents).
- VM service account with role `roles/secretmanager.secretAccessor` on those secrets, and permission to **stop itself** (e.g. `roles/compute.instanceAdmin.v1` or a custom role with `compute.instances.stop`) so the VM can shut down after posting status.
- Repo (including `pyproject.toml`, `uv.lock`, and `remote/`) on the VM on a **persistent** path (e.g. `/opt/bmt` on the boot disk) so `.venv` and installed deps survive VM stop/start.

## Scripts

| Script | Purpose |
|--------|---------|
| `install_deps.sh` | Run `uv sync --extra vm --frozen` from repo root (uses `uv.lock`). Creates/updates `.venv` under repo root. Run once per VM (or at image build). Requires uv and `uv.lock` in repo. |
| `ssh_install.sh` | From your laptop: SSH into the VM and run `install_deps.sh` (installs uv if missing). Set `GCP_ZONE`, `VM_NAME` (or `BMT_VM_NAME`), and `GCP_PROJECT` or `GCP_SA_EMAIL`; optional `BMT_REPO_ROOT` (default `/opt/bmt`). |
| `setup_vm_startup.sh` | From your laptop: set VM custom metadata (`GCS_BUCKET`, `BMT_BUCKET_PREFIX`, `BMT_REPO_ROOT`) and GCP startup script. Requires `GCP_ZONE`, `VM_NAME`, `GCS_BUCKET`, and `GCP_PROJECT` or `GCP_SA_EMAIL`. Run after repo and deps are on the VM. |
| `startup_wrapper.sh` | Minimal script embedded in GCP startup-script metadata; reads config from instance metadata and exec's `startup_example.sh`. Used by `setup_vm_startup.sh`. |
| `startup_example.sh` | Main startup script: install deps if needed (uv sync), fetch secrets from Secret Manager, run watcher with `uv run python remote/vm_watcher.py`. Reads `GCS_BUCKET` / `BMT_BUCKET_PREFIX` from env or GCP instance metadata. |
| `audit_vm_and_bucket.sh` | Audit VM filesystem and bucket layout via `gcloud compute ssh` and `gcloud storage ls`. Requires `GCP_ZONE`, `VM_NAME` (or `BMT_VM_NAME`), `GCS_BUCKET`, and `GCP_PROJECT` or `GCP_SA_EMAIL`. |
| `bmt-watcher.service.example` | Example systemd unit that runs the startup script logic (deps + fetch secrets + watcher). |

## Quick start

1. Install **uv** on the VM once (e.g. via SSH: `curl -LsSf https://astral.sh/uv/install.sh | sh`).
2. Copy this repo (including `pyproject.toml`, `uv.lock`, and `remote/`) to the VM on a **persistent** path (e.g. `/opt/bmt`) so the venv survives stop/start.
3. Run dependency install once: `./remote/bootstrap/install_deps.sh /opt/bmt` (from repo root on the VM) or use `remote/bootstrap/ssh_install.sh` from your laptop (set `GCP_ZONE`, `VM_NAME`, and `GCP_PROJECT` or `GCP_SA_EMAIL`).
4. From your laptop, set VM metadata and startup script from **GH variables**: export `GCP_SA_EMAIL`, `GCP_ZONE`, `VM_NAME`, `GCS_BUCKET`, and optionally `BMT_BUCKET_PREFIX`, then run `./remote/bootstrap/setup_vm_startup.sh`. On each boot the VM runs one BMT run (watcher with `--exit-after-run`), posts status to GitHub, then **stops itself**. The CI workflow starts the VM on each PR/push to dev. Alternatively use systemd with `bmt-watcher.service.example` (without self-stop).

## VM and bucket config (no hardcoding)

All VM and bucket configuration comes from **GitHub repository/organization variables** (Settings → Secrets and variables → Actions → Variables) or from your environment when running locally. **Required variables:** `GCS_BUCKET`, `GCP_SA_EMAIL`, `GCP_ZONE`, `BMT_VM_NAME` (or `VM_NAME`). Optional: `BMT_BUCKET_PREFIX`, `BMT_REPO_ROOT`. `GCP_PROJECT` is derived from `GCP_SA_EMAIL` when unset. Then run `audit_vm_and_bucket.sh` to check VM filesystem and bucket layout and report bloat.

## Secret names

The scripts expect these Secret Manager secret IDs: `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY`. Use the same names or set env vars `GITHUB_APP_SECRET_ID_*` (see `startup_example.sh`).

## Fallback: PAT

If you do not set App credentials, the watcher can still use a PAT via `GITHUB_STATUS_TOKEN`. Check Runs require a GitHub App installation token.
