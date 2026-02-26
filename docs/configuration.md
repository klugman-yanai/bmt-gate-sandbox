# Configuration

This document describes **current** configuration: env contract, repo vars, VM metadata and runtime env, secrets, and bucket layout. The canonical source for variable definitions and consistency checks is [../config/env_contract.json](../config/env_contract.json). For a quick start and workflow overview see [../README.md](../README.md).

---

## Environment contract

**config/env_contract.json** defines:

- **contexts** — Where and how variables are used: `github_repo_vars`, `vm_metadata`, `vm_runtime_env`, `local_dev_env`.
- **required / optional** — Per context, which variables are required vs optional.
- **defaults** — Default values for optional vars (e.g. `BMT_BUCKET_PREFIX`, `BMT_STATUS_CONTEXT`, `BMT_HANDSHAKE_TIMEOUT_SEC`).
- **consistency_checks** — e.g. `repo_vs_vm_metadata` for `GCS_BUCKET` and `BMT_BUCKET_PREFIX` so repo config and VM metadata stay in sync.

Tooling (e.g. `devtools/gh_repo_vars.py`, `devtools/gh_validate_vm_vars.py`) uses this contract to check and apply repo vars and to validate VM metadata.

---

## Repository variables (GitHub)

Set in **Settings → Secrets and variables → Actions → Variables** (or via `gh variable set`). Canonical names only; no aliases (e.g. no `VM_NAME` or `BUCKET`). Set `GCP_PROJECT` explicitly; do not rely on a derived project fallback.

### Required (github_repo_vars)

| Variable | Purpose |
|----------|---------|
| `GCS_BUCKET` | GCS bucket name. |
| `GCP_WIF_PROVIDER` | Workload Identity Federation provider for CI. |
| `GCP_SA_EMAIL` | Service account email for WIF auth. |
| `GCP_PROJECT` | GCP project ID for VM operations. |
| `GCP_ZONE` | VM zone (e.g. `europe-west4-a`). |
| `BMT_VM_NAME` | VM instance name (workflow starts it; VM can stop itself after one run). |

### Optional (common)

| Variable | Default | Purpose |
|----------|---------|---------|
| `BMT_BUCKET_PREFIX` | `""` | Parent namespace prefix; code/runtime are derived as `<parent>/code` and `<parent>/runtime`. |
| `BMT_PROJECTS` | `"all release runners"` | Filter for BMT projects (e.g. non-embedded `*_gcc_Release` presets). |
| `BMT_STATUS_CONTEXT` | `"BMT Gate"` | Commit status name; must match branch protection. |
| `BMT_HANDSHAKE_TIMEOUT_SEC` | `"180"` | Timeout for VM handshake wait. |

Omitted vars inherit from current GitHub repo context first, then from contract defaults (see `config/env_contract.json` and `devtools/gh_repo_vars.py`). Optional overrides can be declared in **config/repo_vars.toml** for local/tooling use.

### Useful commands

```bash
just repo-vars-check    # Check repo vars against contract
just repo-vars-apply    # Apply vars to GitHub (with optional args)
just show-env           # Print env var names used by CI, VM, devtools
just validate-vm-vars   # Ensure repo vars match VM metadata
just sync-vm-metadata   # Sync startup-critical VM metadata from repo contract
```

---

## VM metadata

The workflow syncs **VM metadata** from repo config so the VM uses the same bucket and prefix without a manual bootstrap rerun. Keys synced:

- **GCS_BUCKET** (required)
- **BMT_BUCKET_PREFIX** (optional)
- **BMT_REPO_ROOT** (optional; default `/opt/bmt`)
- **startup-script** (set from `remote/code/bootstrap/startup_wrapper.sh` by `sync-vm-metadata`)
- **startup-script-url** (cleared by workflow metadata sync; optional/manual URL mode can be set by `remote/code/bootstrap/setup_vm_startup.sh`)

`sync-vm-metadata` also validates that required bootstrap code objects exist in `<code-root>` before starting the VM.
This includes pinned UV tool artifacts under `<code-root>/_tools/uv/linux-x86_64/`.

Defined under `vm_metadata` in [../config/env_contract.json](../config/env_contract.json). Consistency check `repo_vs_vm_metadata` ensures `GCS_BUCKET` and `BMT_BUCKET_PREFIX` match between repo vars and VM metadata.

---

## VM runtime environment

On the VM, these are the runtime credentials expected by `vm_watcher.py`. For every enabled repository in `remote/code/config/github_repos.json`, the matching App credential triple must be resolvable at startup:

| Variable | Purpose |
|----------|---------|
| `GITHUB_APP_TEST_ID`, `GITHUB_APP_TEST_INSTALLATION_ID`, `GITHUB_APP_TEST_PRIVATE_KEY` | GitHub App credentials (test). |
| `GITHUB_APP_PROD_ID`, `GITHUB_APP_PROD_INSTALLATION_ID`, `GITHUB_APP_PROD_PRIVATE_KEY` | GitHub App credentials (production). |
| `BMT_UV_BIN` | Optional debug override for uv binary path on VM (bootstrap default is self-heal from pinned code artifact). |

Repository mapping is in **remote/code/config/github_repos.json**. See [../remote/code/lib/github_auth.py](../remote/code/lib/github_auth.py) for resolution logic.

---

## Secrets (GitHub Actions)

| Secret | Purpose |
|--------|---------|
| `APP_TEST_ID` | GitHub App ID used by `ci.yml` (`actions/create-github-app-token@v2`). |
| `APP_TEST_PRIVATE_KEY` | GitHub App private key used by `ci.yml` to mint dispatch token for `workflow_dispatch`. |

---

## Bucket structure (summary)

Use:
- `<parent> = normalize(BMT_BUCKET_PREFIX)` (may be empty)
- `<code-root> = gs://<bucket>/<parent>/code` (or `gs://<bucket>/code`)
- `<runtime-root> = gs://<bucket>/<parent>/runtime` (or `gs://<bucket>/runtime`)

`remote/code` is the manual-sync source of truth for `<code-root>` only.
`remote/runtime` is the manual-sync source for runtime seed artifacts under `<runtime-root>`.
Local large WAV corpora remain under `data/` (not inside `remote/runtime`).
Local mirror policy details: [../remote/README.md](../remote/README.md).

- **`<code-root>/...`** — deployable watcher/orchestrator/manager/bootstrap/config mirrored from `remote/code`.
- **`<code-root>/pyproject.toml`** — VM runtime dependency contract for watcher execution.
- **`<code-root>/uv.lock`** — pinned lock used by `bootstrap/install_deps.sh` (`uv sync --extra vm --frozen`).
- **`<code-root>/_tools/uv/linux-x86_64/uv`** — pinned uv binary uploaded by `just sync-remote`.
- **`<code-root>/_tools/uv/linux-x86_64/uv.sha256`** — pinned uv checksum tracked in repo and verified at boot.
- **`<runtime-root>/triggers/runs/<workflow_run_id>.json`** — Run trigger (CI writes; VM deletes after process).
- **`<runtime-root>/triggers/acks/<workflow_run_id>.json`** — VM handshake ack.
- **`<runtime-root>/triggers/status/<workflow_run_id>.json`** — VM progress heartbeat.
- **`<runtime-root>/_meta/runtime_seed_manifest.json`** — runtime seed sync manifest (written by `devtools/bucket_sync_runtime_seed.py`).
- **`<runtime-root>/<project>/runners/<preset>/...`** — Runner bundles (uploaded by workflow/devtools).
- **`<runtime-root>/<project>/inputs/...`** — Runtime input objects in bucket; local source is explicit upload from `data/...` (keep `remote/runtime/**/inputs` as placeholders only).
- **`<runtime-root>/<results_prefix>/current.json`** — Pointer (`latest`, `last_passing` run_id); updated by watcher.
- **`<runtime-root>/<results_prefix>/snapshots/<run_id>/`** — Per-run artifacts (`latest.json`, `ci_verdict.json`, logs).

Pointer semantics and retention: [architecture.md](architecture.md#gcs-bucket-structure) and [implementation.md](implementation.md#data-flow-detail).

---

## Branch protection

Require the **commit status** named by `BMT_STATUS_CONTEXT` (default: **BMT Gate**) to pass before merge. The Check Run is for visibility; the gate is the commit status.
