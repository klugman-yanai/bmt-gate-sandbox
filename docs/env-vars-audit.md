# Environment variables audit

This document lists **all relevant env vars** in the project, which are actually needed, which add unnecessary complexity or drift risk, and which can be automatically managed. It aligns with the principle: the user controls external configs (GCP, GitHub, branch protection); everything else should be derived, fixed, or auto-managed.

---

## 0. Absolute minimum the user must provide

The **minimum** required to run BMT CI and the VM:

| Where | Minimum |
|-------|--------|
| **Declarative (bmt.tfvars.json)** | **Required:** `gcp_project`, `gcp_zone`, `gcs_bucket`, `service_account` (Pulumi has no default for these). **Optional:** `bmt_vm_name` (default `bmt-gate-blue`), `startup_wrapper_script_path` (default relative to `infra/pulumi`). Zone is required in tfvars; at runtime it is not overridable via env (workflows default `vars.GCP_ZONE` to `europe-west4-a`). |
| **GitHub (manual)** | `GCP_WIF_PROVIDER` (so Actions can auth to GCP). For handoff: `BMT_DISPATCH_APP_ID` (and `BMT_DISPATCH_APP_PRIVATE_KEY` secret when this repo mints the token). |
| **GCP Secret Manager** | Per-repo GitHub App credentials (`GITHUB_APP_TEST_*`, `GITHUB_APP_PROD_*`) for each repo in `github_repos.json`. |
| **GitHub branch protection** | Require the status check named by the constant `STATUS_CONTEXT` in code. |

**Zone is in the minimum:** Pulumi has no default for `gcp_zone`, so you must set it in `bmt.tfvars.json` (e.g. `europe-west4-a`). At runtime we do not allow overriding zone via env; the value is fixed from config/code.

**VM name is not in the minimum.** Pulumi has a default `bmt_vm_name = "bmt-gate-blue"`. You only set it in `bmt.tfvars.json` when you want a different instance name (e.g. another region, or a different naming convention). If omitted, Pulumi and export use `bmt-gate-blue`; pool is then derived as `bmt-gate-blue` + `bmt-gate-green`.

### Why is the VM name “configurable” at all?

The system has to know **which GCE instance** is the BMT VM (to start it, sync metadata, derive Pub/Sub subscription, select from the pool). That identity is the instance **name**. So something has to specify it — but that something is a **default** (`bmt-gate-blue`), not a required input. You only override when:

- You want a different naming convention (e.g. `myorg-bmt-blue`).
- You run multiple BMT setups in the same project and need distinct instance names.
- You’re doing blue/green with a different base name.

So: VM name is **optional** in the minimum; it’s there so deployments can override when needed, not because every user must set it.

---

## 1. What the user actually controls

| Category | What user sets | Where |
|----------|----------------|-------|
| **GCP** | Project, bucket, service account, WIF provider | Declarative: `infra/pulumi/bmt.tfvars.json` → Pulumi → exported to GitHub as `GCP_PROJECT`, `GCS_BUCKET`, `GCP_SA_EMAIL`; **manually in GitHub**: `GCP_WIF_PROVIDER` |
| **VM name** | Primary VM (e.g. blue in blue/green) | Same: `bmt.tfvars.json` → Pulumi → `BMT_LIVE_VM` |
| **GitHub – dispatch** | App ID for workflow_dispatch | **GitHub repo variable**: `BMT_DISPATCH_APP_ID` |
| **GitHub – dispatch secret** | App private key (when this repo mints the token) | **GitHub repo secret**: `BMT_DISPATCH_APP_PRIVATE_KEY` |
| **GitHub – VM-side** | Per-repo App: ID, installation ID, private key | **GCP Secret Manager** (keys like `GITHUB_APP_TEST_ID`, `GITHUB_APP_TEST_INSTALLATION_ID`, `GITHUB_APP_TEST_PRIVATE_KEY`, and `GITHUB_APP_PROD_*`). Repo mapping in `gcp/image/config/github_repos.json`. |
| **Branch protection** | Status check name (context) | **GitHub branch rules**: required status check name. Must match the **constant** in code (`gcp/image/config/constants.py` → `STATUS_CONTEXT`). Not a repo var; code is source of truth. |

So in practice:

- **Declarative (bmt.tfvars.json):** `gcp_project`, `gcp_zone`, `gcs_bucket`, `service_account` (all required); `bmt_vm_name` optional (default `bmt-gate-blue`); `startup_wrapper_script_path` optional. Pulumi apply + export (via `just pulumi`) → four repo vars (GCS_BUCKET, GCP_PROJECT, GCP_SA_EMAIL, BMT_LIVE_VM). Zone is in Pulumi (required in tfvars) and output but **not** in the export contract; workflows use `vars.GCP_ZONE || 'europe-west4-a'`. At runtime zone is fixed in code (not overridable via env).
- **Manual in GitHub:** `GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID` (variable), `BMT_DISPATCH_APP_PRIVATE_KEY` (secret when needed).
- **GCP Secret Manager:** GitHub App credentials per `github_repos.json` (`GITHUB_APP_TEST_*`, `GITHUB_APP_PROD_*`).
- **Branch protection:** Configure the required status check name in GitHub; the same name is hard-coded as `STATUS_CONTEXT` in the repo.

Anything else is either **derived**, **fixed in code**, or **workflow/tool internal**.

---

## 2. Full list by source/usage

### 2.1 Injected into BmtConfig (runtime whitelist only)

Only these five can affect config when running CI/VM code; all others are defaults or derived.

| Var | Needed? | Notes |
|-----|---------|--------|
| `GCS_BUCKET` | Yes | From Pulumi export. User sets in bmt.tfvars.json. |
| `GCP_PROJECT` | Yes | From Pulumi export. |
| `GCP_SA_EMAIL` | Yes | From Pulumi export. |
| `BMT_LIVE_VM` | Yes | From Pulumi export. |
| `GCP_WIF_PROVIDER` | Yes | Set by user in GitHub (not in Pulumi). |

**Not in whitelist (cannot be overridden via env):** `GCP_ZONE`, `BMT_REPO_ROOT`, `BMT_PUBSUB_*`, `BMT_STATUS_CONTEXT`, handshake/description constants. They are fixed or derived in code to avoid drift and misconfiguration.

---

### 2.2 GitHub repo variables (workflows / actionlint)

| Var | Needed? | Auto-managed? | Notes |
|-----|---------|----------------|-------|
| `GCS_BUCKET` | Yes | Pulumi export | — |
| `GCP_PROJECT` | Yes | Pulumi export | — |
| `GCP_SA_EMAIL` | Yes | Pulumi export | — |
| `BMT_LIVE_VM` | Yes | Pulumi export | — |
| `GCP_WIF_PROVIDER` | Yes | No (user) | WIF provider for CI. |
| `BMT_DISPATCH_APP_ID` | Yes | No (user) | App ID for workflow_dispatch. |
| `BMT_VM_POOL_LABEL` | Optional | No | Label-based VM pool discovery; most setups use derived blue/green from `BMT_LIVE_VM`. |
| `BMT_RUNNERS_PRESEEDED_IN_GCS` | Optional | No | When `true`, skip runner upload in CI (e.g. sandbox). |
| `BMT_EXPECTED_IMAGE_FAMILY` | Optional | Default in workflow | Packer/image policy; default `bmt-runtime`. |
| `BMT_EXPECTED_BASE_IMAGE_FAMILY` | Optional | Default in workflow | Default `ubuntu-2204-lts`. |
| `BMT_EXPECTED_BASE_IMAGE_PROJECT` | Optional | Default in workflow | Default `ubuntu-os-cloud`. |

**Optional / workflow-defaulted:** `GCP_ZONE` — workflows use `vars.GCP_ZONE || 'europe-west4-a'`; not in Pulumi export contract. For act, add to `.env` from Pulumi if needed: `GCP_ZONE=$(cd infra/pulumi && pulumi stack output gcp_zone)`. `BMT_VM_POOL` — Pulumi outputs it (derived blue/green); not used as a workflow var (pool is derived in CI from `BMT_LIVE_VM` or `BMT_VM_POOL_LABEL`).

**Removed / not repo vars:** `BMT_PUBSUB_*`, `BMT_REPO_ROOT`, `BMT_STATUS_CONTEXT`, handshake timeouts — all derived or constants.

---

### 2.3 Workflow step outputs / job inputs (internal)

These are **written by steps** and read by later steps; they are not user-configured. They exist so the workflow can pass state without extra storage.

Examples: `VM_REUSED_RUNNING`, `SELECTED_VM`, `TRIGGER_WRITTEN`, `HANDSHAKE_OK`, `REPOSITORY`, `HEAD_SHA`, `PR_NUMBER`, `FILTERED_MATRIX`, `ORCH_HAS_LEGS`, etc. Full list: `WORKFLOW_CONTEXT_ENV_KEYS` in `gcp/image/config/bmt_config.py`.

**Verdict:** Necessary for multi-job handoff; no simplification needed. Not user-facing.

---

### 2.4 VM runtime (on the VM)

| Var | Needed? | Auto-managed? | Notes |
|-----|---------|----------------|-------|
| `GCS_BUCKET` | Yes | VM metadata (synced from repo) or config | — |
| `GCP_PROJECT` | Yes | VM metadata or config | — |
| `BMT_REPO_ROOT` | No (fixed) | Derived: `effective_repo_root` → `/opt/bmt` | Not overridable. |
| `BMT_PUBSUB_SUBSCRIPTION` | No (derived) | From `bmt_vm_name` → `bmt-vm-<name>` | Not overridable. |
| `BMT_WORKSPACE_ROOT` | Yes | Default `~/bmt_workspace` (or legacy `~/sk_runtime`) | Set by run_watcher; rarely need to override. |
| `BMT_IDLE_TIMEOUT_SEC` | Optional | VM metadata or default 600 | Idle seconds before VM self-stops. |
| `BMT_SECRETS_LOCATION` | Optional | Derived from instance zone (region) | For regional Secret Manager. |
| `BMT_SELF_STOP` | Optional | Default `1` | Set to `0` to leave VM running (debug). |
| `GITHUB_APP_TEST_ID`, `*_INSTALLATION_ID`, `*_PRIVATE_KEY` | Yes | GCP Secret Manager → env by run_watcher | Per github_repos.json. |
| `GITHUB_APP_PROD_*` | Yes | Same | — |
| `BMT_DATASET_LOCAL_PATH` | Optional | Set when `/mnt/audio_data` is mounted | — |

**Verdict:** Only GCP + bucket + VM name + GitHub App credentials are truly user/ops concerns. Repo root, subscription, and workspace default are derived or fixed.

---

### 2.5 Local / dev tools

| Var | Needed? | Notes |
|-----|---------|--------|
| `GCS_BUCKET` | Yes | For bucket sync, validate, monitor. |
| `GCP_PROJECT` | Yes | For VM scripts, validate. |
| `BMT_LIVE_VM` | Yes | For VM scripts, monitor. |
| `BMT_ENV_CONTRACT` | Optional | Path to contract JSON for gh_validate_vm_vars. |
| `BMT_RUN_ID`, `BMT_AUTO`, `BMT_PROD`, `BMT_REPO`, `BMT_CONFIG_ROOT`, `BMT_INTERVAL` | Optional | `tools/bmt/bmt_monitor.py` (bmt monitor command) only; defaults or CLI. |

**Zone:** Tools use fixed zone `europe-west4-a`; no `GCP_ZONE` override.

---

### 2.6 Optional / one-off tooling

| Var | Needed? | Notes |
|-----|---------|--------|
| `BMT_VM_POOL_LABEL` | Optional | VM pool by GCP label; alternative to derived blue/green. |
| `BMT_ALLOW_MANUAL_VM_START` | Optional | Allow start-vm when not in GITHUB_ACTIONS (local/dev). |
| `BMT_FORCE_SYNC` | Optional | Force sync in CI even when objects exist. |
| `BMT_VM_START_TIMEOUT_SEC` | Optional | Override for tests; normally constant in code. |
| `BMT_CONTEXT_FILE` | Optional | Override path for `.bmt/context.json`. |
| `BMT_GREEN_VM_NAME`, `BMT_IMAGE_FAMILY`, `BMT_IMAGE_NAME`, `BMT_GREEN_ALLOW_RECREATE` | Optional | create_bmt_green_vm.py. |
| `BMT_EXPORT_DIR` | Optional | export_vm_spec.py output dir. |

These are either **dev/test overrides** or **advanced ops**; they do not need to be in the main “user config” story.

---

## 3. Unnecessary / drift / over-complication

| Issue | Recommendation |
|-------|-----------------|
| **GCP_ZONE as repo var** | Removed. Zone is fixed (`europe-west4-a`) in code; workflow uses `vars.GCP_ZONE \|\| 'europe-west4-a'` only for backward compatibility. Do not reintroduce as configurable. |
| **BMT_PUBSUB_SUBSCRIPTION / TOPIC as repo vars** | Removed. Subscription derived from VM name; topic is constant. Reduces drift and duplicate config. |
| **BMT_REPO_ROOT as repo var** | Removed. Default `/opt/bmt` in code; VM metadata can still sync it for legacy, but config does not read it from env. |
| **BMT_VM_POOL as repo var** | Removed. Pool derived from `BMT_LIVE_VM` (blue/green) or `BMT_VM_POOL_LABEL`. |
| **BMT_STATUS_CONTEXT as repo var** | Not a repo var. Status context is a constant in code; branch protection must match it. Avoids drift between “branch rule name” and “what BMT posts”. |
| **Handshake timeouts as repo vars** | Not in whitelist. Sensible defaults in BmtConfig; no env override. |
| **actionlint config** | `.github/actionlint.yaml` still lists optional vars (e.g. `BMT_EXPECTED_*`, `BMT_VM_POOL_LABEL`) so actionlint does not flag them. No need to add more unless a workflow starts using a new var. |

---

## 4. Automatically managed

| What | How |
|------|-----|
| **GCS_BUCKET, GCP_PROJECT, GCP_SA_EMAIL, BMT_LIVE_VM** | User edits `infra/pulumi/bmt.tfvars.json` → `just pulumi` (apply + export) → GitHub repo vars updated. User does not set these four in the GitHub UI. |
| **Pub/Sub subscription** | Derived in code: `bmt-vm-` + `bmt_vm_name`. |
| **VM pool (blue/green)** | Derived in code from `BMT_LIVE_VM` when name ends with `-blue` or `-green`. |
| **Repo root** | Default `/opt/bmt` in code; no env. |
| **Zone** | Pulumi has `gcp_zone` (required in tfvars); outputs it. Not in repo-vars export; workflows default `vars.GCP_ZONE` to `europe-west4-a`. Fixed in runtime code (not overridable via env). |
| **Status context** | Constant in `gcp/image/config/constants.py`; branch protection configured to match. |
| **VM metadata (GCS_BUCKET, etc.)** | Workflow `sync-vm-metadata` pushes from repo vars to VM metadata so VM sees same bucket/config. |

---

## 5. Summary: minimal “user surface”

**User actually configures:**

1. **Declarative:** `infra/pulumi/bmt.tfvars.json` — **required:** `gcp_project`, `gcp_zone`, `gcs_bucket`, `service_account`. **Optional:** `bmt_vm_name` (default `bmt-gate-blue`), `startup_wrapper_script_path` (see `bmt.tfvars.example.json`).
2. **GitHub Variables:** `GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID`.
3. **GitHub Secret:** `BMT_DISPATCH_APP_PRIVATE_KEY` (when this repo mints the dispatch token).
4. **GCP Secret Manager:** Per-repo GitHub App credentials (`GITHUB_APP_TEST_*`, `GITHUB_APP_PROD_*`) — keyed by `github_repos.json`.
5. **GitHub branch protection:** Required status check name must match the constant `STATUS_CONTEXT` in code.

**Everything else** is either derived (subscription, pool, repo root), fixed (zone, topic, status context, timeouts), or internal (workflow step outputs, tool-only opts). That keeps the surface small and limits drift and misconfiguration.

---

## 6. Override policy: what may vs may not be overridable

### 6.1 May be overridable (in addition to minimal config)

These are **optional overrides** for deployment or ops; safe to let the user set them when they have a good reason.

| Override | Where | Reason |
|----------|--------|--------|
| **BMT_VM_POOL_LABEL** | GitHub repo var (optional) | VM pool by GCP label instead of derived blue/green; needed when naming doesn’t follow `-blue`/`-green`. |
| **BMT_RUNNERS_PRESEEDED_IN_GCS** | GitHub repo var (optional) | Skip runner upload in CI (e.g. sandbox where runners are pre-loaded); avoids “artifact not found” in non-standard setups. |
| **BMT_EXPECTED_IMAGE_FAMILY**, **BMT_EXPECTED_BASE_IMAGE_*** | GitHub repo var or workflow default | Image policy for Packer/build; different orgs may pin different base images. Defaults in workflow are enough for most. |
| **BMT_IDLE_TIMEOUT_SEC** | VM metadata or env on VM | Idle seconds before VM self-stops; ops may want shorter/longer. Default 600 is fine for most. |
| **BMT_SELF_STOP** | Env on VM | Debug: set to `0` to leave VM running. Default `1` (self-stop). |
| **BMT_WORKSPACE_ROOT** | Set by run_watcher default; override only if needed | Default `~/bmt_workspace`; override only for special layouts. |
| **BMT_CONTEXT_FILE** | Local/tool env | Override path for `.bmt/context.json`; useful for tests or multiple configs. |
| **Local/dev tool opts** | Env when running tools | e.g. `BMT_RUN_ID`, `BMT_AUTO`, `BMT_REPO`, `BMT_CONFIG_ROOT`, `BMT_INTERVAL` for `tools/bmt/bmt_monitor` (just monitor); `BMT_ENV_CONTRACT` for gh_validate_vm_vars; green-VM script opts (`BMT_GREEN_VM_NAME`, `BMT_IMAGE_FAMILY`, etc.). Not part of CI/VM contract. |
| **BMT_ALLOW_MANUAL_VM_START** | Env when running start-vm locally | Allow starting VM outside GitHub Actions; dev/safety only. |

Rule of thumb: **overrideable** = “different deployments or one-off ops might legitimately need a different value,” and changing it doesn’t break the contract between repo, VM, and branch protection.

---

### 6.2 Must not be overridable

These **must not** be set by the user via env (or repo vars). They are either derived from minimal config, fixed for correctness, or internal. Allowing overrides would create drift, break handoff, or confuse branch protection.

| Do not override | Why |
|-----------------|-----|
| **GCP_ZONE** | Pulumi has `gcp_zone` (required in tfvars); workflows default `vars.GCP_ZONE` to `europe-west4-a`. At runtime (BmtConfig) zone is not in the env whitelist; code uses fixed default. Do not make it overridable via env. |
| **BMT_REPO_ROOT** | Path on VM is fixed (`/opt/bmt`); code and startup assume it. Override would break watcher and scripts. |
| **BMT_PUBSUB_TOPIC** | Single topic name in code; subscription is derived from VM name. |
| **BMT_PUBSUB_SUBSCRIPTION** | Derived from `bmt_vm_name` (`bmt-vm-<name>`). Must stay in sync with VM and Pulumi. |
| **BMT_VM_POOL** | Derived from `BMT_LIVE_VM` (blue/green) or from `BMT_VM_POOL_LABEL`. Comma-list override was removed to avoid drift. |
| **BMT_STATUS_CONTEXT** | Must match branch protection and what the VM posts. Constant in code; no repo var. Override would desync branch rules and status checks. |
| **Handshake timeouts** (e.g. **BMT_HANDSHAKE_TIMEOUT_SEC**, **BMT_HANDSHAKE_TIMEOUT_SEC_REUSE_RUNNING**) | Sensible defaults in BmtConfig; used for workflow↔VM coordination. Env override removed to avoid flaky or stuck runs. |
| **Progress/failure description strings** (e.g. **BMT_PROGRESS_DESCRIPTION**, **BMT_FAILURE_STATUS_DESCRIPTION**) | UI strings; fixed in code. No need to configure. |
| **Workflow step outputs** (e.g. **SELECTED_VM**, **HANDSHAKE_OK**, **TRIGGER_WRITTEN**) | Written by steps; consumed by later steps. Not user config. |

Rule of thumb: **not overrideable** = “this value is either derived from minimal config, must stay in sync with GitHub/GCP, or is an internal constant; letting the user set it would risk breakage or drift.”
