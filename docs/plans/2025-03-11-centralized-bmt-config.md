# Centralized BMT config – implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Single source of truth for all BMT configuration and behavioral defaults in bmt-gcloud; every consumer gets config only via a Pydantic config class loaded from JSON; no env overrides for defaults; Terraform used only for infra (GCP_* / GCS_*); BMT_* reserved for app config from bmt-config.json.

**Scope:** All changes are made **only** in the **bmt-gcloud** repository (bmt-gate-sandbox). No changes in core-main.

**Architecture:** One JSON file at `gcp/code/config/bmt-config.json` holds defaulted keys only. One Pydantic model in `gcp/code/lib/bmt_config.py` is populated from that JSON; required runtime fields (GCS_BUCKET, GCP_PROJECT, etc.) are injected once at load time via a whitelist of env vars. CLI and VM share the same module; no overrides from env or parameters for defaulted keys. Terraform exports only infra-derived repo vars (GCP_* / GCS_*); behavioral vars (BMT_*) are set from bmt-config.json by a separate export step.

**Tech Stack:** Python 3.12, Pydantic (plain, not pydantic-settings), JSON, existing CLI (click) and VM (argparse) entrypoints.

---

## Design summary (reference)

- **Single API:** `get_config(runtime=...)` returns the only config instance. No `os.environ.get("BMT_...", default)` for defaults.
- **No overrides:** Defaults from JSON only; required runtime from single injection (env whitelist). No .env or parameter override.
- **Config as argument:** Prefer passing `cfg: BmtConfig | None = None` into helpers instead of many parameters; use `cfg or get_config()`.
- **Full location inventory:** See section "All locations" in `.cursor/plans/centralized_bmt_config.plan.md` for every file/symbol that has hardcoded or parameter-passed config.

---

## Task 1: Add bmt-config.json and Pydantic loader

**Files:**
- Create: `gcp/code/config/bmt-config.json`
- Create: `gcp/code/lib/bmt_config.py`
- Modify: `.github/bmt/pyproject.toml` (add `pydantic`)

**Step 1: Add pydantic dependency**

Edit `.github/bmt/pyproject.toml`: under `dependencies`, add `"pydantic",`.

Run: `cd .github/bmt && uv sync`
Expected: Sync succeeds, pydantic installed.

**Step 2: Create bmt-config.json with defaulted keys only**

Create `gcp/code/config/bmt-config.json` with JSON keys for all behavioral defaults (no GCS_BUCKET, GCP_PROJECT, etc.). Include at least: `bmt_status_context`, `bmt_runtime_context`, `bmt_handshake_timeout_sec`, `bmt_trigger_stale_sec`, `bmt_trigger_metadata_keep_recent`, `bmt_preempt_on_pr_stale_queue`, `bmt_vm_start_timeout_sec`, `bmt_vm_stabilization_sec`, `bmt_vm_start_recovery_attempts`, `bmt_vm_recovery_start_delay_sec`, `bmt_idle_timeout_sec`, `bmt_repo_root` (default path only), and any other defaulted fields from the "All locations" inventory. Use numeric values as numbers; strings as strings.

Example shape (values from current defaults):

```json
{
  "bmt_status_context": "BMT Gate",
  "bmt_runtime_context": "BMT Runtime",
  "bmt_handshake_timeout_sec": 420,
  "bmt_trigger_stale_sec": 900,
  "bmt_trigger_metadata_keep_recent": 2,
  "bmt_preempt_on_pr_stale_queue": "1",
  "bmt_vm_start_timeout_sec": 420,
  "bmt_vm_stabilization_sec": 45,
  "bmt_vm_start_recovery_attempts": 2,
  "bmt_vm_recovery_start_delay_sec": 10,
  "bmt_idle_timeout_sec": 600,
  "bmt_stale_trigger_age_hours": 2,
  "bmt_repo_root_default": "/opt/bmt"
}
```

**Step 3: Create gcp/code/lib/bmt_config.py**

Create `gcp/code/lib/bmt_config.py` that:
- Defines a Pydantic model `BmtConfig` with all fields (required: `gcs_bucket`, `gcp_project`, `gcp_zone`, `gcp_sa_email`, `bmt_vm_name`, and any other required infra; optional-with-default from JSON).
- Resolves config path: repo use `gcp/code/config/bmt-config.json` (relative to cwd or `GITHUB_WORKSPACE`); VM use `$BMT_REPO_ROOT/config/bmt-config.json` (from runtime dict).
- Implements `get_config(runtime: dict[str, str] | None = None)` that: (1) loads JSON from resolved path, (2) builds model from JSON for defaulted fields, (3) sets required fields only from `runtime` using a fixed whitelist of keys (e.g. GCS_BUCKET, GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, GCP_SA_EMAIL, BMT_REPO_ROOT, BMT_PUBSUB_*). No overlay of defaulted fields from runtime.
- Exports `get_config` and `BmtConfig`. Optionally caches the instance for CLI (single load per process).

**Step 4: Run existing tests**

Run: `uv run python -m pytest tests/ -v` (from repo root, with `uv pip install -e .` or equivalent so bmt and gcp are importable as needed).
Expected: Existing tests pass (no regressions). If any test imports `cli.shared.config` or `cli.shared.defaults`, they may need path fixes in a later task.

**Step 5: Commit**

```bash
git add gcp/code/config/bmt-config.json gcp/code/lib/bmt_config.py .github/bmt/pyproject.toml
git commit -m "feat(config): add bmt-config.json and Pydantic loader in gcp/code/lib"
```

---

## Task 2: Thin CLI shared config to use gcp/code/lib/bmt_config

**Files:**
- Modify: `.github/bmt/cli/shared/config.py`
- Modify or remove: `.github/bmt/cli/shared/defaults.py`

**Step 1: Make config.py a thin wrapper**

Refactor `.github/bmt/cli/shared/config.py` so it no longer defines its own BmtConfig or loads JSON+env. Instead: ensure `gcp/code` is on `sys.path` (or use a path relative to repo root), import `get_config` and `BmtConfig` from `gcp.code.lib.bmt_config` (or the appropriate import path that works when running from repo root). Re-export `get_config`, `BmtConfig`, and `load_bmt_config` if still used (or replace with a single `get_config()` that calls the lib with `runtime=os.environ` and in the lib only whitelisted keys are read). Remove all `_get(..., "BMT Gate")` style defaults; those come from JSON only.

**Step 2: Remove or empty defaults.py**

Remove constants from `.github/bmt/cli/shared/defaults.py` that are now in bmt-config.json (e.g. DEFAULT_HANDSHAKE_TIMEOUT_SEC, DEFAULT_VM_START_TIMEOUT_SEC, DEFAULT_VM_STOP_WAIT_TIMEOUT_SEC). Either delete the file or leave it empty / with a comment pointing to bmt-config.json. Update any remaining imports of defaults to use `get_config()` instead.

**Step 3: Run tests**

Run: `uv run python -m pytest tests/ -v`
Expected: All tests pass.

**Step 4: Commit**

```bash
git add .github/bmt/cli/shared/config.py .github/bmt/cli/shared/defaults.py
git commit -m "refactor(config): thin CLI config to use gcp/code/lib/bmt_config"
```

---

## Task 3: CLI workflow.py – use get_config() only

**Files:**
- Modify: `.github/bmt/cli/commands/workflow.py`

**Step 1: Replace env reads in run_wait_handshake**

In `run_wait_handshake()`, remove `os.environ.get("BMT_HANDSHAKE_TIMEOUT_SEC", str(DEFAULT_HANDSHAKE_TIMEOUT_SEC))` and the literals `600`, `base_timeout + 60`. Obtain base timeout from `get_config().bmt_handshake_timeout_sec`; compute branch-specific timeout (reuse-running, post-cleanup, standard) from that single source. Remove import of `DEFAULT_HANDSHAKE_TIMEOUT_SEC` from defaults if still present.

**Step 2: Replace env reads in run_post_pending_status and run_post_handoff_timeout_status**

Use `cfg = get_config()` and set `context = cfg.bmt_status_context`, `description` from cfg (add fields to Pydantic/JSON if needed: e.g. `bmt_progress_description`, `bmt_failure_status_description`). Remove all `os.environ.get("BMT_STATUS_CONTEXT", "BMT Gate")` and similar.

**Step 3: Run tests**

Run: `uv run python -m pytest tests/ -v`
Expected: Pass.

**Step 4: Commit**

```bash
git add .github/bmt/cli/commands/workflow.py
git commit -m "refactor(workflow): use get_config() for handshake and status context"
```

---

## Task 4: CLI vm.py – use get_config() only

**Files:**
- Modify: `.github/bmt/cli/commands/vm.py`

**Step 1: run_start – read timeouts from config**

Replace `os.environ.get("BMT_VM_START_TIMEOUT_SEC", ...)`, `BMT_VM_STABILIZATION_SEC`, `BMT_VM_START_RECOVERY_ATTEMPTS`, `BMT_VM_RECOVERY_START_DELAY_SEC` with values from `get_config()`. Ensure those keys exist in bmt-config.json and BmtConfig (add if missing). Keep `BMT_ALLOW_MANUAL_VM_START` as env-only (or add to JSON if it is a config default). Remove imports from defaults.

**Step 2: run_sync_metadata – repo root from config**

Replace `os.environ.get("BMT_REPO_ROOT") or "/opt/bmt"` with `get_config().bmt_repo_root` (or the field that holds the injected repo root). Ensure required runtime injection includes BMT_REPO_ROOT.

**Step 3: run_wait_handshake – accept optional cfg**

Change signature to `run_wait_handshake(cfg: BmtConfig | None = None)`. Inside, use `cfg = cfg or get_config()` and `timeout_sec = cfg.bmt_handshake_timeout_sec`. Remove the `timeout_sec` parameter from the public API. Call sites (e.g. workflow.run_wait_handshake) call with no args.

**Step 4: run_select_available_vm**

Keep reading VM pool from env (BMT_VM_POOL_LABEL, BMT_VM_POOL, BMT_VM_NAME) until runtime injection is defined; these are required runtime, so they come from get_config() if they are on the whitelist. If they are, use cfg.gcp_project, cfg.bmt_vm_name, etc. instead of env.

**Step 5: Run tests**

Run: `uv run python -m pytest tests/ -v`
Expected: Pass.

**Step 6: Commit**

```bash
git add .github/bmt/cli/commands/vm.py
git commit -m "refactor(vm): use get_config(); run_wait_handshake(cfg=...)"
```

---

## Task 5: CLI workflow_trigger, matrix, trigger – use get_config()

**Files:**
- Modify: `.github/bmt/cli/commands/workflow_trigger.py`
- Modify: `.github/bmt/cli/commands/matrix.py`
- Modify: `.github/bmt/cli/commands/trigger.py`

**Step 1: workflow_trigger.run_preflight_trigger_queue**

Replace `os.environ.get("BMT_TRIGGER_STALE_SEC", "900")`, `BMT_TRIGGER_METADATA_KEEP_RECENT`, `BMT_PREEMPT_ON_PR_STALE_QUEUE` with values from `get_config()`. Add fields to JSON/BmtConfig if missing.

**Step 2: matrix – output keys from config (optional)**

If BMT_OUTPUT_KEY, BMT_PRESETS_FILE, BMT_HAS_LEGS_KEY are considered config, add them to bmt-config.json and read from get_config(); otherwise leave as env for now and document as excluded.

**Step 3: trigger.py**

Remove module-level `DEFAULT_STATUS_CONTEXT`, `DEFAULT_RUNTIME_CONTEXT`, `DEFAULT_DESCRIPTION_PENDING` literals; run_trigger already uses get_config() for ctx/runtime_ctx. Ensure description_pending comes from config if it is in JSON.

**Step 4: Run tests**

Run: `uv run python -m pytest tests/ -v`
Expected: Pass.

**Step 5: Commit**

```bash
git add .github/bmt/cli/commands/workflow_trigger.py .github/bmt/cli/commands/matrix.py .github/bmt/cli/commands/trigger.py
git commit -m "refactor(cli): workflow_trigger, matrix, trigger use get_config()"
```

---

## Task 6: VM vm_watcher – use get_config()

**Files:**
- Modify: `gcp/code/vm_watcher.py`

**Step 1: Ensure gcp/code can load bmt_config**

VM runs from repo root or BMT_REPO_ROOT; ensure `gcp/code` is on sys.path so `from lib.bmt_config import get_config` (or equivalent) works when run from gcp/code or repo root. Add pydantic to gcp/code dependencies if there is a separate pyproject for VM code.

**Step 2: Replace module globals**

Remove or replace `_KEEP_RECENT_LOCAL_RUNS`, `DEFAULT_STATUS_CONTEXT`, `DEFAULT_RUNTIME_STATUS_CONTEXT`, `_KEEP_RECENT_WORKFLOW_FILES`, `_STALE_TRIGGER_AGE_HOURS`. At startup (e.g. in `main` after parsing args), call `cfg = get_config(runtime=os.environ)` once. Use `cfg.bmt_trigger_metadata_keep_recent`, `cfg.bmt_status_context`, `cfg.bmt_runtime_context`, and any `bmt_stale_trigger_age_hours` / `bmt_idle_timeout_sec` from cfg instead of _env_int and literals.

**Step 3: Argparse defaults from cfg**

Where args have defaults from env (e.g. `--idle-timeout-sec`, `--workspace-root`), populate from cfg when available. If "no overrides" is strict, argparse can take defaults from cfg after first load (or pass cfg into parse_args).

**Step 4: Helpers accept cfg**

Update `_post_pending_status_from_trigger` and `_prune_run_dirs` to accept optional `cfg: BmtConfig | None = None` and use `(cfg or get_config()).bmt_status_context` / `bmt_trigger_metadata_keep_recent` instead of parameters or module globals.

**Step 5: Run tests**

Run: `uv run python -m pytest tests/ -v`. If VM code is not under tests, run a quick smoke test (e.g. `uv run python gcp/code/vm_watcher.py --help`).
Expected: No errors; tests pass.

**Step 6: Commit**

```bash
git add gcp/code/vm_watcher.py
git commit -m "refactor(vm_watcher): use get_config(); pass cfg to helpers"
```

---

## Task 7: VM root_orchestrator, lib/github_auth, sk/bmt_manager

**Files:**
- Modify: `gcp/code/root_orchestrator.py`
- Modify: `gcp/code/lib/github_auth.py`
- Modify: `gcp/code/sk/bmt_manager.py`

**Step 1: root_orchestrator**

Replace `--workspace-root` default from `os.environ.get("BMT_WORKSPACE_ROOT", "")` with value from get_config() when available. Keep BMT_STATUS_* env passed to manager as set by orchestrator (from run context); ensure those are not overridable defaults (they are per-run).

**Step 2: github_auth**

Replace `os.environ.get("BMT_REPO_ROOT", "").strip() or "/opt/bmt"` with get_config().bmt_repo_root (or the injected repo root field). Load config once at module or caller level and pass or use from get_config().

**Step 3: bmt_manager**

BMT_STATUS_BUCKET, BMT_STATUS_RUNTIME_PREFIX, etc. are set by orchestrator for the run; no change to source of those. If bmt_manager reads any BMT_* default (e.g. repo root), use get_config().

**Step 4: Run tests**

Run: `uv run python -m pytest tests/ -v`
Expected: Pass.

**Step 5: Commit**

```bash
git add gcp/code/root_orchestrator.py gcp/code/lib/github_auth.py gcp/code/sk/bmt_manager.py
git commit -m "refactor(vm): root_orchestrator, github_auth, bmt_manager use get_config()"
```

---

## Task 8: Repo vars contract and Terraform

**Files:**
- Modify: `tools/repo_vars_contract.py`
- Modify: `infra/terraform/variables.tf` (remove behavioral defaults; keep only infra)
- Modify or create: `infra/bootstrap/.env.example`

**Step 1: repo_vars_contract loads defaults from JSON**

Refactor `tools/repo_vars_contract.py` so the `defaults` tuple is built by reading `gcp/code/config/bmt-config.json` (or by importing the Pydantic model and using its schema/defaults). Remove hardcoded `DEFAULT_HANDSHAKE_TIMEOUT_SEC = 420` and the inline defaults tuple for BMT_STATUS_CONTEXT, BMT_TRIGGER_STALE_SEC, etc. Ensure the script can resolve the path to bmt-config.json when run from repo root.

**Step 2: Terraform – infra vars only**

Remove from Terraform any variables that define BMT behavioral defaults (bmt_status_context, bmt_handshake_timeout_sec, bmt_trigger_stale_sec, bmt_trigger_metadata_keep_recent, bmt_projects, bmt_runtime_context). Terraform only exports infra-derived vars (GCS_BUCKET, GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, BMT_REPO_ROOT, GCP_SA_EMAIL, BMT_PUBSUB_*). Document in variables.tf or a README that behavioral BMT_* vars are set from bmt-config.json via a separate export step, not Terraform.

**Step 3: .env.example**

Update or create `infra/bootstrap/.env.example` to list required env vars and note that behavioral defaults match `gcp/code/config/bmt-config.json`; no override from .env for those.

**Step 4: Run tests and lint**

Run: `uv run python -m pytest tests/ -v` and `ruff check .` / `basedpyright`.
Expected: Pass.

**Step 5: Commit**

```bash
git add tools/repo_vars_contract.py infra/terraform/variables.tf infra/bootstrap/.env.example
git commit -m "refactor(config): repo_vars from JSON; Terraform infra-only"
```

---

## Task 9: Documentation and optional validation

**Files:**
- Modify: `docs/configuration.md`
- Create (optional): script or CI step to validate Terraform vs bmt-config.json

**Step 1: Update docs/configuration.md**

Document that all BMT config defaults live in `gcp/code/config/bmt-config.json`; the only way to get config in code is the Pydantic config class in `gcp/code/lib/bmt_config.py`. No .env or parameter overrides for defaulted keys. Terraform exports only GCP_* / GCS_* (infra); BMT_* behavioral vars come from bmt-config.json and a separate export step.

**Step 2: Optional validation**

If desired, add a small script or CI job that reads bmt-config.json and (1) checks that repo_vars_contract defaults match, (2) fails if Terraform still defines any BMT_* behavioral default. Skip if out of scope.

**Step 3: Commit**

```bash
git add docs/configuration.md
git commit -m "docs: configuration points to bmt-config.json and get_config()"
```

---

## Execution handoff

Plan complete and saved to `docs/plans/2025-03-11-centralized-bmt-config.md`.

**Two execution options:**

1. **Subagent-driven (this session)** – Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Parallel session (separate)** – Open a new session with **executing-plans** and run through the plan with checkpoints.

**Which approach?**

If subagent-driven: use **superpowers:subagent-driven-development** in this session.  
If parallel session: open the worktree/session and use **superpowers:executing-plans** there.
