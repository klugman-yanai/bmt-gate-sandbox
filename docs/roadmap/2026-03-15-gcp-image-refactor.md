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

# gcp/image Single Entrypoint and Readability Refactor — Implementation Plan (Deepened)

## Enhancement Summary

**Deepened on:** 2026-03-15
**Sections enhanced:** Overview, Phase 1 (CLI), Phase 2 (constants), Phase 3 (value objects), Phase 4 (typed payloads), Phase 5 (extract modules), dependency and type strategy.
**Research agents used:** best-practices-researcher, architecture-strategist, code-simplicity-reviewer.

### Key Improvements

1. **CLI:** Do not mutate `sys.argv`. Refactor `vm_watcher.main()` (and other mains) to accept optional kwargs or a config object; Typer CLI parses options and calls `main(**opts)` or `main(config=...)`. Use `app(args=[...], standalone_mode=False)` for programmatic invocation if needed.
2. **Type strategy:** Use **dataclasses** (frozen where appropriate) for value objects and internal config (BucketPaths, LegIdentity, WatcherEnvConfig, GatePhaseResult). Use **TypedDict** for all JSON-at-boundary payloads (trigger, leg, manager summary, ci_verdict). Use **Pydantic** only where it already exists (e.g. BmtConfig) or for validation/coercion (e.g. env loading). WatcherEnvConfig = dataclass, not Pydantic.
3. **Dependency layering:** Enforce L0 (constants/enums, leaf, no gcp.image imports) → L1 (value objects, typed payloads) → L2 (config) → L3 (utils, gcs_helpers) → L4 (trigger_resolution, pointer_update, verdict_aggregation, gate) → L5 (vm_watcher, root_orchestrator, bmt_manager_base). Document in plan; keeps payloads and gate free of orchestration to avoid circular imports.
4. **Phase order:** Introduce typed payloads (Phase 4) **before** extracting the trigger pipeline and gate module (Phase 5), so new modules use typed payloads from the start.
5. **YAGNI:** Introduce **GatePhaseResult** first; refactor `_write_run_outputs` to take GatePhaseResult plus remaining args. Add **RunOutputContext** only if the call site is still unwieldy. Drop **CommitRef** from the plan unless a concrete use appears. Consider **one** `gcp/image/models.py` (or `payloads.py`) for value objects and TypedDicts; split only if it grows past ~200 lines. **Defer** Task 5.2 (extract gate/verdict) until after Phase 3; then decide based on bmt_manager_base size.
6. **Constants:** Prefer one or two config modules (e.g. `config/constants.py` for result paths + trigger codes, `config/status.py` for StrEnums) instead of many small files.
7. **Trigger pipeline:** Add only `gcp/image/trigger_pipeline.py`; do not create `gcp/image/vm/`. Pipeline is a facade called by vm_watcher; keep VM bootstrap contract unchanged (path_utils.VM_WATCHER_SCRIPT, scripts/run_watcher.py).
8. **Payload contract:** Document in plan or docs/architecture.md: trigger, ack, status, and CI verdict payload shapes are defined in gcp/image; CI and VM both use these types; CI may import from gcp.image (config + payloads) with one-way dependency.

### New Considerations Discovered

- Lazy subcommand registration: register Typer subcommands inside `main()` (or a wire function) so heavy deps (GCS, GitHub) are not loaded for `--help`.
- gate.py must not import bmt_manager_base or GCS; only constants, enums, and plain data (e.g. GatePhaseResult). bmt_manager_base and verdict_aggregation import from gate.
- path_utils ↔ config: any new constants module must be L0-only so both can import it without cycles. If you later move VM_WATCHER_SCRIPT (or other path constants) into L0, have path_utils re-export or import from L0 so path_utils remains the single public name for on-image paths; optional for this refactor.

### Technical review (post-deepen)

- **Consistency:** Phase order, dependency rules, type strategy, and YAGNI/deferrals are consistent. No sys.argv mutation and config-based CLI are reflected in Phase 1 tasks.
- **Clarifications applied:** (1) L4 now explicitly includes trigger_pipeline and github_status/github_checks; L0 includes log_config; gate must not import verdict_aggregation or bmt_manager_base. (2) Phase 2: default constants layout pinned to a single `config/constants.py` unless it grows too large; path_utils and L0 consumers use that module. (3) GatePhaseResult lives in L1 (`gcp/image/models.py`); gate.py (L4) is logic-only and imports from models. (4) Task 5.1: handshake stays inside the pipeline; pipeline must not import vm_watcher. (5) Task 6.1: concrete target added (trigger_resolution decision/reason → dict lookup + early returns; optional second pass in vm_watcher).

---

**Tools and design patterns used**

- **Single CLI entrypoint** — Typer app with subcommands (`watcher`, `orchestrator`, `run-watcher`, etc.) so all entrypoints are invoked via `python -m gcp.image <subcommand>`.
- **Constants and enums** — Centralized result-path strings and status/conclusion/trigger-decision codes as `enum.StrEnum` or constants in one or two config modules to remove magic strings.
- **Value objects** — Immutable dataclasses (`BucketPaths`, `LegIdentity`, etc.) to group related primitives and reduce long argument lists.
- **Config / result dataclasses** — `GatePhaseResult`, `WatcherEnvConfig` (and optionally `RunOutputContext`) to replace multi-argument functions and multi-tuple returns.
- **Typed payloads** — TypedDict for trigger, leg, manager summary, and CI verdict at boundaries (GCS, subprocess, API). Pydantic only where validation or existing config.
- **Parameter objects** — Single config/context objects passed into functions instead of many positional or keyword arguments.
- **Guard clauses and lookup tables** — Early returns and dict-based dispatch instead of long if/elif chains where it simplifies control flow.
- **Extract-module refactors** — Trigger-processing pipeline and gate/verdict logic moved into dedicated modules to shrink `vm_watcher.py` and `bmt_manager_base.py` and improve testability.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** One root entrypoint for gcp/image (`main.py` or `__main__.py`), replace magic strings with constants/enums, introduce config and value objects (dataclasses/TypedDict/Pydantic where appropriate) to cut parameter counts and improve type-safety, and reduce complexity/lines while improving readability.

**Architecture:** (1) Add `gcp/image/__main__.py` as the single CLI entrypoint using Typer subcommands; CLI parses options and calls existing `main()` with kwargs or a config object (no sys.argv mutation). (2) Centralize result-path and status/conclusion strings in one or two config modules (e.g. `config/constants.py`, `config/status.py`) and use enums/constants everywhere. (3) Introduce value objects (BucketPaths, LegIdentity) and config/result dataclasses (GatePhaseResult, WatcherEnvConfig; RunOutputContext only if needed) so functions take one or few objects. (4) Use TypedDict for trigger/leg/manager summary/CI verdict payloads at boundaries. (5) Extract trigger-processing into a facade module; extract gate/verdict helpers after Phase 3 if bmt_manager_base remains large. Enforce dependency layering (constants leaf → models → config → utils → pipeline/gate → orchestration).

**Tech Stack:** Python 3.12, Pydantic (existing config only), Typer (for CLI), pathlib, enum.StrEnum (3.11+), dataclasses, TypedDict. No new runtime dependencies beyond Typer if not already present. Rich is not used in gcp/image.

### Dependency rules (research-backed)

- **L0 (leaf):** Only the **new** constants/status modules (result-path names, status/conclusion enums, trigger decision codes, log_config). No imports from other gcp.image modules. path_utils remains L3 and does not import L0 unless we move path-related constants into L0 (optional). config (L2) may import from L0.
- **L1:** Value objects (BucketPaths, LegIdentity), TypedDict payloads (trigger, leg, manager summary, ci_verdict), **GatePhaseResult** (in `gcp/image/models.py`). May use L0 only.
- **L2:** Config (WatcherEnvConfig, BmtConfig, etc.). May use L0, L1.
- **L3:** utils, gcs_helpers, path_utils. May use L0–L2.
- **L4:** trigger_resolution, trigger_cleanup, pointer_update, verdict_aggregation, **trigger_pipeline** (new), **github_status / github_checks**, gate (new, logic only). May use L0–L3. Must not import vm_watcher or root_orchestrator. **gate must not import verdict_aggregation or bmt_manager_base**; only bmt_manager_base and verdict_aggregation import from gate.
- **L5:** vm_watcher, root_orchestrator, bmt_manager_base. May use L0–L4.

---

## Phase 1: Single root entrypoint

### Research Insights

**Best practices:**

- Do not build `sys.argv` and call `main()`; it is fragile and breaks tests and programmatic use.
- Either: (1) Refactor each `main()` to accept optional kwargs or a config object, and have Typer callbacks parse options and call `main(**opts)` or `main(config=...)`; or (2) Use Click’s `app(args=["sub", "--opt"], standalone_mode=False)` for programmatic invocation without mutating sys.argv.
- Prefer thin CLI, fat core: CLI only parses and builds config; core logic is in a function that takes config. Tests call the core function directly.
- Register subcommands inside a `main()` or wire function so heavy imports (GCS, GitHub) happen only when the CLI runs, not when `--help` is printed.

**Implementation detail (config-based CLI):**

```python
# cli.py - watcher callback
@app.command()
def watcher(bucket: str = typer.Option(...), workspace_root: str = typer.Option(""), ...) -> None:
    config = WatcherConfig(bucket=bucket, workspace_root=workspace_root, ...)
    raise SystemExit(vm_watcher_main(config))

# vm_watcher.py - main accepts config or kwargs
def main(config: WatcherConfig | None = None) -> int:
    opts = config or _parse_argv()  # _parse_argv() for backward compat when run as script
    ...
```

**VM bootstrap:** Keep path_utils.VM_WATCHER_SCRIPT and scripts/run_watcher.py as the deploy contract; `python -m gcp.image` is the implementation detail. vm_watcher.py can remain a thin wrapper that calls the same code. **CLI exposes both** `watcher` (vm_watcher) and `run-watcher` (scripts/run_watcher); startup continues to use scripts/run_watcher.py so the VM contract is unchanged.

### Task 1.1: Add Typer-based CLI skeleton and **main**.py

**Files:**

- Create: `gcp/image/cli.py`
- Create: `gcp/image/__main__.py`
- Modify: `gcp/image/path_utils.py` (ensure VM_WATCHER_SCRIPT / entrypoint names stay consistent)

**Step 1: Add Typer dependency (if missing)**

Check: `grep -r typer pyproject.toml uv.lock 2>/dev/null || true`
If Typer is not in the root project, add it to the workspace member that provides gcp. Root already has `typer>=0.15.0`; add to gcp/image member only if running as standalone package.

**Step 2: Create CLI module with subcommand stubs**

Create `gcp/image/cli.py` with a Typer app. For the watcher subcommand: parse options, build a small config object (or kwargs), and call `vm_watcher.main(config=...)` or `vm_watcher.main(**opts)`. Do **not** set `sys.argv` and then call `main()`. Lazy-import vm_watcher inside the callback to avoid pulling GCS/GitHub on `--help`.

**Step 3: Create **main**.py**

Create `gcp/image/__main__.py` that imports `app` from `gcp.image.cli` and runs `app()`.

**Step 4: Verify entrypoint**

Run: `uv run python -m gcp.image watcher --help`
Expected: Typer shows options for watcher.

**Step 5: Commit**

`feat(gcp/image): add single CLI entrypoint (Typer) and __main__.py`

### Task 1.2: Wire orchestrator and run-watcher subcommands

**Files:**

- Modify: `gcp/image/cli.py`
- Modify: `gcp/image/scripts/run_watcher.py` (optional: keep as thin wrapper that calls `python -m gcp.image run-watcher` or import and call run_watcher_main)

Same pattern: parse options, build config or kwargs, call orchestrator main / run_watcher main with that config. No sys.argv mutation. Expose both `watcher` (vm_watcher) and `run-watcher` (scripts/run_watcher) as subcommands; startup keeps using scripts/run_watcher.py so the VM deploy contract is unchanged.

### Task 1.3: Document single entrypoint and update startup (optional)

**Files:**

- Modify: `gcp/image/scripts/README.md`
- Optionally: `gcp/image/scripts/startup_entrypoint.sh` and `.github/bmt/ci/resources/startup_entrypoint.sh`

Document that the canonical way to run the watcher is `python -m gcp.image watcher ...`. Keep VM_WATCHER_SCRIPT and scripts/run_watcher.py as the deploy contract unless you explicitly switch startup to `python -m gcp.image run-watcher` after refactoring mains to accept config.

---

## Phase 2: Constants and enums

### Research Insights

**Simplicity:** Prefer one or two config modules (e.g. `config/constants.py` for result paths + trigger decision/reason codes, `config/status.py` for StrEnums) instead of four+ tiny files. If everything fits, a single `config/constants.py` is fine.

**Layering:** Constants/enums must be L0 (leaf): no imports from other gcp.image modules. Both path_utils and config can then import this module without cycles.

**Default constants layout (pin):** Use a single `config/constants.py` for result-path names and trigger decision/reason codes unless it grows too large; add `config/status.py` only then. path_utils and all L0 consumers MUST import from this chosen module to avoid duplication and cycles.

### Task 2.1: Result path constants

**Files:**

- Create or modify: `gcp/image/config/constants.py` (or keep separate `config/result_paths.py` if you prefer)
- Modify: `gcp/image/pointer_update.py`, `gcp/image/projects/shared/bmt_manager_base.py`, `gcp/image/root_orchestrator.py`, `gcp/image/verdict_aggregation.py`, `gcp/image/github/github_checks.py`

Define constants: CURRENT_JSON, LATEST_JSON, CI_VERDICT_JSON, MANAGER_SUMMARY_JSON, BMT_ROOT_RESULTS_JSON, SNAPSHOTS_PREFIX, LOGS_PREFIX, POINTER_KEY_LAST_PASSING, POINTER_KEY_LATEST, POINTER_KEY_UPDATED_AT. Replace literals in the listed files.

### Task 2.2: Status and conclusion enums

**Files:**

- Create or modify: `gcp/image/config/status.py` (or add to `config/constants.py`)
- Modify: `gcp/image/vm_watcher.py`, `gcp/image/github/github_checks.py`, `gcp/image/github/status_file.py`, `gcp/image/verdict_aggregation.py`

Use `enum.StrEnum` for CommitStatus, CheckConclusion, and any run-outcome values. Replace string literals in the listed files.

### Task 2.3: Trigger resolution decision/reason constants

**Files:**

- Modify: `gcp/image/trigger_resolution.py`; optionally add to `gcp/image/config/constants.py`

Define constants or StrEnum for decision/reason codes (ACCEPTED, REJECTED, JOBS_SCHEMA_INVALID, etc.). Replace literals in trigger_resolution and callers.

---

## Phase 3: Value objects and config dataclasses

### Research Insights

**Value objects:** Use `@dataclass(frozen=True)` for BucketPaths, LegIdentity so they are hashable and immutable. Group related parameters into one type; pass one object instead of many arguments.

**RunOutputContext vs GatePhaseResult:** Introduce **GatePhaseResult** first. Refactor `_write_run_outputs` to take GatePhaseResult plus the remaining arguments (paths, timestamps, etc.). Add **RunOutputContext** only if the call site is still unwieldy (YAGNI).

**WatcherEnvConfig:** Use a **dataclass** (or NamedTuple), not Pydantic; a small bundle from _setup_env_and_config does not need validation.

**Module layout:** Consider a single `gcp/image/models.py` (or `payloads.py`) containing BucketPaths, LegIdentity, GatePhaseResult, and later TypedDicts. Split into models/paths.py, models/trigger.py, models/summary.py only when: (1) the file grows beyond ~200 lines (primary criterion), or (2) a subset has a clear boundary with zero or minimal imports from other model submodules so splitting doesn’t introduce circular or heavy cross-imports within models/. **GatePhaseResult lives in L1** (`gcp/image/models.py`); `gcp/image/gate.py` (L4) is logic-only and imports GatePhaseResult from models. Do not put GatePhaseResult in gate.py.

### Task 3.1: BucketPaths value object

**Files:**

- Create: `gcp/image/models/paths.py` or add to `gcp/image/models.py`
- Modify: `gcp/image/vm_watcher.py`, `gcp/image/root_orchestrator.py`, `gcp/image/trigger_resolution.py`, `gcp/image/pointer_update.py`

Define `@dataclass(frozen=True) class BucketPaths: code_root, runtime_root, bucket_name=""`. Add helper to build from bucket name. Refactor call sites to accept BucketPaths.

### Task 3.2: LegIdentity value object

**Files:**

- Add to `gcp/image/models/paths.py` or `gcp/image/models.py`
- Modify: `gcp/image/vm_watcher.py`, `gcp/image/trigger_resolution.py`, `gcp/image/root_orchestrator.py`

Define `@dataclass(frozen=True) class LegIdentity: project, bmt_id, run_id, index=-1`. Use in trigger_resolution and vm_watcher; convert to/from dict at GCS/subprocess boundaries.

### Task 3.3: GatePhaseResult (and optionally RunOutputContext)

**Files:**

- Create or modify: `gcp/image/models.py` (L1) — add GatePhaseResult here (not in gate.py).
- Modify: `gcp/image/projects/shared/bmt_manager_base.py`

Define **GatePhaseResult** in **L1** (`gcp/image/models.py`) in this task; gate.py (Phase 5) will only import it from here—do not define GatePhaseResult in gate.py. Refactor `_run_gate_phase` to return GatePhaseResult. Refactor `_write_run_outputs` to accept GatePhaseResult plus remaining args. Add RunOutputContext only if still needed.

### Task 3.4: WatcherEnvConfig (run_watcher)

**Files:**

- Modify: `gcp/image/scripts/run_watcher.py`

Define a **dataclass** WatcherEnvConfig (bucket, project, repo_root, sub_effective, etc.). Have _setup_env_and_config return `WatcherEnvConfig | None`. Refactor main() to use the config object.

---

## Phase 4: Typed payloads (TriggerPayload, LegSummary, ManagerSummary)

### Research Insights

**Type strategy:** Use **TypedDict** for all JSON-at-boundary payloads: trigger payload, leg payload, manager summary, ci_verdict. You already get dicts from orjson.loads/GCS; TypedDict gives type hints without adding Pydantic. Use Pydantic only where validation is required (e.g. env loading) or where it already exists.

**Order:** Do Phase 4 **before** Phase 5 (extract trigger pipeline and gate) so the new modules use typed payloads from the start.

**Payload contract:** Document that trigger, ack, status, and CI verdict shapes are defined in gcp/image; CI and VM both use these types; CI may import from gcp.image (config + payloads) with one-way dependency.

### Task 4.1: TriggerPayload and leg payload TypedDicts

**Files:**

- Create: `gcp/image/models/trigger.py` or add to `gcp/image/models.py`
- Modify: `gcp/image/vm_watcher.py`, `gcp/image/trigger_resolution.py`

Define TypedDict for run trigger payload (legs, repository, sha, workflow_run_id, run_context, bucket, status_context, etc.) and for resolved leg (index, project, bmt_id, run_id, decision, reason). Use in _download_and_parse_trigger and _resolve_requested_legs /_build_leg_lists.

### Task 4.2: ManagerSummary / CiVerdict TypedDicts

**Files:**

- Create: `gcp/image/models/summary.py` or add to `gcp/image/models.py`
- Modify: `gcp/image/pointer_update.py`, `gcp/image/verdict_aggregation.py`, `gcp/image/github/github_checks.py`, `gcp/image/projects/shared/bmt_manager_base.py`

Define TypedDict for manager summary and for ci_verdict. Use in pointer_update, verdict_aggregation, github_checks when reading summaries.

---

## Phase 5: Extract modules to reduce complexity

### Research Insights

**Trigger pipeline:** Implement as a **facade** that vm_watcher calls (e.g. `trigger_pipeline.process(trigger_uri, ...)`). Composes: discover → resolve → handshake → run legs → pointer update → cleanup → status. Add **only** `gcp/image/trigger_pipeline.py`; do not create `gcp/image/vm/`. Keep trigger_resolution, trigger_cleanup, pointer_update, verdict_aggregation as-is; pipeline orchestrates them.

**Gate extraction:** Create `gcp/image/gate.py` (or `gcp/image/projects/shared/gate.py`) with _gate_result, _resolve_status, and GatePhaseResult. gate.py must **not** import bmt_manager_base or GCS; only L0/L1 (constants, enums, plain data). bmt_manager_base and verdict_aggregation import from gate. **Defer** this task until after Phase 3; then decide based on bmt_manager_base size and testability.

**Circular imports:** Ensure payloads/models do not import vm_watcher, trigger_pipeline, or anything that pulls in GitHub/GCS. Keep lazy imports in vm_watcher for heavy deps.

### Task 5.1: Extract trigger processing pipeline from vm_watcher

**Files:**

- Create: `gcp/image/trigger_pipeline.py`
- Modify: `gcp/image/vm_watcher.py`

Move the logic: download trigger, resolve legs, build leg lists, run orchestrator loop, aggregate verdicts, update pointers, post final status into trigger_pipeline. Expose e.g. `process_run_trigger(trigger_uri, paths: BucketPaths, workspace_root: Path, github_token_resolver, ...) -> bool`. vm_watcher’s _process_run_trigger builds BucketPaths and calls this. **Handshake** (build ack payload and upload to handshake URI) and **status posting** (commit status, check run) stay inside the pipeline, using trigger_resolution, gcs_helpers, and the injected github_token_resolver (or callables passed from vm_watcher), so the flow is not split across two call sites. The pipeline must **not** import vm_watcher so that only vm_watcher imports the pipeline.

### Task 5.2: Extract gate/verdict helpers from bmt_manager_base (defer until after Phase 3)

**Files:**

- Create: `gcp/image/gate.py` or `gcp/image/projects/shared/gate.py`
- Modify: `gcp/image/projects/shared/bmt_manager_base.py`, optionally `gcp/image/verdict_aggregation.py`

Move _resolve_status, _gate_result, _all_failures_are_timeouts into gate.py. gate.py depends only on constants/enums and GatePhaseResult. bmt_manager_base and verdict_aggregation import from gate. Run tests.

### Task 5.3: Fix script _log/_log_err (optional)

**Files:**

- Modify: `gcp/image/scripts/run_watcher.py`, `gcp/image/scripts/audit_vm_and_bucket.py`, etc.

Either implement _log/_log_err to write the message or remove them and use logging/print where needed.

---

## Phase 6: Final cleanup and docs

### Task 6.1: Prefer guard clauses and lookup tables

**Concrete target:** In `trigger_resolution.py`, replace the decision/reason if/elif chain (e.g. around accepted/rejected/skip) with a single dict mapping `(decision, reason)` or a key string to outcome, and use early returns for invalid input. Optionally do a second pass in `vm_watcher` for one similar branch. Document the pattern in a short comment. Scope: 1–2 files only.

### Task 6.2: Update docs and CLAUDE.md

Update docs/architecture.md, CLAUDE.md, gcp/image/scripts/README.md: single entrypoint `python -m gcp.image`, subcommands, config/constants and config/result_paths (or constants.py/status.py), models/ for value objects and payload types. Add a short “Payload contract” subsection in **docs/architecture.md** (and optionally in this plan) if not already present: trigger/ack/status/verdict shapes defined in gcp/image; CI and VM use these types.

---

## Verification and rollback

- **After each task:** Run `uv run python -m pytest tests/ -v --tb=line -x` (or the narrower scope given in the task). Fix any failures before the next task.
- **Ruff:** Run `ruff check gcp/image` and `basedpyright` after Phase 2 and Phase 4; fix new issues.
- **Rollback:** Each task is a single commit; revert by commit if a phase causes regressions. Revert is feature-flag-free (no toggles to maintain).

---

## Execution handoff

Plan complete and saved to `docs/roadmap/2026-03-15-gcp-image-refactor.md`.

**Two execution options:**

1. **Subagent-driven (this session)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Parallel session (separate)** — Open a new session with executing-plans and run through the plan task-by-task with checkpoints.

Which approach do you prefer?
