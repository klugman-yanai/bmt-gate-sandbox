---
todos:
  - title: Task 1.1 Add Typer-based CLI skeleton and __main__.py
    status: todo
  - title: Task 1.2 Wire orchestrator and run-watcher subcommands
    status: todo
  - title: Task 1.3 Document single entrypoint and update startup (optional)
    status: todo
  - title: Task 2.1 Result path constants
    status: todo
  - title: Task 2.2 Status and conclusion enums
    status: todo
  - title: Task 2.3 Trigger resolution decision/reason constants
    status: todo
  - title: Task 3.1 BucketPaths / GcsPaths value object
    status: todo
  - title: Task 3.2 LegIdentity / RunLeg value object
    status: todo
  - title: Task 3.3 RunOutputContext and GatePhaseResult (bmt_manager_base)
    status: todo
  - title: Task 3.4 WatcherEnvConfig (run_watcher)
    status: todo
  - title: Task 4.1 TriggerPayload and leg payload TypedDicts
    status: todo
  - title: Task 4.2 ManagerSummary / CiVerdict types
    status: todo
  - title: Task 5.1 Extract trigger processing pipeline from vm_watcher
    status: todo
  - title: Task 5.2 Extract gate/verdict helpers from bmt_manager_base
    status: todo
  - title: Task 5.3 Fix script _log/_log_err (optional)
    status: todo
  - title: Task 6.1 Prefer guard clauses and lookup tables
    status: todo
  - title: Task 6.2 Update docs and CLAUDE.md
    status: todo
---

# gcp/image Single Entrypoint and Readability Refactor — Implementation Plan

**Tools and design patterns used**

- **Single CLI entrypoint** — Typer app with subcommands (`watcher`, `orchestrator`, `run-watcher`, etc.) so all entrypoints are invoked via `python -m gcp.image <subcommand>`.
- **Constants and enums** — Centralized result-path strings (`config/result_paths.py`) and status/conclusion/trigger-decision codes as `enum.StrEnum` or constants to remove magic strings.
- **Value objects** — Immutable dataclasses (`BucketPaths`, `LegIdentity`, etc.) to group related primitives and reduce long argument lists.
- **Config / result dataclasses** — `RunOutputContext`, `GatePhaseResult`, `WatcherEnvConfig` (and similar) to replace multi-argument functions and multi-tuple returns.
- **Typed payloads** — TypedDict or Pydantic models for trigger payloads, leg summaries, manager summary, and CI verdict at boundaries (GCS, subprocess, API).
- **Parameter objects** — Single config/context objects passed into functions instead of many positional or keyword arguments.
- **Guard clauses and lookup tables** — Early returns and dict-based dispatch instead of long if/elif chains where it simplifies control flow.
- **Extract-module refactors** — Trigger-processing pipeline and gate/verdict logic moved into dedicated modules to shrink `vm_watcher.py` and `bmt_manager_base.py` and improve testability.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** One root entrypoint for gcp/image (`main.py` or `__main__.py`), replace magic strings with constants/enums, introduce config and value objects (Pydantic/dataclasses) to cut parameter counts and improve type-safety, and reduce complexity/lines while improving readability.

**Architecture:** (1) Add `gcp/image/__main__.py` (and optional `main.py`) as the single CLI entrypoint using Typer subcommands (`watcher`, `orchestrator`, `run-watcher`, `install-deps`, etc.); existing script paths may remain as thin wrappers that delegate. (2) Centralize result-path and status/conclusion strings in `config/constants.py` or a new `config/result_paths.py` and use enums/constants everywhere. (3) Introduce value objects (e.g. `BucketPaths`, `LegIdentity`, `CommitRef`) and config/result dataclasses (e.g. `RunOutputContext`, `GatePhaseResult`, `WatcherEnvConfig`, `TriggerPayload`) so functions take one or few objects instead of many primitives. (4) Add TypedDict or Pydantic models for trigger payloads, leg summaries, and manager summaries. (5) Extract trigger-processing and PR/comment logic from vm_watcher into focused modules; extract gate/verdict helpers from bmt_manager_base where it simplifies reuse.

**Tech Stack:** Python 3.12, Pydantic (existing), Typer (for CLI), pathlib, enum.StrEnum (3.11+). No new runtime dependencies beyond Typer if not already present.

---

## Phase 1: Single root entrypoint

### Task 1.1: Add Typer-based CLI skeleton and __main__.py

**Files:**
- Create: `gcp/image/cli.py`
- Create: `gcp/image/__main__.py`
- Modify: `gcp/image/path_utils.py` (ensure VM_WATCHER_SCRIPT / entrypoint names stay consistent)

**Step 1: Add Typer dependency (if missing)**

Check: `grep -r typer pyproject.toml uv.lock 2>/dev/null || true`  
If Typer is not in the root project, add it to the workspace member that provides gcp (see pyproject.toml `[tool.uv.workspace]`). For a minimal change, add to root or gcp/image member: `typer>=0.15.0` in dependencies.

**Step 2: Create CLI module with subcommand stubs**

Create `gcp/image/cli.py`:

```python
"""Single CLI entrypoint for gcp.image. Subcommands delegate to existing main() implementations."""
from __future__ import annotations
import typer
app = typer.Typer(help="BMT VM and image CLI")

@app.command()
def watcher(
    bucket: str = typer.Option(..., help="GCS bucket name"),
    workspace_root: str = typer.Option(default="", help="Workspace root path"),
    exit_after_run: bool = typer.Option(False, "--exit-after-run"),
    idle_timeout_sec: int = typer.Option(600, "--idle-timeout-sec"),
    poll_interval_sec: int = typer.Option(30, "--poll-interval-sec"),
    subscription: str | None = typer.Option(None),
    gcp_project: str | None = typer.Option(None, "--gcp-project"),
) -> None:
    """Run the VM watcher (polls GCS or Pub/Sub, runs legs, posts status)."""
    from pathlib import Path
    from gcp.image.vm_watcher import main as watcher_main
    # Build argv equivalent for existing main(); or refactor vm_watcher.main to accept kwargs.
    import sys
    sys.argv = ["vm_watcher", "--bucket", bucket]
    if workspace_root:
        sys.argv.extend(["--workspace-root", workspace_root])
    if exit_after_run:
        sys.argv.append("--exit-after-run")
    sys.argv.extend(["--idle-timeout-sec", str(idle_timeout_sec)])
    if subscription:
        sys.argv.extend(["--subscription", subscription])
    if gcp_project:
        sys.argv.extend(["--gcp-project", gcp_project])
    raise SystemExit(watcher_main())
```

Add other subcommands as stubs that delegate: `orchestrator`, `run-watcher`, `install-deps`, etc. (Each can build `sys.argv` and call the existing script’s `main()` until those are refactored to accept a config object.)

**Step 3: Create __main__.py**

Create `gcp/image/__main__.py`:

```python
"""Run with: python -m gcp.image [subcommand] [options]. Default subcommand: watcher."""
from __future__ import annotations
from gcp.image.cli import app
if __name__ == "__main__":
    app()
```

**Step 4: Verify entrypoint**

Run: `cd /home/yanai/sandbox/bmt-gcloud && uv run python -m gcp.image watcher --help`  
Expected: Typer shows options for watcher.

**Step 5: Commit**

```bash
git add gcp/image/cli.py gcp/image/__main__.py
git commit -m "feat(gcp/image): add single CLI entrypoint (Typer) and __main__.py"
```

### Task 1.2: Wire orchestrator and run-watcher subcommands

**Files:**
- Modify: `gcp/image/cli.py`
- Modify: `gcp/image/scripts/run_watcher.py` (optional: keep as thin wrapper that calls `python -m gcp.image run-watcher` or import and call a run_watcher_main())

**Step 1: Add orchestrator subcommand**

In `gcp/image/cli.py`, add:

```python
@app.command()
def orchestrator(
    bucket: str = typer.Option(...),
    project: str = typer.Option(...),
    bmt_id: str = typer.Option(..., "--bmt-id"),
    run_context: str = typer.Option("manual", "--run-context"),
    run_id: str = typer.Option(..., "--run-id"),
    workspace_root: str = typer.Option(...),
    leg_index: int | None = typer.Option(None, "--leg-index"),
    summary_out: str | None = typer.Option(None, "--summary-out"),
) -> None:
    """Run root orchestrator for one leg."""
    from gcp.image.root_orchestrator import main as orch_main
    import sys
    sys.argv = ["root_orchestrator", "--bucket", bucket, "--project", project, "--bmt-id", bmt_id,
                "--run-context", run_context, "--run-id", run_id, "--workspace-root", workspace_root]
    if leg_index is not None:
        sys.argv.extend(["--leg-index", str(leg_index)])
    if summary_out:
        sys.argv.extend(["--summary-out", summary_out])
    raise SystemExit(orch_main())
```

**Step 2: Add run-watcher subcommand**

Add `run-watcher` subcommand that invokes the same logic as `scripts/run_watcher.py` (e.g. import `run_watcher.main` and call it, or build argv and run the script). Ensure startup scripts can still call `scripts/run_watcher.py` by path; that script can be updated to `python -m gcp.image run-watcher` in a later task if desired.

**Step 3: Run and commit**

Run: `uv run python -m gcp.image orchestrator --help` and `uv run python -m gcp.image run-watcher --help`  
Commit: `feat(gcp/image): add orchestrator and run-watcher CLI subcommands`

### Task 1.3: Document single entrypoint and update startup (optional)

**Files:**
- Modify: `gcp/image/scripts/README.md`
- Modify: `gcp/image/scripts/startup_entrypoint.sh` and `.github/bmt/ci/resources/startup_entrypoint.sh` (optional: switch to `python -m gcp.image run-watcher` and `python -m gcp.image watcher`)

**Step 1:** Update README to state that the canonical way to run the watcher is `python -m gcp.image watcher ...` and that `scripts/run_watcher.py` / `vm_watcher.py` are compatibility wrappers or call the same entrypoint.

**Step 2 (optional):** Change startup script to invoke `BMT_REPO_ROOT/.venv/bin/python -m gcp.image run-watcher` (and run_watcher to spawn `python -m gcp.image watcher`) so only one entrypoint is used in production. If you keep script paths for backward compatibility, skip this step.

**Step 3: Commit**

`docs(gcp/image): document single entrypoint and optional startup use of -m gcp.image`

---

## Phase 2: Constants and enums

### Task 2.1: Result path constants

**Files:**
- Create or modify: `gcp/image/config/result_paths.py`
- Modify: `gcp/image/pointer_update.py`, `gcp/image/projects/shared/bmt_manager_base.py`, `gcp/image/root_orchestrator.py`, `gcp/image/verdict_aggregation.py`, `gcp/image/github/github_checks.py`

**Step 1: Define constants**

Create `gcp/image/config/result_paths.py`:

```python
"""Canonical names for GCS result paths and filenames. Single source of truth."""
from __future__ import annotations
CURRENT_JSON = "current.json"
LATEST_JSON = "latest.json"
CI_VERDICT_JSON = "ci_verdict.json"
MANAGER_SUMMARY_JSON = "manager_summary.json"
BMT_ROOT_RESULTS_JSON = "bmt_root_results.json"
SNAPSHOTS_PREFIX = "snapshots"
LOGS_PREFIX = "logs"
POINTER_KEY_LAST_PASSING = "last_passing"
POINTER_KEY_LATEST = "latest"
POINTER_KEY_UPDATED_AT = "updated_at"
```

**Step 2: Replace literals**

In `pointer_update.py`: replace `"current.json"`, `"/snapshots/"`, `"last_passing"`, `"latest"`, `"updated_at"` with imports from `gcp.image.config.result_paths`.  
In `bmt_manager_base.py`: replace `"latest.json"`, `"ci_verdict.json"`, `"ci_verdicts"`, `"manager_summary.json"` with constants.  
In `root_orchestrator.py`: replace `"bmt_root_results.json"`, `"manager_summary.json"`.  
In `verdict_aggregation.py` and `github_checks.py`: replace `"manager_summary.json"`, `"ci_verdict.json"`, `"logs/"` with constants.

**Step 3: Run tests**

Run: `uv run python -m pytest tests/ -v -k "pointer or bmt_manager or verdict or trigger" --tb=short -x`  
Expected: PASS (no behavior change).

**Step 4: Commit**

`refactor(gcp/image): centralize result path constants in config/result_paths.py`

### Task 2.2: Status and conclusion enums

**Files:**
- Create or modify: `gcp/image/config/status.py` (or add to `config/constants.py`)
- Modify: `gcp/image/vm_watcher.py`, `gcp/image/github/github_checks.py`, `gcp/image/github/status_file.py`, `gcp/image/verdict_aggregation.py`

**Step 1: Define enums**

Use `enum.StrEnum` (Python 3.11+) for values that are compared to strings (e.g. GitHub API, status file). Example:

```python
# gcp/image/config/status.py
from __future__ import annotations
from enum import StrEnum

class CommitStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"

class CheckConclusion(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    NEUTRAL = "neutral"
    CANCELLED = "cancelled"
```

Add run outcome / conclusion enums as needed for status_file and verdict_aggregation (e.g. `completed`, `cancelled`, `skipped`, `pass`, `warning`).

**Step 2: Replace string literals**

In vm_watcher, github_checks, status_file, verdict_aggregation: replace `"pending"`, `"success"`, `"failure"`, etc., with enum members. Use `.value` only where the API requires a plain str; StrEnum compares equal to its value.

**Step 3: Run tests and commit**

Run: `uv run python -m pytest tests/vm tests/github tests/ -v --tb=short -x`  
Commit: `refactor(gcp/image): add status/conclusion enums and use in vm_watcher, github_checks, status_file, verdict_aggregation`

### Task 2.3: Trigger resolution decision/reason constants

**Files:**
- Modify: `gcp/image/trigger_resolution.py` and optionally `gcp/image/config/trigger.py`

**Step 1:** Define constants or a StrEnum for decision/reason codes: `ACCEPTED`, `REJECTED`, `JOBS_SCHEMA_INVALID`, `JOBS_CONFIG_MISSING`, `BMT_NOT_DEFINED`, `BMT_DISABLED`, `MANAGER_MISSING`, etc.

**Step 2:** Replace all string literals in trigger_resolution (and callers) with these constants.

**Step 3: Run tests and commit**

Run: `uv run python -m pytest tests/vm/ tests/ci/ -v -k trigger --tb=short`  
Commit: `refactor(gcp/image): constants for trigger resolution decision/reason codes`

---

## Phase 3: Value objects and config dataclasses

### Task 3.1: BucketPaths / GcsPaths value object

**Files:**
- Create: `gcp/image/models/paths.py` (or `gcp/image/value_objects.py`)
- Modify: `gcp/image/vm_watcher.py`, `gcp/image/root_orchestrator.py`, `gcp/image/trigger_resolution.py`, `gcp/image/pointer_update.py` (and others that pass code_bucket_root, runtime_bucket_root repeatedly)

**Step 1: Define BucketPaths**

```python
# gcp/image/models/paths.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class BucketPaths:
    code_root: str
    runtime_root: str
    bucket_name: str = ""  # optional, for display
```

**Step 2:** Add helpers in utils or gcs_helpers to build `BucketPaths` from bucket name (using existing _code_bucket_root, _runtime_bucket_root). Refactor one call site (e.g. vm_watcher’s _process_run_trigger) to accept `BucketPaths` and use `paths.code_root` / `paths.runtime_root`. Run tests, then gradually replace other (code_bucket_root, runtime_bucket_root) pairs with `BucketPaths`.

**Step 3: Commit**

`refactor(gcp/image): add BucketPaths value object and use in trigger/orchestrator paths`

### Task 3.2: LegIdentity / RunLeg value object

**Files:**
- Modify: `gcp/image/models/paths.py` or new `gcp/image/models/trigger.py`
- Modify: `gcp/image/vm_watcher.py`, `gcp/image/trigger_resolution.py`, `gcp/image/root_orchestrator.py`

**Step 1: Define LegIdentity**

```python
@dataclass(frozen=True)
class LegIdentity:
    project: str
    bmt_id: str
    run_id: str
    index: int = -1
```

**Step 2:** Use LegIdentity in trigger_resolution (return list of LegIdentity where appropriate) and in vm_watcher when passing leg identity to orchestrator or status updates. Convert to/from dict at boundaries (GCS, subprocess argv) as needed.

**Step 3: Run tests and commit**

`refactor(gcp/image): add LegIdentity value object for leg/run identity`

### Task 3.3: RunOutputContext and GatePhaseResult (bmt_manager_base)

**Files:**
- Create: `gcp/image/projects/shared/run_context.py` (or under gcp/image/models/)
- Modify: `gcp/image/projects/shared/bmt_manager_base.py`

**Step 1: Define dataclasses**

```python
@dataclass
class GatePhaseResult:
    status: str
    reason_code: str
    gate: dict[str, Any]
    aggregate_score: float
    raw_score: float
    delta_from_previous: float | None
    failed_count: int
    previous_latest: dict[str, Any] | None
    demo_force_pass: bool
```

```python
@dataclass
class RunOutputContext:
    result_payload: dict[str, Any]
    latest_local: Path
    snapshot_prefix: str
    status: str
    reason_code: str
    gate: dict[str, Any]
    aggregate_score: float
    raw_score: float
    delta_from_previous: float | None
    failed_count: int
    demo_force_pass: bool
    started_at: str
    start_timestamp: float
    setup_end_timestamp: float
    execution_end_timestamp: float
    outputs_prefix: str
```

**Step 2:** Refactor `_run_gate_phase` to return `GatePhaseResult` instead of a 9-tuple. Refactor `_write_run_outputs` to accept `RunOutputContext` (and optionally `GatePhaseResult`) instead of 18 positional arguments.

**Step 3: Run tests and commit**

Run: `uv run python -m pytest tests/projects/ tests/infra/ -v --tb=short -x`  
Commit: `refactor(gcp/image): GatePhaseResult and RunOutputContext for bmt_manager_base`

### Task 3.4: WatcherEnvConfig (run_watcher)

**Files:**
- Modify: `gcp/image/scripts/run_watcher.py`

**Step 1:** Define a small Pydantic model or dataclass `WatcherEnvConfig` with fields: bucket, project, repo_root, sub_effective (and any other values currently returned as a tuple from _setup_env_and_config). Have _setup_env_and_config return `WatcherEnvConfig | None`.

**Step 2:** Refactor main() to use the config object and pass it to _launch_watcher etc., reducing ad-hoc tuples.

**Step 3: Run tests and commit**

Run: `uv run python -m pytest tests/bootstrap/ -v --tb=short -x`  
Commit: `refactor(gcp/image): WatcherEnvConfig for run_watcher env/config`

---

## Phase 4: Typed payloads (TriggerPayload, LegSummary, ManagerSummary)

### Task 4.1: TriggerPayload and leg payload TypedDicts

**Files:**
- Create: `gcp/image/models/trigger.py` (or `gcp/image/schemas/trigger.py`)
- Modify: `gcp/image/vm_watcher.py`, `gcp/image/trigger_resolution.py`

**Step 1:** Define TypedDict (or Pydantic) for run trigger payload: e.g. legs, repository, sha, workflow_run_id, run_context, bucket, status_context, runtime_status_context, pull_request_number, server_url. Use it in _download_and_parse_trigger return type and wherever the payload is read.

**Step 2:** Define TypedDict for a resolved leg (index, project, bmt_id, run_id, decision, reason). Use in _resolve_requested_legs and _build_leg_lists.

**Step 3: Run tests and commit**

`refactor(gcp/image): TypedDict for trigger and leg payloads`

### Task 4.2: ManagerSummary / CiVerdict types

**Files:**
- Create: `gcp/image/models/summary.py`
- Modify: `gcp/image/pointer_update.py`, `gcp/image/verdict_aggregation.py`, `gcp/image/github/github_checks.py`, `gcp/image/projects/shared/bmt_manager_base.py`

**Step 1:** Define TypedDict or Pydantic model for manager summary (run_id, project_id, bmt_id, passed, ci_verdict_uri, etc.) and for ci_verdict. Use in pointer_update._update_pointer_and_cleanup, verdict_aggregation, and github_checks when reading summaries.

**Step 2: Run tests and commit**

`refactor(gcp/image): typed ManagerSummary and CiVerdict for pointer/verdict/checks`

---

## Phase 5: Extract modules to reduce complexity

### Task 5.1: Extract trigger processing pipeline from vm_watcher

**Files:**
- Create: `gcp/image/trigger_pipeline.py` (or `gcp/image/vm/trigger_processor.py`)
- Modify: `gcp/image/vm_watcher.py`

**Step 1:** Move the logic that: downloads trigger, resolves legs, builds leg lists, runs orchestrator loop, aggregates verdicts, updates pointers, and posts final status into a new module. Expose a single function e.g. `process_run_trigger(trigger_uri: str, paths: BucketPaths, workspace_root: Path, github_token_resolver: Callable) -> bool`. vm_watcher’s _process_run_trigger becomes a thin wrapper that builds BucketPaths and calls this function.

**Step 2:** Keep PR state checks and handshake/status writes in the pipeline or in vm_watcher; avoid circular imports. Run tests.

**Step 3: Commit**

`refactor(gcp/image): extract trigger processing pipeline from vm_watcher`

### Task 5.2: Extract gate/verdict helpers from bmt_manager_base

**Files:**
- Create: `gcp/image/projects/shared/gate.py` or `gcp/image/gate.py`
- Modify: `gcp/image/projects/shared/bmt_manager_base.py`

**Step 1:** Move _resolve_status, _gate_result, _all_failures_are_timeouts (and related) into a shared `gate.py` (or verdict.py). Import them in bmt_manager_base and in tests. This reduces bmt_manager_base size and makes gate logic reusable and testable in isolation.

**Step 2: Run tests and commit**

`refactor(gcp/image): extract gate/verdict helpers to shared module`

### Task 5.3: Fix script _log/_log_err (optional)

**Files:**
- Modify: `gcp/image/scripts/run_watcher.py`, `gcp/image/scripts/audit_vm_and_bucket.py`, and other scripts that define _log/_log_err but do not log the message

**Step 1:** Either implement _log/_log_err to actually write the message (to stderr or a log file) or remove them and use logging/print where needed. This improves readability and fixes the “unused parameter” smell.

**Step 2: Commit**

`fix(gcp/image): make script _log/_log_err actually log or remove`

---

## Phase 6: Final cleanup and docs

### Task 6.1: Prefer guard clauses and lookup tables

**Files:**
- Modify: selected files in `gcp/image/` that have long if/elif chains or deep nesting

**Step 1:** In 1–2 key files (e.g. trigger_resolution or vm_watcher), replace an if/elif chain with a dict lookup or early returns. Document the pattern in a short comment. No large-scale rewrite; one or two examples per file.

**Step 2: Commit**

`refactor(gcp/image): guard clauses and lookup table in selected modules`

### Task 6.2: Update docs and CLAUDE.md

**Files:**
- Modify: `docs/architecture.md`, `CLAUDE.md`, `gcp/image/scripts/README.md`

**Step 1:** Update architecture and CLAUDE to state that gcp/image has a single entrypoint (`python -m gcp.image`), document subcommands, and point to config/constants and config/result_paths for constants and to models/ for value objects and payload types.

**Step 2: Commit**

`docs: gcp/image single entrypoint, constants, and value objects`

---

## Verification and rollback

- **After each task:** Run `uv run python -m pytest tests/ -v --tb=line -x` (or the narrower scope given in the task). Fix any failures before the next task.
- **Ruff:** Run `ruff check gcp/image` and `basedpyright` after Phase 2 and Phase 4; fix new issues.
- **Rollback:** Each task is a single commit; revert by commit if a phase causes regressions.

---

## Execution handoff

Plan complete and saved to `docs/plans/2026-03-15-gcp-image-refactor.md`.

**Two execution options:**

1. **Subagent-driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Parallel session (separate)** — Open a new session with executing-plans and run through the plan task-by-task with checkpoints.

Which approach do you prefer?
