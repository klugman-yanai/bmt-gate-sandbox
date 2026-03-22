# gcp/image Refactor: Constants, Types, Entrypoint, Decoupling

**Status:** Proposed
**Urgency:** HIGH IMPACT
**Goal:** Eliminate magic strings, enforce type safety at all boundaries, establish a single config-driven entrypoint, and structurally decouple the monolithic `vm_watcher.py` into testable modules. This is the foundation for containerization and Cloud Run migration.

> **Supersedes:** `2026-03-15-gcp-image-refactor-alpha.md`. Key change: invocation is **config-driven** (env + payload); **no Typer/argparse CLI**. The alpha plan used Typer; this plan adopts the holistic plan's position that contributor and entrypoint code must not use CLI parsing.

---

## Reading Guide

This document is part of a 5-document roadmap series, split from the former holistic serverless migration plan.

| # | Document | Focus | Urgency |
|---|----------|-------|---------|
| 1 | [gcp-data-separation-and-dev-workflow.md](gcp-data-separation-and-dev-workflow.md) | Bug fixes, manifest, FUSE, WorkspaceLayout | MOST URGENT |
| **2** | **gcp-image-refactor.md** (this) | Constants, types, entrypoint, decoupling | **HIGH** |
| 3 | [contributor-api-and-manager-contract.md](contributor-api-and-manager-contract.md) | Protocol, BaseBmtManager, contributor workflow | HIGH |
| 4 | [cloud-run-containerization-and-infra.md](cloud-run-containerization-and-infra.md) | Dockerfile, Cloud Run, Pulumi, coordinator | MEDIUM |
| 5 | [ci-cutover-and-vm-decommission.md](ci-cutover-and-vm-decommission.md) | Direct API, shadow testing, cutover | LOWER |

**Dependency chain:** 1 → 2+3 → 4 → 5

**Depends on:** Document 1 (gcp/ data separation) must be completed first.
**Co-dependent with:** Document 3 (contributor API) — Phase 1 models are used by the contributor contract; tasks 3.5/3.6 from Phase 3 are in document 3.

---

## Dependency Layering

Enforce strict import layering to prevent circular dependencies:

| Layer | Modules | May import from |
| :--- | :--- | :--- |
| **L0** (constants/enums, leaf) | `config/constants.py`, `config/status.py`, `log_config` | No `gcp.image` imports |
| **L1** (value objects, typed payloads) | `models.py` | L0 only |
| **L2** (config) | `config.py` (load_config) | L0, L1 |
| **L3** (utils, GCS helpers) | `gcs_helpers.py`, `path_utils` | L0, L1, L2 |
| **L4** (pipeline, gate, status) | `trigger_pipeline.py`, `trigger_resolution.py`, `pointer_update.py`, `verdict_aggregation.py`, `gate.py`, `github_status.py`, `github_checks.py` | L0–L3 |
| **L5** (orchestration) | `vm_watcher.py`, `root_orchestrator.py`, `bmt_manager_base.py` | L0–L4 |

**Key constraint:** `gate.py` must have ZERO dependencies on GCS, orchestration, or `bmt_manager_base`. It imports only from L0–L1.

---

## Type Strategy

- **Dataclasses** (frozen where appropriate) for value objects and internal config: `BucketPaths`, `LegIdentity`, `WorkspacePaths`, `GatePhaseResult`, `ManagerConfig`.
- **TypedDict** for all JSON-at-boundary payloads: `TriggerPayload`, `LegSummary`, `ManagerSummary`, `CiVerdict`.
- **Pydantic** only where it already exists (e.g. `BmtConfig`) or for validation/coercion (e.g. env loading).
- **No raw untyped dicts** (`dict[str, Any]`) at any API or internal boundary.

---

## Phase 1: Boundary Foundations (Constants & Models)

**Goal:** Eliminate magic strings and enforce type safety at all GCS and subprocess boundaries.

- [ ] **1.1 Result Path Constants (L0 Leaf)**
  - **File:** `gcp/image/config/constants.py`
  - **Task:** Define `CURRENT_JSON`, `LATEST_JSON`, `CI_VERDICT_JSON`, `MANAGER_SUMMARY_JSON`, `SNAPSHOTS_PREFIX`, `LOGS_PREFIX`.
  - **Task:** Define pointer keys: `POINTER_KEY_LAST_PASSING`, `POINTER_KEY_LATEST`.
  - **Task:** Define registry path constant(s), e.g. `RUNTIME_CONFIG_PREFIX` and `BMT_PROJECTS_FILENAME`, so the orchestrator loads the project registry from GCS at a well-known path (no registry baked into the image). Support optional `BMT_REGISTRY_URI` override; when unset, derive from bucket + `RUNTIME_CONFIG_PREFIX`/`BMT_PROJECTS_FILENAME`.

- [ ] **1.2 Status & Conclusion Enums (L0 Leaf)**
  - **File:** `gcp/image/config/status.py`
  - **Task:** Use `enum.StrEnum` for `CommitStatus` (pending, success, error, failure) and `CheckConclusion` (success, failure, neutral, cancelled).

- [ ] **1.3 Trigger Decision Constants**
  - **File:** `gcp/image/config/constants.py`
  - **Task:** Define codes: `ACCEPTED`, `REJECTED`, `JOBS_SCHEMA_INVALID`, `SUPERSEDED`.

- [ ] **1.4 Intuitive value classes (framework-defined; no raw dicts)**
  - **File:** `gcp/image/models.py` (or `gcp/image/contracts/models.py`)
  - **Task:** The framework defines **intuitive value classes** (dataclasses or frozen dataclasses); **no raw untyped dicts** in the API or internal boundaries. Required shapes include:
    - **Identity / paths:** `BucketPaths` (`code_root`, `runtime_root`, `bucket_name`), `LegIdentity` (`project`, `bmt_id`, `run_id`, `index`), `WorkspacePaths` (e.g. `workspace_root`, `staging_dir`, `cache_base`, `outputs_dir`, `logs_dir`).
    - **Config for managers:** `ManagerConfig` (e.g. `leg_identity`, `bucket_paths`, `jobs_config`, `workspace_paths`, `run_context`, `limit`); `BmtJobsConfig` (or nested value classes) for runner, paths, template_uri, gate, **optional input file discovery** (e.g. `input_file_extensions: ["*.wav"]` or glob pattern) so the base class can recursively collect input files from the inputs root (including subdirs) without contributor code, and **optional project-specific parsing config** (e.g. keyword, regex) so that each BMT can define how to parse its runner's CLI output.
    - **Results and runner I/O:** `FileRunResult` (per-file result: `file`, `exit_code`, `status`, `error`, plus **project-specific fields** as typed attributes). `RunnerIdentity`, `GateResult`. Use these in Protocol method signatures instead of `dict[str, Any]`.
    - **Results (boundaries):** `GatePhaseResult` (`status`, `summary`, `metrics`).
  - **Task:** Prefer immutable value classes (`frozen=True`) where appropriate; use descriptive attribute names.

- [ ] **1.5 Typed boundary payloads (value classes / TypedDict; no raw dicts)**
  - **File:** `gcp/image/models.py`
  - **Task:** All boundary payloads are **typed**: use dataclasses or TypedDict (or Pydantic models), never `dict[str, Any]`. Define `TriggerPayload` (legs, repository, sha, workflow_run_id, run_context), `LegSummary` (index, project, bmt_id, decision, reason), `ManagerSummary`, `CiVerdict`, and any registry/ack/status shapes as value classes or TypedDict with full field typing.

- [ ] **1.6 Trigger/Handshake Payload Completeness**
  - **File:** `gcp/image/models.py`
  - **Task:** Ensure trigger payload includes `bucket`, `ref`, and `triggered_at` where required by status/check and traceability flows.
  - **Task:** Add typed shapes for ack/status payloads used by handoff and coordinator stages.

- [ ] **1.7 Artifact Schema Versioning**
  - **Files:** `gcp/image/models.py`, `gcp/image/schemas/`
  - **Task:** Define schema-versioned models for canonical JSON artifacts and explicit JSONL event record shapes.
  - **Task:** Add compatibility policy for additive/non-breaking changes in contributor-generated artifacts.

- [ ] **1.8 Declarative config (JSON schema + typed models, minimal boilerplate)**
  - **Files:** `gcp/image/schemas/` (e.g. `bmt_jobs.schema.json`, `bmt_registry.schema.json`), `gcp/image/models.py` or Pydantic/dataclass loaders.
  - **Task:** Define **JSON schemas** for jobs config and registry; load and validate at the boundary (GCS fetch, file read) into **Pydantic or dataclass** models. **No raw untyped dicts**: the result of loading is always a typed value class or config class (e.g. `BmtRegistry`, `BmtJobsConfig`), not `dict[str, Any]`.
  - **Task:** Base class (or a factory) builds `ManagerConfig` and any project-specific config from the **validated** declarative config. Derived manager classes **do not** parse config or pluck keys.

### Research Insights (Phase 1)

**Best Practices:**
- Keep boundary payloads as **typed** value classes or TypedDict; never use raw untyped dicts. Separate DTOs from core domain value objects to avoid transport-driven coupling.
- Add constants for trigger families (`triggers/runs`, `triggers/acks`, `triggers/status`) alongside result constants for a single path contract.
- Keep decision/reason constants aligned with existing lowercase codes used by CI/runtime to avoid drift.

**Implementation Details:**
- Include optional typed shapes for ack/status payloads in addition to trigger/verdict payloads.
- Reserve a small compatibility map for legacy keys while migrating to stricter models.

**Edge Cases:**
- Missing payload keys (`bucket`, `ref`, `triggered_at`) can silently break handshake/check flows; include/validate explicitly.
- Generic constants like `SUPERSEDED` should map to concrete reasons used in runtime status reporting.

**References:**
- [Cloud Run Jobs overview](https://cloud.google.com/run/docs/create-jobs)
- [gcloud run jobs execute](https://cloud.google.com/sdk/gcloud/reference/run/jobs/execute)

---

## Phase 2: Single Entrypoint & Config-Driven Invocation

**Goal:** One entrypoint at image root; invocation is **config-driven** (env vars and optionally a single payload file or JSON in env). No CLI (argparse/Typer). Aligns with container/serverless patterns (Cloud Run Jobs, 12-factor).

- [ ] **2.1 Single entrypoint `main.py` at image root (config-driven)**
  - **File:** `gcp/image/main.py` (at the root of the image folder; in repo, this is the single entrypoint script that will live at image root).
  - **Task:** Implement `main.py` as the only entrypoint. **Do not use argparse or Typer.** Import **intuitively named operations** from submodules: `load_config()` (from env + optional payload), `run_watcher(config)`, `run_orchestrator(config)`. `main()` loads config, then calls the right runner based on config (e.g. `config.mode`). Implementation lives in submodules; `main.py` only composes the calls.
  - **Task:** No other executable scripts at image root; rest of code in submodules.
  - **Principle:** Comments and docstrings explain **why**, never **what**.

- [ ] **2.2 Config loading (env + optional payload)**
  - **Files:** `gcp/image/config.py` (or equivalent under a submodule), used by `main.py`.
  - **Task:** Implement `load_config()` that reads **environment variables** (e.g. `BMT_MODE`, `GCS_BUCKET`, `BMT_PAYLOAD_PATH`) and optionally a **single structured payload** (JSON file at path from env, or JSON string in an env var). Return a **typed config object** (e.g. `EntrypointConfig` with `mode`, `bucket`, `payload` or leg-specific fields). No CLI parsing; no argparse/Typer. Validation at load time; clear errors for missing/invalid config.
  - **Requirement:** Heavy modules (GCS, GitHub) are not imported at config-load time; only env and file reads.

- [ ] **2.3 Watcher and orchestrator as callables**
  - **Files:** `gcp/image/watcher.py` (or under a submodule), `gcp/image/orchestrator.py` (or equivalent).
  - **Task:** Implement run logic to accept typed config objects (e.g. `WatcherConfig`, `OrchestratorConfig` or a unified `EntrypointConfig`). No `sys.argv` in library code. `main.py` calls `load_config()` then `run_watcher(config)` or `run_orchestrator(config)`.

- [ ] **2.4 Legacy wrapper compatibility (optional)**
  - **File:** `gcp/image/scripts/run_watcher.py` (optional compatibility script).
  - **Task:** If kept, make it a thin wrapper that sets env (e.g. `BMT_MODE=watcher`) and invokes `python main.py`. Prefer directing users to set env and run `main.py` directly.

### Research Insights (Phase 2)

**Best Practices:**
- Config-driven invocation avoids CLI surface and fits container/serverless runtimes (env and payload are the standard inputs).
- Keep side effects behind injected ports/config objects for testability.

**Implementation Details:**
- Ensure config models are typed (dataclass or Pydantic); `WatcherConfig`/`OrchestratorConfig` (or unified config) accept injected ports for tests.
- Smoke tests: `BMT_MODE=watcher python main.py` (with minimal env) and orchestrator path with a payload file.

---

## Phase 3: Structural Decoupling & Logic Extraction

**Goal:** Shrink the monolithic `vm_watcher.py` and isolate scoring logic into testable modules.

> **Note:** Tasks 3.5 (contributor API contract) and 3.6 (parsing boundary) are in [contributor-api-and-manager-contract.md](contributor-api-and-manager-contract.md) because they define the contributor-facing API surface.

- [ ] **3.1 Extract Trigger Processing Pipeline**
  - **File:** `gcp/image/trigger_pipeline.py`
  - **Task:** Move download trigger, **resolve legs** (parse trigger payload into a typed list of legs, e.g. `list[LegIdentity]`), handshake (Ack), and result aggregation into a facade. Replace or refactor `root_orchestrator.py` so orchestration is invoked via `run_orchestrator(config)` from the single entrypoint; remove or deprecate the standalone script.
  - **Requirement:** Pipeline must NOT import `vm_watcher`.

- [ ] **3.2 Extract Gate/Verdict Logic**
  - **File:** `gcp/image/gate.py`
  - **Task:** Move `_gate_result`, `_resolve_status`, and `_all_failures_are_timeouts` from `bmt_manager_base.py`.
  - **Requirement:** `gate.py` must have ZERO dependencies on GCS or Orchestration.

- [ ] **3.3 Guard Clauses & Lookup Tables**
  - **File:** `gcp/image/trigger_resolution.py`
  - **Task:** Replace the long `if/elif` chain for decision/reason with a **typed** lookup (e.g. mapping from decision enum to reason; no raw dicts with string keys).

- [ ] **3.4 Coordinator Logic Extraction**
  - **File:** `gcp/image/coordinator.py` (new)
  - **Task:** Extract aggregation, pointer update, status/check posting, and trigger cleanup from watcher-centric flow into reusable coordinator logic.
  - **Requirement:** Coordinator module must be runnable from CI post-step or dedicated Cloud Run coordinator job.
  - **Task (log dump → Check Run):** The coordinator must own log dump generation for failure cases. On any non-success outcome, the coordinator: (1) collects recent log content (watcher log + per-leg runner log tails from `{results_prefix}/snapshots/{run_id}/logs/`); (2) uploads the concatenated content to GCS under the well-known log dumps prefix via `log_config.dump_logs_to_gcs()`; (3) generates a signed URL via `generate_signed_url()` (3-day expiry); (4) passes `log_dump_url` to `github_checks.render_results_table()` so the link appears in the Check Run summary on the **Checks tab** of the PR. This applies to gate failures, timeouts, and unhandled crashes — the Check Run summary must always contain a clickable log dump link when the conclusion is `failure`.

### Research Insights (Phase 3)

**Best Practices:**
- Define extraction boundaries as ports/adapters: trigger pipeline should orchestrate interfaces, not concrete cloud helpers.
- Keep gate logic framework-free and I/O-free to maximize deterministic unit coverage.

**Implementation Details:**
- Add mock adapters (GCS, GitHub status, orchestrator runner) so Phase 1-3 unit tests run without network/subprocess dependencies.
- Use a single decision-reason lookup table with exhaustive tests for unsupported/superseded/schema-invalid branches.

**Edge Cases:**
- Ensure pipeline can represent partial leg failures and timeouts without collapsing all outcomes into one reason code.

**References:**
- [Python `typing.Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

---

## Done When

Constants and value classes are in place; single entrypoint `main.py` loads config from env and optional payload and invokes watcher or orchestrator; trigger pipeline is extracted and must NOT import `vm_watcher`; gate/trigger/coordinator logic is extracted. All checklist items are complete and unit tests pass.

[Document 4 (cloud-run-containerization-and-infra.md)](cloud-run-containerization-and-infra.md) depends on completion of this document and [document 3](contributor-api-and-manager-contract.md).

---

## Verification

| Phase | Method |
| :--- | :--- |
| **1-3** | `pytest tests/` — unit tests for types, extraction, gate logic, trigger pipeline |
