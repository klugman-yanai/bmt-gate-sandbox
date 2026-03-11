# Configuration

This document describes **current** configuration: Terraform for infra-derived repo vars; a Python contract (tools/repo/vars_contract.py) for required/optional/secrets and behavioral defaults. **Behavioral defaults** (handshake timeout, VM timeouts, trigger retention, etc.) are defined in **gcp/code/lib/bmt_config.py** (Pydantic model). Some values are **constants** in that module (not config): trigger metadata keep-recent count, VM stabilization/recovery delays, preempt-on-PR-stale behavior, stale trigger age in hours, default repo root, and the runtime context label. Only **bmt_status_context** (and optionally the timeout fields) remain as configurable behavior; status context must match branch protection. Terraform, Justfile, and .env.example document the same values where they are exported. Secrets are documented in [../infra/README.md](../infra/README.md). For a quick start see [../README.md](../README.md).

---

## Terraform as source of truth

**infra/terraform** defines GCP resources and outputs infra-derived values (bucket, project, zone, VM name, Pub/Sub, etc.). **tools/repo/vars_contract.py** defines the repo vars contract (required, optional, secrets) and default values for behavioral vars (e.g. BMT_STATUS_CONTEXT, BMT_HANDSHAKE_TIMEOUT_SEC). Export combines both: Terraform for infra vars, contract defaults for the rest.

```bash
just terraform-export-vars          # Print key=value
just terraform-export-vars-apply    # Apply to GitHub (gh variable set)
```

Infra-derived vars come from Terraform outputs ([outputs.tf](../infra/terraform/outputs.tf)); the mapping to GitHub var names and the full list are in **tools/repo/vars_contract.py**. **Secrets** (`GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID`, `BMT_DISPATCH_APP_PRIVATE_KEY`) are set manually and never in Terraform.

---

## Environment contract (Python + branch-status)

The "contract" is built from **tools/repo/vars_contract.py** (Python) and **infra/branch-status-context.json**:

- **required** / **optional** / **secrets_not_in_terraform** — Defined in `REPO_VARS_CONTRACT` in repo_vars_contract.py.
- **defaults** — Behavioral var defaults (e.g. BMT_STATUS_CONTEXT, BMT_HANDSHAKE_TIMEOUT_SEC) in the same module.
- **repo_var_vs_branch_required_status_context** (in branch-status-context.json) — Ensures `BMT_STATUS_CONTEXT` matches branch protection.

Tooling (`tools/repo/gh_repo_vars.py`, `tools/repo/gh_validate_vm_vars.py`, `tools/repo/gh_show_env.py`) uses this contract to check and apply repo vars and to validate VM metadata.

---

## Repository variables (GitHub)

Set in **Settings → Secrets and variables → Actions → Variables** (or via `gh variable set`). Canonical names only; no aliases (e.g. no `VM_NAME` or `BUCKET`). Set `GCP_PROJECT` explicitly; do not rely on a derived project fallback.

### Required (github_repo_vars)

| Variable | Purpose |
| --- | --- |
| `GCS_BUCKET` | GCS bucket name. |
| `GCP_WIF_PROVIDER` | Workload Identity Federation provider for CI. (Secret; set manually.) |
| `GCP_SA_EMAIL` | Service account email for WIF auth. (From Terraform output `service_account`.) |
| `GCP_PROJECT` | GCP project ID for VM operations. |
| `GCP_ZONE` | VM zone (e.g. `europe-west4-a`). |
| `BMT_VM_NAME` | VM instance name (workflow starts it; VM can stop itself after one run). |
| `BMT_PUBSUB_SUBSCRIPTION` | Pub/Sub subscription for VM trigger delivery (from Terraform output). |
| `BMT_STATUS_CONTEXT` | Commit status name (from Terraform; must match branch protection). |
| `BMT_HANDSHAKE_TIMEOUT_SEC` | Handshake timeout seconds (from Terraform). |

These are set from Terraform via `just terraform-export-vars-apply`; do not set them manually as optional overrides.

### Optional (common)

| Variable | Default | Purpose |
| --- | --- | --- |
| `BMT_VM_POOL` | — | **Recommended.** Comma-separated VM names (e.g. `vm1,vm2`). Pool is explicit and version-controlled; each name is verified via Compute SDK. When set, select-available-vm assigns by run ID so concurrent workflows get different VMs. If unset, uses `BMT_VM_NAME` only. Pool must never be empty. |
| `BMT_VM_POOL_LABEL` | — | Optional. Label filter to discover pool from GCP (e.g. `bmt-gate:true`). Use when you prefer discovery by instance label over an explicit list. Overrides `BMT_VM_POOL` when set. |
| `BMT_HANDSHAKE_TIMEOUT_SEC_REUSE_RUNNING` | `"600"` | When select-available-vm reuses a RUNNING VM (no TERMINATED available), this timeout is used for handshake so the workflow does not fail while the VM finishes the previous trigger. Consecutive runs within the VM idle window reuse the same VM without cold boot. |
| `BMT_IDLE_TIMEOUT_SEC` | `"600"` (VM/env) | Idle period in seconds after each run with no new trigger before the VM exits and self-stops. Set in VM metadata or env; `0` = exit immediately after one run (legacy behavior). |
| `BMT_TRIGGER_STALE_SEC` | `"900"` | Stale-trigger threshold used in preflight diagnostics/summaries. |
| `BMT_DISPATCH_APP_ID` | — | GitHub App ID for BMT handoff dispatch (see [Secrets and variables](#secrets-and-variables-github-actions)). Required for the “Trigger BMT” job in `dummy-build-and-test.yml`. |

**Behavioral constants (not repo vars):** Runtime context label, trigger metadata keep-recent count, VM stabilization/recovery values, preempt-on-PR-stale, and stale trigger age in hours are fixed in **gcp/code/lib/bmt_config.py** (e.g. `DEFAULT_RUNTIME_CONTEXT`, `TRIGGER_METADATA_KEEP_RECENT`, `VM_STABILIZATION_SEC`). They are not configurable via environment or Terraform.

Omitted vars inherit from current GitHub repo context first, then from Terraform outputs (when you run `just terraform-export-vars`) or contract defaults. Optional overrides can be passed via `just repo-vars-apply --config <path>` with a TOML/JSON file.

**VM pool (concurrent runs):** For two or more VMs, set **`BMT_VM_POOL`** to a comma-separated list of instance names (e.g. `bmt-vm-1,bmt-vm-2`). This is the recommended approach: explicit, version-controlled, and verified via the Compute SDK. Leave `BMT_VM_POOL_LABEL` unset unless you prefer discovery by instance label.

For `BMT_STATUS_CONTEXT`, `tools/repo/gh_repo_vars.py` resolves the desired value from the effective branch rules using **infra/branch-status-context.json**. This keeps branch protection and repo variables aligned. Values for `BMT_STATUS_CONTEXT` and `BMT_HANDSHAKE_TIMEOUT_SEC` come from Terraform (static config); export with `just terraform-export-vars-apply`.

### Useful commands

```bash
just terraform-export-vars     # Print Terraform-sourced vars
just terraform-export-vars-apply  # Apply them to GitHub
just repo-vars-check           # Check repo vars against Terraform/contract
just repo-vars-apply           # Apply vars to GitHub (from Terraform + optional override file)
just show-env                  # Print env var names used by CI, VM, tools
just validate-vm-vars          # Ensure repo vars match VM metadata
just sync-vm-metadata         # Sync startup-critical VM metadata from repo
```

---

## VM metadata

The workflow syncs **VM metadata** from repo config so the VM uses the same bucket without a manual bootstrap rerun. Keys synced:

- **GCS_BUCKET** (required)
- **BMT_REPO_ROOT** (optional; default `/opt/bmt`)
- **BMT_IDLE_TIMEOUT_SEC** (optional; default `600`) — Idle period in seconds after each run before VM exits; `0` = exit immediately after one run.
- **startup-script** (set from packaged `cli.resources/startup_entrypoint.sh` by `sync-vm-metadata`)
- **startup-script-url** (cleared by workflow metadata sync; optional/manual URL mode can be set by `gcp/code/bootstrap/set_startup_script_url.sh`)

`sync-vm-metadata` also validates that required bootstrap code objects exist in `<code-root>` before starting the VM.
This includes pinned UV tool artifacts under `<code-root>/_tools/uv/linux-x86_64/`.

Defined under `vm_metadata` in the Terraform-backed contract. Consistency check `repo_vs_vm_metadata` ensures `GCS_BUCKET` matches between repo vars and VM metadata.

---

## VM runtime environment

On the VM, these are the runtime credentials expected by `vm_watcher.py`. For every enabled repository in `gcp/code/config/github_repos.json`, the matching App credential triple must be resolvable at startup:

| Variable | Purpose |
| --- | --- |
| `GITHUB_APP_TEST_ID`, `GITHUB_APP_TEST_INSTALLATION_ID`, `GITHUB_APP_TEST_PRIVATE_KEY` | GitHub App credentials (test). |
| `GITHUB_APP_PROD_ID`, `GITHUB_APP_PROD_INSTALLATION_ID`, `GITHUB_APP_PROD_PRIVATE_KEY` | GitHub App credentials (production). |
| `GH_APP_TEST_ID`, `GH_APP_TEST_INSTALLATION_ID`, `GH_APP_TEST_PRIVATE_KEY` | Alias fallback names accepted by VM/runtime tooling (canonical `GITHUB_APP_*` takes precedence). |
| `GH_APP_PROD_ID`, `GH_APP_PROD_INSTALLATION_ID`, `GH_APP_PROD_PRIVATE_KEY` | Alias fallback names accepted by VM/runtime tooling (canonical `GITHUB_APP_*` takes precedence). |
| `BMT_UV_BIN` | Optional debug override for uv binary path on VM (bootstrap default is self-heal from pinned code artifact). |

Repository mapping is in **gcp/code/config/github_repos.json**. See [../gcp/code/lib/github_auth.py](../gcp/code/lib/github_auth.py) for resolution logic.

---

## Secrets and variables (GitHub Actions)

| Name | Type | Purpose |
| --- | --- | --- |
| `BMT_DISPATCH_APP_ID` | **Variable** | GitHub App ID used to mint a token for dispatching the BMT handoff workflow (`workflow_dispatch`). Set in **Variables** (not Secrets); same name in test and prod repos. |
| `BMT_DISPATCH_APP_PRIVATE_KEY` | **Secret** | GitHub App private key (PEM) used by the CI workflow with `actions/create-github-app-token@v2` to obtain that dispatch token. |

**IDE warning:** Editors using the GitHub Actions JSON schema may show “Context access might be invalid” for `vars.BMT_DISPATCH_APP_ID` and `secrets.BMT_DISPATCH_APP_PRIVATE_KEY`. The schema only knows built-in names (e.g. `GITHUB_TOKEN`); these custom names are valid at runtime once the variable and secret are set in **Settings → Variables and secrets → Actions**.

**Migration:** If you previously used `APP_TEST_ID` / `APP_TEST_PRIVATE_KEY`, set **variable** `BMT_DISPATCH_APP_ID` and **secret** `BMT_DISPATCH_APP_PRIVATE_KEY` (same values). Prod repos use the same names with the prod App’s credentials.

---

## Bucket structure (summary)

Use:

- `<code-root> = gs://<bucket>/code`
- `<runtime-root> = gs://<bucket>/runtime`

`gcp/code` is the manual-sync source of truth for `<code-root>` only.
`gcp/runtime` is the manual-sync source for runtime seed artifacts under `<runtime-root>`.
Local large WAV corpora remain under `data/` (not inside `gcp/runtime`).
Local mirror policy details: [../gcp/README.md](../gcp/README.md).

- **`<code-root>/...`** — deployable watcher/orchestrator/manager/bootstrap/config mirrored from `gcp/code`.
- **`<code-root>/pyproject.toml`** — VM runtime package (build-system + `lib` package). Bootstrap `install_deps.sh` runs `pip install -e ".[vm]"` from the code root so the `lib` package and VM deps are installed in the venv; no PYTHONPATH.
- **`<code-root>/uv.lock`** — optional pinned lock for `gcp/code` when using `uv sync` from code root.
- **`<code-root>/_tools/uv/linux-x86_64/uv`** — pinned uv binary uploaded by `just sync-gcp`.
- **`<code-root>/_tools/uv/linux-x86_64/uv.sha256`** — pinned uv checksum tracked in repo and verified at boot.
- **`<runtime-root>/triggers/runs/<workflow_run_id>.json`** — Run trigger (CI writes; VM deletes after process).
- **`<runtime-root>/triggers/acks/<workflow_run_id>.json`** — VM handshake ack.
- **`<runtime-root>/triggers/status/<workflow_run_id>.json`** — VM progress heartbeat.
- **`<runtime-root>/_meta/runtime_seed_manifest.json`** — runtime seed sync manifest (written by `tools/remote/bucket_sync_runtime_seed.py`).
- **`<runtime-root>/<project>/runners/<preset>/...`** — Runner bundles (uploaded by workflow/tools).
- **`<runtime-root>/<project>/inputs/...`** — Runtime input objects in bucket; local source is explicit upload from `data/...` (keep `gcp/runtime/**/inputs` as placeholders only).
- **`<runtime-root>/<results_prefix>/current.json`** — Pointer (`latest`, `last_passing` run_id); updated by watcher.
- **`<runtime-root>/<results_prefix>/snapshots/<run_id>/`** — Per-run artifacts (`latest.json`, `ci_verdict.json`, logs).

Pointer semantics and retention: [architecture.md](architecture.md#results-contract) and [architecture.md](architecture.md#implementation--data-flow).

---

## Pyproject files

The repo has three `pyproject.toml` files:

| Location | Purpose | Necessary? |
| --- | --- | --- |
| **Root** (`pyproject.toml`) | Installable package **bmt-gcloud**: exposes `gcp` and `tools` for CLI and tests. Workspace members: `.github/bmt`, `gcp/code`. CLI and tests assume an **editable install from repo root** (`uv sync` or `pip install -e .`); no PYTHONPATH or sys.path. | **Yes** |
| **`.github/bmt/pyproject.toml`** | BMT CLI package: build backend, `bmt` entrypoint, depends on **bmt-gcloud**. All workflows run `uv sync` from repo root (so bmt-gcloud and bmt are installed) and `uv run bmt <cmd>`. | **Yes** |
| **`gcp/code/pyproject.toml`** | VM runtime package (**bmt-vm-runtime**): build-system, installable **lib** package. Bootstrap `install_deps.sh` runs `pip install -e ".[vm]"` from the code root so the venv has `lib` and VM deps; no PYTHONPATH. | **Yes** — VM code uses `from lib.*`; image build and local VM-style runs rely on this. |

---

## Branch protection

Require the **commit status** named by `BMT_STATUS_CONTEXT` (value from Terraform) to pass before merge.
The runtime context label (e.g. "BMT Runtime") is a non-gating constant in **gcp/code/lib/bmt_config.py** (`DEFAULT_RUNTIME_CONTEXT`) and must not be used as a protected merge gate.

GitHub branch rules are the source of truth for that context. Keep branch rules and repo vars aligned via:

```bash
just repo-vars-check
just repo-vars-apply
```
