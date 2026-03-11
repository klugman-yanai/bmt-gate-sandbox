# Configuration

This document describes **current** configuration: Terraform as source of truth for non-secret repo vars, VM metadata, runtime env, secrets, and bucket layout. The canonical source for variable definitions is **infra/terraform** (variables + outputs) and [infra/terraform/repo-vars-mapping.json](../infra/terraform/repo-vars-mapping.json). Secrets are documented in [../infra/README.md](../infra/README.md). For a quick start see [../README.md](../README.md).

---

## Terraform as source of truth

**infra/terraform** defines all non-secret configuration. Export GitHub repo variables from Terraform outputs:

```bash
just terraform-export-vars          # Print key=value
just terraform-export-vars-apply    # Apply to GitHub (gh variable set)
```

Mapping from Terraform output keys to GitHub var names: [infra/terraform/repo-vars-mapping.json](../infra/terraform/repo-vars-mapping.json). Required and optional vars are listed there; **secrets** (`GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID`, `BMT_DISPATCH_APP_PRIVATE_KEY`) are set manually and never in Terraform.

---

## Environment contract (Terraform-backed)

The "contract" is built from **infra/terraform/repo-vars-mapping.json** and **infra/branch-status-context.json**:

- **required_from_terraform** / **optional_from_terraform** — Which GitHub vars are populated from Terraform outputs.
- **secrets_not_in_terraform** — Vars you must set manually (WIF, GitHub App).
- **defaults** — Optional defaults (e.g. `BMT_STATUS_CONTEXT`, `BMT_RUNTIME_CONTEXT`).
- **repo_var_vs_branch_required_status_context** (in branch-status-context.json) — Ensures `BMT_STATUS_CONTEXT` matches branch protection.

Tooling (`tools/gh_repo_vars.py`, `tools/gh_validate_vm_vars.py`, `tools/gh_show_env.py`) uses this contract to check and apply repo vars and to validate VM metadata.

---

## Repository variables (GitHub)

Set in **Settings → Secrets and variables → Actions → Variables** (or via `gh variable set`). Canonical names only; no aliases (e.g. no `VM_NAME` or `BUCKET`). Set `GCP_PROJECT` explicitly; do not rely on a derived project fallback.

### Required (github_repo_vars)

| Variable | Purpose |
|----------|---------|
| `GCS_BUCKET` | GCS bucket name. |
| `GCP_WIF_PROVIDER` | Workload Identity Federation provider for CI. (Secret; set manually.) |
| `GCP_SA_EMAIL` | Service account email for WIF auth. (From Terraform output `service_account`.) |
| `GCP_PROJECT` | GCP project ID for VM operations. |
| `GCP_ZONE` | VM zone (e.g. `europe-west4-a`). |
| `BMT_VM_NAME` | VM instance name (workflow starts it; VM can stop itself after one run). |
| `BMT_PUBSUB_SUBSCRIPTION` | Pub/Sub subscription for VM trigger delivery (from Terraform output). |

### Optional (common)

| Variable | Default | Purpose |
|----------|---------|---------|
| `BMT_STATUS_CONTEXT` | `"BMT Gate"` | Commit status name; must match branch protection. Effective value is sourced from branch rules via consistency checks. |
| `BMT_RUNTIME_CONTEXT` | `"BMT Runtime"` | Non-gating runtime check-run context for live progress and terminal runtime outcome. |
| `BMT_RUNTIME_BACKEND` | `"vm"` | Runtime dispatcher backend (`vm` or `cloud_run_job`). |
| `BMT_CLOUD_RUN_JOB` | — | Cloud Run Job name when `BMT_RUNTIME_BACKEND=cloud_run_job`. |
| `BMT_CLOUD_RUN_REGION` | — | Cloud Run region when `BMT_RUNTIME_BACKEND=cloud_run_job`. |
| `BMT_HANDSHAKE_TIMEOUT_SEC` | `"180"` | Timeout for runtime handshake wait. |
| `BMT_HANDSHAKE_TIMEOUT_SEC_REUSE_RUNNING` | `"600"` | When select-available-vm reuses a RUNNING VM (no TERMINATED available, e.g. after cancel-in-progress), this timeout is used for handshake so the workflow does not fail while the VM finishes the previous trigger. Only used when a RUNNING VM was selected. |
| `BMT_PREEMPT_ON_PR_STALE_QUEUE` | `"1"` | If stale queue files exist for PR runs, preflight cleanup may force clean runtime restart to avoid stalled handoffs. |
| `BMT_TRIGGER_STALE_SEC` | `"900"` | Stale-trigger threshold used in preflight diagnostics/summaries. |
| `BMT_TRIGGER_METADATA_KEEP_RECENT` | `"2"` | Number of recent trigger metadata files (`acks/status`) retained after cleanup. |
| `BMT_DISPATCH_APP_ID` | — | GitHub App ID for BMT handoff dispatch (see [Secrets and variables](#secrets-and-variables-github-actions)). Required for the “Trigger BMT” job in `dummy-build-and-test.yml`. |

Omitted vars inherit from current GitHub repo context first, then from Terraform outputs (when you run `just terraform-export-vars`) or contract defaults. Optional overrides can be passed via `just repo-vars-apply --config <path>` with a TOML/JSON file.

For `BMT_STATUS_CONTEXT`, `tools/gh_repo_vars.py` resolves the desired value from the effective branch rules using **infra/branch-status-context.json**. This keeps branch protection and repo variables aligned.

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
- **startup-script** (set from packaged `cli.resources/startup_wrapper.sh` by `sync-vm-metadata`)
- **startup-script-url** (cleared by workflow metadata sync; optional/manual URL mode can be set by `gcp/code/bootstrap/setup_vm_startup.sh`)

`sync-vm-metadata` also validates that required bootstrap code objects exist in `<code-root>` before starting the VM.
This includes pinned UV tool artifacts under `<code-root>/_tools/uv/linux-x86_64/`.

Defined under `vm_metadata` in the Terraform-backed contract. Consistency check `repo_vs_vm_metadata` ensures `GCS_BUCKET` matches between repo vars and VM metadata.

---

## VM runtime environment

On the VM, these are the runtime credentials expected by `vm_watcher.py`. For every enabled repository in `gcp/code/config/github_repos.json`, the matching App credential triple must be resolvable at startup:

| Variable | Purpose |
|----------|---------|
| `GITHUB_APP_TEST_ID`, `GITHUB_APP_TEST_INSTALLATION_ID`, `GITHUB_APP_TEST_PRIVATE_KEY` | GitHub App credentials (test). |
| `GITHUB_APP_PROD_ID`, `GITHUB_APP_PROD_INSTALLATION_ID`, `GITHUB_APP_PROD_PRIVATE_KEY` | GitHub App credentials (production). |
| `GH_APP_TEST_ID`, `GH_APP_TEST_INSTALLATION_ID`, `GH_APP_TEST_PRIVATE_KEY` | Alias fallback names accepted by VM/runtime tooling (canonical `GITHUB_APP_*` takes precedence). |
| `GH_APP_PROD_ID`, `GH_APP_PROD_INSTALLATION_ID`, `GH_APP_PROD_PRIVATE_KEY` | Alias fallback names accepted by VM/runtime tooling (canonical `GITHUB_APP_*` takes precedence). |
| `BMT_UV_BIN` | Optional debug override for uv binary path on VM (bootstrap default is self-heal from pinned code artifact). |

Repository mapping is in **gcp/code/config/github_repos.json**. See [../gcp/code/lib/github_auth.py](../gcp/code/lib/github_auth.py) for resolution logic.

---

## Secrets and variables (GitHub Actions)

| Name | Type | Purpose |
|------|------|---------|
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
- **`<code-root>/pyproject.toml`** — VM runtime dependency contract for watcher execution.
- **`<code-root>/uv.lock`** — pinned lock used by `bootstrap/install_deps.sh` (`uv sync --extra vm --frozen`).
- **`<code-root>/_tools/uv/linux-x86_64/uv`** — pinned uv binary uploaded by `just sync-gcp`.
- **`<code-root>/_tools/uv/linux-x86_64/uv.sha256`** — pinned uv checksum tracked in repo and verified at boot.
- **`<runtime-root>/triggers/runs/<workflow_run_id>.json`** — Run trigger (CI writes; VM deletes after process).
- **`<runtime-root>/triggers/acks/<workflow_run_id>.json`** — VM handshake ack.
- **`<runtime-root>/triggers/status/<workflow_run_id>.json`** — VM progress heartbeat.
- **`<runtime-root>/_meta/runtime_seed_manifest.json`** — runtime seed sync manifest (written by `tools/bucket_sync_runtime_seed.py`).
- **`<runtime-root>/<project>/runners/<preset>/...`** — Runner bundles (uploaded by workflow/tools).
- **`<runtime-root>/<project>/inputs/...`** — Runtime input objects in bucket; local source is explicit upload from `data/...` (keep `gcp/runtime/**/inputs` as placeholders only).
- **`<runtime-root>/<results_prefix>/current.json`** — Pointer (`latest`, `last_passing` run_id); updated by watcher.
- **`<runtime-root>/<results_prefix>/snapshots/<run_id>/`** — Per-run artifacts (`latest.json`, `ci_verdict.json`, logs).

Pointer semantics and retention: [architecture.md](architecture.md#results-contract) and [implementation.md](implementation.md#data-flow).

---

## Branch protection

Require the **commit status** named by `BMT_STATUS_CONTEXT` (default: **BMT Gate**) to pass before merge.
`BMT_RUNTIME_CONTEXT` is non-gating runtime visibility (progress + terminal runtime outcome) and must not be used as a protected merge gate.

GitHub branch rules are the source of truth for that context. Keep branch rules and repo vars aligned via:

```bash
just repo-vars-check
just repo-vars-apply
```
