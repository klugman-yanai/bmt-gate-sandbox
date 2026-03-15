# Configuration

This document describes **current** configuration: Pulumi for infra-derived repo vars and a Python contract ([tools/repo/vars_contract.py](../tools/repo/vars_contract.py)) for required/optional/secrets and defaults.

---

## Where to set what (at a glance)

One place to answer **"where do I set X?"** — three tiers.

### Tier 1 — You set these

| Setting | Where | How |
|--------|--------|-----|
| **Infra (required)** | `infra/pulumi/bmt.tfvars.json` | `gcp_project`, `gcp_zone`, `gcs_bucket`, `service_account` (four required). Optional: `bmt_vm_name` (default `bmt-gate-blue`). See [infra/README.md](../infra/README.md). |
| **CI vars (optional in file)** | `infra/pulumi/bmt.tfvars.json` → `github_vars` | Optional block `github_vars` with `GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID`. Synced to GitHub when you run `just pulumi`. If omitted, set them manually in GitHub. |
| **Secrets** | GitHub (Variables / Secrets) or GCP | **GCP_WIF_PROVIDER**, **BMT_DISPATCH_APP_ID** — set in GitHub if not in `github_vars`. **BMT_DISPATCH_APP_PRIVATE_KEY** — GitHub Secret when this repo mints the dispatch token. VM-side App credentials in GCP Secret Manager. |

Run **`just pulumi`** to apply infra and push all Tier 1 repo vars (from Pulumi + optional `github_vars`) to GitHub.

### Tier 2 — Set by Tier 1 (do not edit by hand)

| Setting | Source |
|--------|--------|
| **GCS_BUCKET**, **GCP_PROJECT**, **GCP_SA_EMAIL**, **BMT_LIVE_VM** | Pulumi stack output → synced to GitHub Variables by `just pulumi`. |
| **GCP_WIF_PROVIDER**, **BMT_DISPATCH_APP_ID** | If present in `bmt.tfvars.json` → `github_vars`, synced by `just pulumi`. Else set once in GitHub. |
| **VM metadata** (GCS_BUCKET, BMT_REPO_ROOT, BMT_IDLE_TIMEOUT_SEC, startup-script) | Workflow `sync-vm-metadata` from repo config. |

### Tier 3 — Derived or in code (do not set as vars)

| Setting | Source |
|--------|--------|
| **BMT_PUBSUB_SUBSCRIPTION**, **BMT_PUBSUB_TOPIC**, **BMT_VM_POOL**, **BMT_STATUS_CONTEXT**, **GCP_ZONE** | Derived from BMT_LIVE_VM and constants in code. |
| **Handshake timeouts**, **IDLE_TIMEOUT_SEC**, **TRIGGER_STALE_SEC**, **VM_STABILIZATION_SEC**, etc. | Constants in [gcp/image/config/bmt_config.py](../gcp/image/config/bmt_config.py). No repo var or env. |

**Useful commands:** `just pulumi` (apply + push vars), `just validate` (check repo vars vs Pulumi/contract and VM metadata), `just show-env` (print env var names).

---

## Pulumi as source of truth

**infra/pulumi** defines GCP resources and exports infra-derived values (bucket, project, zone, VM name, Pub/Sub, etc.). **tools/repo/vars_contract.py** defines the repo vars contract (required, optional, secrets) and default values for vars that have a default. Export combines both: Pulumi for infra vars, contract defaults for the rest.

```bash
just pulumi                         # Preflight, apply infra, push repo vars to GitHub
just pulumi --verbose              # Same with full output
```

Infra-derived vars come from Pulumi stack outputs; the mapping to GitHub var names and the full list are in **tools/repo/vars_contract.py**. **Secrets** (`GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID`) are set manually and never in Pulumi. The GitHub App private key may live in the bucket; it is not a repo var when not used at repo level.

---

## Environment contract (Python + branch-status)

The "contract" is built from **tools/repo/vars_contract.py** (Python) and **infra/branch-status-context.json**:

- **required** / **optional** / **secrets_not_in_infra** — Defined in `REPO_VARS_CONTRACT` in repo_vars_contract.py.
- **defaults** — Var defaults (e.g. BMT_STATUS_CONTEXT, BMT_REPO_ROOT) in the same module.
- **repo_var_vs_branch_required_status_context** (in branch-status-context.json) — Ensures `BMT_STATUS_CONTEXT` matches branch protection.

Tooling (`tools/repo/gh_repo_vars.py`, `tools/repo/gh_validate_vm_vars.py`, `tools/repo/gh_show_env.py`) uses this contract to check and apply repo vars and to validate VM metadata.

---

## What must be an env var vs constant

Repo vars (GitHub Variables) and env vars are only for values that **vary per repo or deployment** or are **secrets**. Everything else is a **constant** in code (no user override).

### What you actually configure

Realistically you only change:

| Where | What |
|-------|------|
| **Repo** | Which GitHub repo (clone/origin). |
| **Declarative config** (`infra/pulumi/bmt.tfvars.json`) | **Four required:** `gcp_project`, `gcp_zone`, `gcs_bucket`, `service_account`. **Optional:** `bmt_vm_name` (default `bmt-gate-blue`). Run `just pulumi` to apply and push to GitHub as `GCS_BUCKET`, `GCP_PROJECT`, `GCP_SA_EMAIL`, `BMT_LIVE_VM`. Zone is not exported; it is fixed in code at runtime. See [infra/README.md](../../infra/README.md). |
| **GitHub (vars/secrets)** | **GCP_WIF_PROVIDER**, **BMT_DISPATCH_APP_ID** — optional in `bmt.tfvars.json` under `github_vars` (synced by `just pulumi`), or set by hand in GitHub. **BMT_DISPATCH_APP_PRIVATE_KEY** — GitHub Secret when this repo mints the dispatch token. |

So: project, zone, bucket, and SA are the required four in `bmt.tfvars.json`; VM name is optional. You can add `github_vars` to the same file to sync GCP_WIF_PROVIDER and BMT_DISPATCH_APP_ID to GitHub, or set them once in GitHub.

### Not repo vars — derived or declarative (YAGNI)

These are derived in code or come from Pulumi/constants; do not set as GitHub variables:

| Name | Source |
|------|--------|
| **BMT_PUBSUB_SUBSCRIPTION** | Derived: `bmt-vm-` + **BMT_LIVE_VM** (BmtConfig.effective_pubsub_subscription). |
| **BMT_PUBSUB_TOPIC** | Constant: `bmt-triggers` (constants.PUBSUB_TOPIC_NAME). |
| **BMT_REPO_ROOT** | Default in code: `/opt/bmt` (DEFAULT_REPO_ROOT). Pulumi can override VM metadata only. |
| **BMT_VM_POOL** | Derived when **BMT_LIVE_VM** ends with `-blue` or `-green`: `<base>-blue,<base>-green`. Else single-VM from BMT_LIVE_VM. |
| **BMT_STATUS_CONTEXT** | Constant in code: `BMT Gate` (constants.STATUS_CONTEXT). Branch protection must match. |
| **GCP_ZONE** | Constant: `europe-west4-a` (europe-west4 only; not a repo var). |

### Not repo vars — constants in code (do not override)

These are **behavioral constants** in **gcp/image/config/bmt_config.py**. Code uses the default; there is no repo var or env for them.

| Name (in code) | Purpose | Value |
|----------------|---------|--------|
| **BMT_HANDSHAKE_TIMEOUT_SEC** | How long CI waits for VM handshake ack. | 420s (BmtConfig default). |
| **BMT_HANDSHAKE_TIMEOUT_SEC_REUSE_RUNNING** | Handshake timeout when reusing a RUNNING VM. | 600s. |
| **DEFAULT_REPO_ROOT** | Repo root on VM when not set via metadata. | `/opt/bmt`. |
| **DEFAULT_RUNTIME_CONTEXT** | Label for runtime Check Run (non-gating). | `BMT Runtime`. |
| **IDLE_TIMEOUT_SEC** | Idle period before VM self-stops. | 600. |
| **TRIGGER_STALE_SEC**, **STALE_TRIGGER_AGE_HOURS** | Stale trigger thresholds. | 900, 2. |
| **VM_STABILIZATION_SEC**, **VM_START_RECOVERY_ATTEMPTS**, **VM_STOP_WAIT_TIMEOUT_SEC** | VM lifecycle timing. | Fixed in module. |
| **TRIGGER_METADATA_KEEP_RECENT** | How many trigger metadata entries to keep. | 2. |

Handoff workflow **env** does not set `BMT_HANDSHAKE_TIMEOUT_SEC`; the CLI uses `get_config().bmt_handshake_timeout_sec`, which falls back to the model default when unset.

### Not repo var — secret in bucket or caller

| Name | Why not repo var |
|------|-------------------|
| **BMT_DISPATCH_APP_PRIVATE_KEY** | When the GitHub App private key (PEM) is stored in the bucket and the **caller repo** (e.g. build-and-test) uses it to dispatch, bmt-gcloud does not need this as a repo secret. Only set as a repo secret when CI in this repo must mint the dispatch token itself. |

### Workflow-only / tool-only env (not in repo vars contract)

Used by jobs or local tools; not part of the canonical repo vars list:

- **BMT_VM_POOL_LABEL** — Optional. Label filter to discover VM pool from GCP (overrides derived blue/green pool). **BMT_VM_POOL** is no longer a repo var; pool is derived from **BMT_LIVE_VM** when name ends with `-blue`/`-green`.
- **BMT_CONFIG**, **BMT_FORCE**, **BMT_CONTRACT**, **BMT_PRUNE_EXTRA** — Tool flags for repo-vars (paths/behavior). Use `--apply` with `gh_repo_vars` or Pulumi repo vars to write vars; `just pulumi` passes `--apply` automatically.
- **BMT_SRC_DIR**, **BMT_DELETE**, **BMT_FORCE**, **GCS_BUCKET** — Bucket sync/verify tools.
- **GITHUB_TOKEN**, **GITHUB_RUN_ID**, **GITHUB_REPOSITORY**, etc. — Set by Actions; not repo vars.

---

## Repository variables (GitHub)

Set in **Settings → Secrets and variables → Actions → Variables** (or via `gh variable set`). Canonical names only; no aliases (e.g. no `VM_NAME` or `BUCKET`). Set `GCP_PROJECT` explicitly; do not rely on a derived project fallback.

### Repo variables: from Pulumi vs set by hand

| Variable | Set by | Purpose |
| --- | --- | --- |
| `GCS_BUCKET` | **Pulumi export** (from `bmt.tfvars.json` → `gcs_bucket`) | GCS bucket name. |
| `GCP_PROJECT` | **Pulumi export** (from `gcp_project`) | GCP project ID. |
| `GCP_SA_EMAIL` | **Pulumi export** (from `service_account`) | Service account for WIF and VM. |
| `BMT_LIVE_VM` | **Pulumi export** (from `bmt_vm_name`) | VM instance name. Declared in declarative config, not in GitHub UI. |
| `GCP_WIF_PROVIDER` | **You set in GitHub** | Workload Identity Federation provider for CI. |
| `BMT_DISPATCH_APP_ID` | **You set in GitHub** | GitHub App ID for workflow_dispatch. (Private key as repo secret when needed.) |

Run `just pulumi` (with `bmt.tfvars.json` filled in) to apply infra and push the first four to GitHub. Set `GCP_WIF_PROVIDER` and the App credentials manually in GitHub.

**Set by Pulumi (do not configure by hand):** `GCS_BUCKET`, `GCP_PROJECT`, `GCP_SA_EMAIL`, `BMT_LIVE_VM`. They are overwritten when you run `just pulumi`.

**Set by you (or from `github_vars` in bmt.tfvars.json):** `GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID`. If present in `bmt.tfvars.json` under `github_vars`, `just pulumi` syncs them to GitHub; otherwise set them once in GitHub.

**Remove from GitHub (obsolete / derived in code):** `BMT_PUBSUB_SUBSCRIPTION`, `BMT_PUBSUB_TOPIC`. Subscription and topic are derived from `BMT_LIVE_VM` and constants; keeping them as repo vars causes drift. Remove with `gh variable delete BMT_PUBSUB_SUBSCRIPTION` and `gh variable delete BMT_PUBSUB_TOPIC`.

**Optional / not from Pulumi export:** `GCP_ZONE` — workflows may default it (e.g. `europe-west4-a`). You can set it from Pulumi manually if needed: `gh variable set GCP_ZONE "$(cd infra/pulumi && pulumi stack output gcp_zone)"`. `BMT_STATUS_CONTEXT` is a constant in code; branch protection must match it; no need to set as a repo var.

### Optional / workflow-only (not in Pulumi export)

| Variable | Purpose |
| --- | --- |
| `BMT_VM_POOL_LABEL` | Label filter to discover VM pool from GCP (e.g. `bmt-gate:true`). Overrides derived blue/green pool when set. |
| `BMT_HANDSHAKE_TIMEOUT_SEC_REUSE_RUNNING` | `"600"` | When select-available-vm reuses a RUNNING VM (no TERMINATED available), this timeout is used for handshake so the workflow does not fail while the VM finishes the previous trigger. Consecutive runs within the VM idle window reuse the same VM without cold boot. |
| `BMT_IDLE_TIMEOUT_SEC` | `"600"` (VM/env) | Idle period in seconds after each run with no new trigger before the VM exits and self-stops. Set in VM metadata or env; `0` = exit immediately after one run (legacy behavior). |
| `BMT_TRIGGER_STALE_SEC` | `"900"` | Stale-trigger threshold used in preflight diagnostics/summaries. |
| `BMT_DISPATCH_APP_ID` | — | GitHub App ID for BMT handoff dispatch (see [Secrets and variables](#secrets-and-variables-github-actions)). Required for the “Trigger BMT” job in `dummy-build-and-test.yml`. |

**Behavioral constants (not repo vars):** Handshake timeouts, runtime context label, trigger metadata keep-recent count, VM stabilization/recovery values, preempt-on-PR-stale, and stale trigger age in hours are fixed in **gcp/image/config/bmt_config.py** (e.g. `DEFAULT_RUNTIME_CONTEXT`, `TRIGGER_METADATA_KEEP_RECENT`, `VM_STABILIZATION_SEC`). They are not configurable via environment or Pulumi.

Omitted vars inherit from current GitHub repo context first, then from Pulumi outputs (when you run `just pulumi`) or contract defaults.

**VM pool (concurrent runs):** When using blue/green VM names (e.g. **BMT_LIVE_VM** = `bmt-gate-blue`), the VM pool is derived in code (no `BMT_VM_POOL` repo var) so you don’t set it manually. For other schemes, use **`BMT_VM_POOL_LABEL`** to discover VMs by GCP instance label.

**Status context:** The commit status name is a constant in code (`gcp/image/config/constants.py` → `STATUS_CONTEXT`). Configure branch protection to require that same name; there is no repo var.

### Useful commands

```bash
just pulumi                     # Preflight, apply, and push repo vars to GitHub
just validate                   # Check repo vars vs Pulumi/contract and VM metadata
just show-env                   # Print env var names used by CI, VM, tools
just sync-vm-metadata           # Sync startup-critical VM metadata from repo
```

---

## VM metadata

The workflow syncs **VM metadata** from repo config so the VM uses the same bucket without a manual bootstrap rerun. Keys synced:

- **GCS_BUCKET** (required)
- **BMT_REPO_ROOT** (optional; default `/opt/bmt`)
- **BMT_IDLE_TIMEOUT_SEC** (optional; default `600`) — Idle period in seconds after each run before VM exits; `0` = exit immediately after one run.
- **startup-script** (set from packaged `cli.resources/startup_entrypoint.sh` by `sync-vm-metadata`)
- **startup-script-url** (cleared by workflow metadata sync; optional/manual URL mode can be set by `gcp/image/scripts/set_startup_script_url.py`)

`sync-vm-metadata` also validates that required VM code objects exist in `<code-root>` before starting the VM.
This includes pinned UV tool artifacts under `<code-root>/_tools/uv/linux-x86_64/`.

Defined under `vm_metadata` in the Pulumi-backed contract. Consistency check `repo_vs_vm_metadata` ensures `GCS_BUCKET` matches between repo vars and VM metadata.

---

## VM runtime environment

On the VM, these are the runtime credentials expected by `vm_watcher.py`. For every enabled repository in `gcp/image/config/github_repos.json`, the matching App credential triple must be resolvable at startup:

| Variable | Purpose |
| --- | --- |
| `GITHUB_APP_TEST_ID`, `GITHUB_APP_TEST_INSTALLATION_ID`, `GITHUB_APP_TEST_PRIVATE_KEY` | GitHub App credentials (test). |
| `GITHUB_APP_PROD_ID`, `GITHUB_APP_PROD_INSTALLATION_ID`, `GITHUB_APP_PROD_PRIVATE_KEY` | GitHub App credentials (production). |
| `GH_APP_TEST_ID`, `GH_APP_TEST_INSTALLATION_ID`, `GH_APP_TEST_PRIVATE_KEY` | Alias fallback names accepted by VM/runtime tooling (canonical `GITHUB_APP_*` takes precedence). |
| `GH_APP_PROD_ID`, `GH_APP_PROD_INSTALLATION_ID`, `GH_APP_PROD_PRIVATE_KEY` | Alias fallback names accepted by VM/runtime tooling (canonical `GITHUB_APP_*` takes precedence). |
| `BMT_UV_BIN` | Optional debug override for uv binary path on VM (bootstrap default is self-heal from pinned code artifact). |

Repository mapping is in **gcp/image/config/github_repos.json**. See [../gcp/image/lib/github_auth.py](../gcp/image/lib/github_auth.py) for resolution logic.

---

## Secrets and variables (GitHub Actions)

| Name | Type | Purpose |
| --- | --- | --- |
| `BMT_DISPATCH_APP_ID` | **Variable** | GitHub App ID used to mint a token for dispatching the BMT handoff workflow (`workflow_dispatch`). Set in **Variables** (not Secrets); same name in test and prod repos. |
| `BMT_DISPATCH_APP_PRIVATE_KEY` | **Secret** (optional) | GitHub App private key (PEM). Only needed at repo level when CI in this repo mints the dispatch token. When the key lives in the bucket and the **caller repo** dispatches, this repo does not need this secret. |

**IDE warning:** Editors using the GitHub Actions JSON schema may show “Context access might be invalid” for `vars.BMT_DISPATCH_APP_ID` and `secrets.BMT_DISPATCH_APP_PRIVATE_KEY`. The schema only knows built-in names (e.g. `GITHUB_TOKEN`); these custom names are valid at runtime once the variable and secret are set in **Settings → Variables and secrets → Actions**.

**Migration:** If you previously used `APP_TEST_ID` / `APP_TEST_PRIVATE_KEY`, set **variable** `BMT_DISPATCH_APP_ID` and **secret** `BMT_DISPATCH_APP_PRIVATE_KEY` (same values). Prod repos use the same names with the prod App’s credentials.

---

## Bucket structure (summary)

Use:

- `<code-root> = gs://<bucket>/code`
- `<runtime-root> = gs://<bucket>/runtime`

`gcp/image` is the manual-sync source of truth for `<code-root>` only.
`gcp/remote` is the manual-sync source for runtime seed artifacts under `<runtime-root>`.
Local large WAV corpora remain under `data/` (not inside `gcp/remote`).
Local mirror policy details: [../gcp/README.md](../gcp/README.md).

- **`<code-root>/...`** — deployable watcher/orchestrator/manager/vm scripts/config mirrored from `gcp/image`.
- **`<code-root>/pyproject.toml`** — VM runtime package (build-system + config package). Bootstrap `install_deps.py` runs `pip install -e ".[vm]"` from the code root so the config package and VM deps are installed in the venv; no PYTHONPATH.
- **`<code-root>/uv.lock`** — optional pinned lock for `gcp/image` when using `uv sync` from code root.
- **`<code-root>/_tools/uv/linux-x86_64/uv`** — pinned uv binary uploaded by `just deploy`.
- **`<code-root>/_tools/uv/linux-x86_64/uv.sha256`** — pinned uv checksum tracked in repo and verified at boot.
- **`<runtime-root>/triggers/runs/<workflow_run_id>.json`** — Run trigger (CI writes; VM deletes after process).
- **`<runtime-root>/triggers/acks/<workflow_run_id>.json`** — VM handshake ack.
- **`<runtime-root>/triggers/status/<workflow_run_id>.json`** — VM progress heartbeat.
- **`<runtime-root>/_meta/runtime_seed_manifest.json`** — runtime seed sync manifest (written by `tools/remote/bucket_sync_runtime_seed.py`).
- **`<runtime-root>/<project>/runners/<preset>/...`** — Runner bundles (uploaded by workflow/tools).
- **`<runtime-root>/<project>/inputs/...`** — Runtime input objects in bucket; local source is explicit upload from `data/...` (keep `gcp/remote/**/inputs` as placeholders only).
- **`<runtime-root>/<results_prefix>/current.json`** — Pointer (`latest`, `last_passing` run_id); updated by watcher.
- **`<runtime-root>/<results_prefix>/snapshots/<run_id>/`** — Per-run artifacts (`latest.json`, `ci_verdict.json`, logs).

Pointer semantics and retention: [architecture.md](architecture.md#results-contract) and [architecture.md](architecture.md#implementation--data-flow).

---

## Pyproject files and uv workspace

The repo uses a **uv workspace** ([uv docs](https://docs.astral.sh/uv/concepts/projects/workspaces/)): one lockfile at root, multiple packages. `uv lock` resolves all members; `uv run` and `uv sync` operate on the workspace root by default. To run a specific member: `uv run --package bmt …` or `uv run --package bmt-vm-runtime …`.

**Dependency groups (per-workspace):**

- **Root** — `[dependency-groups] dev`: tests, ruff, basedpyright, pytest, etc. Install with `uv sync --group dev`.
- **.github/bmt** — `[dependency-groups] dev`: ruff, basedpyright for lint/typecheck of the CLI. Install with `uv sync --package bmt --group dev`.
- **gcp/image** — `[dependency-groups] dev = []`; dev tooling runs from root. Optional runtime extra `[vm]` for PyJWT/cryptography when running VM watcher from root or on the image.

The repo has three `pyproject.toml` files:

| Location | Purpose | Necessary? |
| --- | --- | --- |
| **Root** (`pyproject.toml`) | Installable package **bmt-gcloud**: exposes `gcp` and `tools` for CLI and tests. Workspace members: `.github/bmt`, `gcp/image`. CLI and tests assume an **editable install from repo root** (`uv sync` or `pip install -e .`); no PYTHONPATH or sys.path. | **Yes** |
| **`.github/bmt/pyproject.toml`** | BMT CLI package: build backend, `bmt` entrypoint, depends on **bmt-gcloud**. **Portable:** copy `.github/bmt/` into a production repo's `.github/`; no workspace or parent-repo reference. In this repo the root provides `bmt-gcloud` via `tool.uv.sources` so the member resolves from the workspace. In production, use PyPI or set `tool.uv.sources` in the enclosing project. | **Yes** |
| **`gcp/image/pyproject.toml`** | VM runtime package (**bmt-vm-runtime**): build-system, installable packages. Bootstrap `install_deps.py` runs `pip install -e ".[vm]"` from the code root so the venv has config and VM deps; no PYTHONPATH. | **Yes** — VM code uses `from config.*`; image build and local VM-style runs rely on this. |

---

## Branch protection

Require the **commit status** named by `BMT_STATUS_CONTEXT` (value from Pulumi) to pass before merge.
The runtime context label (e.g. "BMT Runtime") is a non-gating constant in **gcp/image/lib/bmt_config.py** (`DEFAULT_RUNTIME_CONTEXT`) and must not be used as a protected merge gate.

GitHub branch rules are the source of truth for that context. Keep branch rules and repo vars aligned via:

```bash
just validate
```
