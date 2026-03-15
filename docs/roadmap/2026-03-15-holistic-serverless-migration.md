# Holistic Serverless Migration: Detailed Implementation Plan

**Status:** Proposed / Integrated Master Plan
**Date:** 2026-03-15
**Goal:** A high-fidelity, meticulously ordered migration to a serverless architecture. This plan integrates the **Refactor Alpha** (code quality/structure) with the **Cloud Run Jobs Migration** (infrastructure/scalability) to solve the "40GB startup wall" and support 20+ projects.

---

## Reading Guide

- **What is authoritative:** checklist tasks in each phase and the verification matrix.
- **What is advisory:** each `Research Insights` block (implementation guidance and pitfalls).
- **Artifact terminology:** use **JSON** for canonical control/state artifacts and **JSONL** for high-volume telemetry streams.

### Quick Navigation

- **Contract + contributor API:** `Core Image Contract Redesign Opportunity`, `How to add a new project or BMT manager`, Phase 1, Phase 3
- **Cloud Run/GCS Fuse infra:** Phase 4, Phase 5
- **Coordinator/failure semantics:** Phase 6, Phase 7
- **Cutover/rollback:** Phase 8, Verification Matrix

### Plan structure (higher-level grouping)

Phases are grouped into three **parts** to separate code/contract work from infrastructure and from cutover:

| Part | Phases | Focus |
| :--- | :--- | :--- |
| **I — Refactor Alpha (Code & Contract)** | 1–3 | Boundary foundations, CLI, structural decoupling; testable contract-driven code |
| **II — Container & Cloud Run** | 4–6 | Containerization, Pulumi Job + GCS Fuse, scale and coordinator model |
| **III — CI & Cutover** | 7–8 | Direct API handoff, shadow run, cutover, VM decommission |

---

## Enhancement Summary

**Deepened on:** 2026-03-15  
**Sections enhanced:** 9 (Phases 1-8 + Verification Matrix)  
**Research inputs used:** architecture, security, performance, flow completeness, docs quality, Cloud Run/GCS Fuse/WIF implementation guidance

### Key Improvements

1. Added explicit ownership requirements for aggregation, pointer update (`current.json`), status/check posting, and cleanup in the Cloud Run model.
2. Tightened Cloud Run + GCS Fuse implementation details (mount options, task model, memory/cache tradeoffs, WIF/IAM scoping, CI execution semantics).
3. Added measurable migration/cutover guardrails (shadow parity, rollback drill, observability thresholds, and go/no-go checks).

### New Considerations Discovered

- Do not run direct API trigger and Eventarc fallback in a way that can produce duplicate executions.
- Define post-execution coordinator behavior before cutover to preserve existing pointer/snapshot semantics.
- Prefer least-privilege WIF + SA bindings and digest-pinned container execution for safer CI handoff.
- Use **JSON** for canonical control/state artifacts and **JSONL** for high-volume telemetry streams.

---

## Core Image Contract Redesign Opportunity

**Why now:** This migration is a strong opportunity to redesign `gcp/image` as the canonical API/interface that contributors use when implementing new BMTs.

### Decision: API Surface for Contributor BMTs

| Option | Pros | Cons | Recommendation |
| :--- | :--- | :--- | :--- |
| **Documentation-only contract** | Fast to start; low tooling overhead | Drifts easily; weak enforcement | Use only as supplemental narrative docs |
| **Type-stub contract (`.pyi` + Protocols/TypedDicts)** | Strong static guidance; editor-native contributor UX; low runtime coupling | Needs CI type-checking discipline | **Primary contract surface** |
| **Base class contract (runtime ABC)** | Runtime guardrails; clear required hooks; easier onboarding | Can become rigid/over-coupled if overloaded | **Secondary runtime contract** for required lifecycle hooks |
| **Wheel-distributed API package** | Versioned contract; strict dependency boundary | Release/versioning overhead; slows iteration early | Defer until API stabilizes across 2-3 migration iterations |

### Chosen Direction (This Plan)

- Use a **hybrid contract**:
  1. `Protocol` + `TypedDict`/`dataclass` models as the primary interface specification
  2. Thin runtime `BaseBmtManager` ABC for mandatory lifecycle methods
  3. Contributor documentation with one minimal and one advanced reference implementation
- Keep contributor API **Python-native and non-RESTful**:
  - implement lifecycle hooks and typed contracts in code, not HTTP endpoints
  - use class-based manager implementations and typed method signatures as the extension surface
- Use **boundary validation**:
  - JSON schema for canonical JSON artifacts (`current.json`, `ci_verdict.json`, `manager_summary.json`)
  - Runtime parser validation for runner stdout and JSONL telemetry before conversion to internal typed models
- Defer standalone wheel packaging until contract churn drops and versioning policy is ready.

### Image layout (single entrypoint + submodules)

The container image must have **one single entrypoint**, `main.py`, at the image root. All other code lives in **submodules** under a single top-level package; no other executable scripts at the image root.

- **Entrypoint:** `main.py` at image root (e.g. `/app/main.py`). It is the only script invoked by the container runtime; it delegates to the Typer CLI (watcher, orchestrator, or other subcommands).
- **Submodules:** All other code is organized under one package (e.g. `gcp/image/` or a dedicated `bmt/` package) with clear subpackages: `config/`, `contracts/`, `coordinator`, `gate`, `projects/`, etc. No free-floating modules at the image root besides `main.py`.
- **Rationale:** Single entrypoint simplifies `CMD`/`ENTRYPOINT`, tooling, and onboarding; submodules keep boundaries clear and avoid a flat, hard-to-navigate root.

---

## How to add a new project or BMT manager

This section describes the **contributor workflow** for adding a new project or BMT manager using the API, with **exact code examples**.

**Prerequisites:** Phase 1–3 contract and layout are in place (constants, models, CLI, `BaseBmtManager`, contracts, `bmt_projects.json`).

**Steps:**

1. **Create a project package** under the shared projects tree, e.g. `gcp/image/projects/<project_name>/`.
   - Add `bmt_manager.py` (or the module name defined by the project registry).
   - Add any project-specific config, runners, or assets under the same directory.

2. **Implement the manager against the contract**
   - Subclass `BaseBmtManager` and implement the required lifecycle hooks (e.g. `run_leg`, summary emission).
   - Use the typed models from `gcp/image/models.py` and the contracts from `gcp/image/contracts/` for inputs and outputs (e.g. `LegIdentity`, `ManagerSummary`, `CiVerdict`).
   - Use constants from `gcp/image/config/constants.py` for result paths and trigger decisions; use enums from `config/status.py` for status/conclusion.
   - Ensure runner stdout or JSONL telemetry is parsed through the parsing-boundary validation layer so gate/coordinator logic only see normalized typed models.

3. **Register the project**
   - Add an entry to `gcp/image/bmt_projects.json` (or the configured project registry): project name, `manager_script` path (e.g. `projects/<project_name>/bmt_manager.py`), and `jobs_config` path.
   - Ensure the jobs config conforms to the artifact contract (canonical JSON for control, JSONL only for telemetry where defined).

4. **Validate and test**
   - Run the layout/contract tests (e.g. `pytest tests/` for type and extraction tests).
   - Run a local or CI leg that invokes the new manager via the single entrypoint (`main.py` → orchestrator subcommand → project manager) and confirm `manager_summary` and `ci_verdict` are produced and conform to schemas.

---

### Exact code examples

**1. Registry entry in `gcp/image/bmt_projects.json`**

Add one object to the projects list (or the structure your repo uses):

```json
{
  "acme": {
    "manager_script": "projects/acme/bmt_manager.py",
    "jobs_config": "projects/acme/config/bmt_jobs.json"
  }
}
```

If the registry is a list of projects with a `name` field:

```json
{
  "name": "acme",
  "manager_script": "projects/acme/bmt_manager.py",
  "jobs_config": "projects/acme/config/bmt_jobs.json"
}
```

**2. Minimal manager class in `gcp/image/projects/acme/bmt_manager.py`**

Implement every abstract method; use shared constants and models for paths and artifact shapes.

```python
"""Minimal BMT manager for project 'acme'. Implement all abstract methods."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from gcp.image.config.constants import (
    CI_VERDICT_JSON,
    LATEST_JSON,
    MANAGER_SUMMARY_JSON,
    SNAPSHOTS_PREFIX,
)
from gcp.image.models import LegIdentity, ManagerSummary, CiVerdict  # Phase 1 types
from gcp.image.projects.shared.bmt_manager_base import BmtManagerBase, parse_args as _base_parse_args


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Acme BMT manager")
    parser.add_argument("--jobs-config", required=True)
    return _base_parse_args(parser)


class AcmeBmtManager(BmtManagerBase):
    """Concrete BMT manager for the Acme project."""

    def setup_assets(self) -> None:
        """Download/cache runner, template, dataset. Set self.runner_path, self._inputs_root."""
        self._inputs_root = self.staging_dir / "inputs"
        self._inputs_root.mkdir(parents=True, exist_ok=True)
        # ... sync runner/template/dataset from GCS; set self.runner_path, self.cache_stats
        self.runner_path = self.cache_base / "runner" / "my_runner_bin"

    def collect_input_files(self, inputs_root: Path) -> list[Path]:
        """Return list of input files to process (e.g. WAVs)."""
        return sorted(inputs_root.rglob("*.wav"))

    def run_file(self, input_file: Path, inputs_root: Path) -> dict[str, Any]:
        """Run BMT on one file. Return dict with file, exit_code, status, error, and any scores."""
        # Invoke runner binary; parse stdout through parsing-boundary layer.
        return {
            "file": str(input_file.relative_to(inputs_root)),
            "exit_code": 0,
            "status": "ok",
            "error": "",
            "score": 42.0,
        }

    def compute_score(self, file_results: list[dict[str, Any]]) -> float:
        """Aggregate score from per-file results (e.g. mean of score)."""
        if not file_results:
            return 0.0
        return sum(r.get("score", 0.0) for r in file_results) / len(file_results)

    def get_runner_identity(self) -> dict[str, Any]:
        """Runner metadata for latest.json / traceability."""
        return {"name": "acme_runner", "build_id": "local", "source_ref": ""}

    def _evaluate_gate(
        self,
        aggregate_score: float,
        last_score: float | None,
        failed_count: int,
        file_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Pass/fail vs baseline. Use gate config from self.bmt_cfg; optionally _gate_result()."""
        from gcp.image.projects.shared.bmt_manager_base import _gate_result
        comparison = (self.bmt_cfg.get("gate") or {}).get("comparison", "gte")
        return _gate_result(
            comparison, aggregate_score, last_score, failed_count, self.run_context
        )


def main() -> None:
    args = parse_args()
    bmt_cfg = {}  # load from args.jobs_config and resolve leg
    manager = AcmeBmtManager(args, bmt_cfg)
    raise SystemExit(manager.run())
```

**3. Single entrypoint `main.py` (image root)**

The image root has one script that delegates to the Typer app; no other executables at root.

```python
#!/usr/bin/env python3
"""Single entrypoint for the BMT image. Delegates to the Typer CLI."""

from gcp.image.cli import app

if __name__ == "__main__":
    app()
```

Invocation examples:

```bash
python main.py --help
python main.py run-watcher --bucket gs://my-bucket ...
python main.py run-orchestrator --leg-json '{"project":"acme","bmt_id":"...", ...}'
```

**4. Jobs config path (canonical JSON)**

Reference a JSON file that conforms to the artifact contract (no JSONL for control state). Example shape:

```json
{
  "runner": { "uri": "runners/acme_runner" },
  "paths": {
    "dataset_prefix": "datasets/acme",
    "results_prefix": "acme/results",
    "outputs_prefix": "acme/outputs"
  },
  "template_uri": "projects/acme/input_template.json",
  "gate": { "comparison": "gte", "tolerance_abs": 0.0 }
}
```

---

No changes to `main.py` or the orchestrator are required when adding a new project; only the new project package and the registry entry.

---

## Artifact Contract (JSON + JSONL)

**Goal:** Separate control-plane state from high-volume telemetry while preserving reliability and debuggability.

### Canonical Artifacts (JSON)

- `current.json` (pointer state)
- `ci_verdict.json` (gate source of truth)
- `manager_summary.json` (per-leg deterministic summary)
- trigger/ack/status payload JSON files

**Contract:**

- Must validate against versioned JSON schemas before upload and after download at coordinator boundaries.
- Must remain stable and compact; these files are the operational source of truth.

### Telemetry Artifacts (JSONL)

- Per-file runner events
- Parsing diagnostics and extraction traces
- Optional per-leg progress streams

**Contract:**

- One JSON object per line (JSONL), append-friendly for large outputs.
- Parsed and normalized before aggregation; malformed lines are counted and surfaced as explicit parse errors.
- Telemetry never replaces canonical verdict/pointer JSON artifacts.

---

## Part I — Refactor Alpha (Code & Contract)

Phases 1–3: boundary foundations, single entrypoint/CLI, and structural decoupling. Delivers type-safe contracts, testable extraction, and a clear contributor API.

---

## Phase 1: Boundary Foundations (Constants & Models)

**Goal:** Eliminate magic strings and enforce type safety at all GCS and subprocess boundaries.

- [ ] **1.1 Result Path Constants (L0 Leaf)**
  - **File:** `gcp/image/config/constants.py`
  - **Task:** Define `CURRENT_JSON`, `LATEST_JSON`, `CI_VERDICT_JSON`, `MANAGER_SUMMARY_JSON`, `SNAPSHOTS_PREFIX`, `LOGS_PREFIX`.
  - **Task:** Define pointer keys: `POINTER_KEY_LAST_PASSING`, `POINTER_KEY_LATEST`.
- [ ] **1.2 Status & Conclusion Enums (L0 Leaf)**
  - **File:** `gcp/image/config/status.py`
  - **Task:** Use `enum.StrEnum` for `CommitStatus` (pending, success, error, failure) and `CheckConclusion` (success, failure, neutral, cancelled).
- [ ] **1.3 Trigger Decision Constants**
  - **File:** `gcp/image/config/constants.py`
  - **Task:** Define codes: `ACCEPTED`, `REJECTED`, `JOBS_SCHEMA_INVALID`, `SUPERSEDED`.
- [ ] **1.4 Value Objects (L1 Models)**
  - **File:** `gcp/image/models.py`
  - **Task:** `@dataclass(frozen=True) class BucketPaths`: `code_root`, `runtime_root`, `bucket_name`.
  - **Task:** `@dataclass(frozen=True) class LegIdentity`: `project`, `bmt_id`, `run_id`, `index`.
  - **Task:** `class GatePhaseResult`: `status`, `summary`, `metrics`.
- [ ] **1.5 Typed Boundary Payloads (TypedDict)**
  - **File:** `gcp/image/models.py`
  - **Task:** `TriggerPayload`: `legs[]`, `repository`, `sha`, `workflow_run_id`, `run_context`.
  - **Task:** `LegSummary`: `index`, `project`, `bmt_id`, `decision`, `reason`.
  - **Task:** `ManagerSummary` and `CiVerdict` shapes.
- [ ] **1.6 Trigger/Handshake Payload Completeness**
  - **File:** `gcp/image/models.py`
  - **Task:** Ensure trigger payload includes `bucket`, `ref`, and `triggered_at` where required by status/check and traceability flows.
  - **Task:** Add typed shapes for ack/status payloads used by handoff and coordinator stages.
- [ ] **1.7 Artifact Schema Versioning**
  - **Files:** `gcp/image/models.py`, `gcp/image/schemas/`
  - **Task:** Define schema-versioned models for canonical JSON artifacts and explicit JSONL event record shapes.
  - **Task:** Add compatibility policy for additive/non-breaking changes in contributor-generated artifacts.

### Research Insights (Phase 1)

**Best Practices:**

- Keep DTO payloads (`TypedDict`) separate from core domain value objects to avoid transport-driven coupling.
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

## Phase 2: Single Entrypoint & CLI Refactor

**Goal:** Standardize invocation via one entrypoint at image root and a config-based Typer CLI; all other code in submodules.

- [ ] **2.1 Single entrypoint `main.py` at image root**
  - **File:** `gcp/image/main.py` (at the root of the image folder; in repo, this is the single entrypoint script that will live at image root).
  - **Task:** Implement `main.py` as the only entrypoint: it initializes and runs the Typer app (e.g. `app()`). No other executable scripts at image root.
  - **Task:** Ensure the rest of the codebase is organized in submodules (e.g. `config/`, `contracts/`, `coordinator`, `gate`, `projects/`) and imported from `main.py` or the Typer app, not invoked as scripts.
- [ ] **2.2 Typer CLI skeleton in a submodule**
  - **Files:** `gcp/image/cli.py` (or equivalent under a submodule), invoked by `main.py`.
  - **Task:** Implement `app = typer.Typer()`. Expose `watcher` and `orchestrator` as subcommands.
  - **Requirement:** Lazy-import heavy modules (GCS/GitHub) inside callbacks to keep `--help` fast.
- [ ] **2.3 Refactor watcher/orchestrator into callables**
  - **Files:** `gcp/image/watcher.py` (or under a submodule), `gcp/image/orchestrator.py` (or equivalent).
  - **Task:** Implement run logic to accept `WatcherConfig` or `OrchestratorConfig` objects; no `sys.argv` in library code. `main.py` → Typer → these callables.
- [ ] **2.4 Legacy wrapper compatibility**
  - **File:** `gcp/image/scripts/run_watcher.py` (optional compatibility script).
  - **Task:** If kept, make it a thin wrapper that invokes the single entrypoint (e.g. `python main.py run-watcher` or `python -m <package> run-watcher` where the package entrypoint is `main.py`). Prefer directing users to `main.py` for all invocations.

### Research Insights (Phase 2)

**Best Practices:**

- Treat CLI entrypoints as adapters only; move side effects behind injected ports/config objects.
- Keep `--help` fast by preserving lazy imports for cloud clients and GitHub integrations.

**Implementation Details:**

- Ensure `WatcherConfig`/`OrchestratorConfig` can accept injected ports (GCS, GitHub, runner execution) for testability.
- Keep wrapper scripts compatibility-only and prohibit new logic there.

**Edge Cases:**

- Hidden `sys.argv` assumptions in helper modules can survive refactors; add smoke tests for `python -m gcp.image --help`, `watcher`, and `orchestrator`.

**References:**

- [Typer docs](https://typer.tiangolo.com/)

---

## Phase 3: Structural Decoupling & Logic Extraction

**Goal:** Shrink the monolithic `vm_watcher.py` and isolate scoring logic into testable modules.

- [ ] **3.1 Extract Trigger Processing Pipeline**
  - **File:** `gcp/image/trigger_pipeline.py`
  - **Task:** Move download trigger, resolve legs, handshake (Ack), and result aggregation into a facade.
  - **Requirement:** Pipeline must NOT import `vm_watcher`.
- [ ] **3.2 Extract Gate/Verdict Logic**
  - **File:** `gcp/image/gate.py`
  - **Task:** Move `_gate_result`, `_resolve_status`, and `_all_failures_are_timeouts` from `bmt_manager_base.py`.
  - **Requirement:** `gate.py` must have ZERO dependencies on GCS or Orchestration.
- [ ] **3.3 Guard Clauses & Lookup Tables**
  - **File:** `gcp/image/trigger_resolution.py`
  - **Task:** Replace the long `if/elif` chain for decision/reason with a dict-based lookup.
- [ ] **3.4 Coordinator Logic Extraction**
  - **File:** `gcp/image/coordinator.py` (new)
  - **Task:** Extract aggregation, pointer update, status/check posting, and trigger cleanup from watcher-centric flow into reusable coordinator logic.
  - **Requirement:** Coordinator module must be runnable from CI post-step or dedicated Cloud Run coordinator job.
- [ ] **3.5 Contributor API Contract Module Structure**
  - **Files:** `gcp/image/contracts/`, `gcp/image/projects/shared/`
  - **Task:** Define `Protocol`/TypedDict contract for project managers (`run_leg`, summary emission, error typing).
  - **Task:** Add thin `BaseBmtManager` ABC for runtime invariants and required hooks.
  - **Task:** Add contributor docs that mirror contract symbols and include compatibility checklist.
- [ ] **3.6 Parsing Boundary Validation Layer**
  - **Files:** `gcp/image/projects/shared/`, `gcp/image/contracts/`
  - **Task:** Add a dedicated parsing boundary for runner stdout/JSONL telemetry that validates and normalizes records before they enter gate/coordinator logic.
  - **Requirement:** Downstream gate and aggregation logic consumes normalized typed models only, never raw stdout lines.

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

## Part II — Container & Cloud Run

Phases 4–6: container image, Pulumi Cloud Run Job with GCS Fuse, scalability and coordinator semantics. Delivers a runnable Job and a defined post-execution coordinator model.

---

## Phase 4: High-Performance Containerization

**Goal:** Create a "Zero-Download" execution environment.

- [ ] **4.1 Create `gcp/image/Dockerfile`**
  - **Base:** `python:3.12-slim-bookworm`.
  - **Deps:** `libsndfile1`, `ffmpeg`, `curl`, `gnupg`, `uv`.
  - **Image layout:** One entrypoint at image root: `main.py` (e.g. `/app/main.py`). Copy the rest of the code into submodules under `/app` (e.g. `/app/config/`, `/app/contracts/`, `/app/projects/`, or `/app/gcp/image/` as a package). Set `PYTHONPATH` so `main.py` can import the package. `CMD`/`ENTRYPOINT` invoke only `python main.py` (with subcommand args).
  - **Code:** Copy `gcp/image` and `tools` so that the image root has exactly `main.py` and one top-level package; no other scripts at root.
- [ ] **4.2 Project "Plugin" packing**
  - **Task:** Bake the entire `gcp/image/projects/` tree into the image as a submodule (e.g. under `/app/projects/` or `/app/gcp/image/projects/`).
  - **Impact:** Orchestrator imports manager logic locally; no download from GCS at runtime.
- [ ] **4.3 Local validation**
  - **Task:** Build `bmt-orchestrator:latest`.
  - **Task:** Run `docker run -v $(pwd)/gcp/remote:/mnt/runtime -e GCS_BUCKET=... bmt-orchestrator run-orchestrator --leg-json='{...}'` (or equivalent via `main.py run-orchestrator ...`) to verify local FUSE simulation.

### Research Insights (Phase 4)

**Best Practices:**

- Keep runtime image lean and deterministic; pin toolchain versions and avoid dynamic installs at runtime.
- Treat project managers as baked plugins (`gcp/image/projects/**`) to remove startup download dependencies.

**Performance Considerations:**

- Cold start and mount readiness are major contributors; target smaller image layers and minimal import-time work.
- Build and push by digest, and execute by digest in CI to eliminate image drift during rollout.

**Implementation Details:**

- Add an image freshness gate equivalent to current VM image checks for `gcp/image/**` and Docker-affecting paths.

**Edge Cases:**

- Local bind mount and GCS Fuse behavior are not identical; keep local test as functional validation, not full perf proxy.

**References:**

- [Cloud Run container runtime contract](https://cloud.google.com/run/docs/container-contract)

---

## Phase 5: Cloud Run Gen 2 Infrastructure (Pulumi)

**Goal:** Provision the serverless backbone with mandatory GCS Fuse mounting.

- [ ] **5.1 Define Cloud Run Job (Gen 2)**
  - **Resource:** `gcp.cloudrunv2.Job`.
  - **Volume:** **Mandatory GCS Fuse Mount** mapping `gs://{BUCKET}/runtime` to `/mnt/runtime`.
  - **FUSE Tuning:** Set `file-cache`, `stat-cache-capacity`, and `type: "gcs"` for optimal read-heavy WAV streaming.
- [ ] **5.2 IAM & Secret Access**
  - **Task:** Create `bmt-job-runner` Service Account.
  - **Task:** Grant least-privilege, resource-scoped access:
    - `roles/storage.objectViewer` for required read paths
    - scoped write permissions only for result/pointer paths
    - secret-scoped access for required GitHub App secrets only
- [ ] **5.3 Artifact Registry**
  - **Task:** Provision Docker repository and set CI push permissions.
- [ ] **5.4 Trigger-Source Policy (Direct API vs Eventarc)**
  - **Task:** Choose and document one primary trigger path for CI (`direct-api` or `eventarc`) and enforce mutual exclusion.
  - **Requirement:** No configuration should allow duplicate execution for a single workflow run.
- [ ] **5.5 Security Hardening Prerequisites**
  - **Task:** Require WIF attribute conditions (`attribute.repository`, `attribute.repository_owner`, optional `attribute.ref`) for CI identity bindings.
  - **Task:** Scope secret access to specific GitHub App secrets; avoid broad project-level secret accessor grants.
  - **Task:** Define image digest enforcement policy for execution-time pinning.

### Research Insights (Phase 5)

**Best Practices:**

- Use Gen2 Cloud Run Jobs with explicit GCS volume mount options tuned for read-heavy workloads.
- Scope IAM to required resources and actions; prefer `run.invoker` where execute-only is sufficient.

**Performance Considerations:**

- Prefer mount options such as `only-dir=runtime`, `metadata-cache-ttl-secs`, `stat-cache-max-size-mb`, and `type-cache-max-size-mb`.
- Size container memory with Fuse cache + worker concurrency overhead in mind.

**Security Considerations:**

- Bind WIF with repository/branch conditions (`attribute.repository`, `attribute.repository_owner`, optional `attribute.ref`).
- Scope `iam.serviceAccountUser` to the job runtime SA only.
- Prefer secret-specific access and version pinning strategy for sensitive GitHub app credentials.

**Implementation Details:**

- Clarify trigger-source policy: direct API primary vs Eventarc fallback, and prevent dual active triggers.
- Prefer `roles/run.invoker` where execution-only is needed; use `roles/run.developer` only when deployment mutation is required.

**Edge Cases:**

- Fuse mount has startup timeout behavior; include retry/failure handling and clear status path when mount fails.
- Explicitly define Artifact Registry push identity and minimum permissions to avoid over-privileged build principals.

**References:**

- [Cloud Storage volume mounts for Cloud Run jobs](https://cloud.google.com/run/docs/configuring/jobs/cloud-storage-volume-mounts)
- [Cloud Run parallelism](https://cloud.google.com/run/docs/configuring/parallelism)
- [Workload Identity Federation with deployment pipelines](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)
- [Cloud Run IAM roles](https://cloud.google.com/run/docs/reference/iam/roles)

---

## Phase 6: Scalability & Performance Tuning

**Goal:** Enable native parallelism and handle 40GB datasets efficiently.

- [ ] **6.1 Native Task Parallelism**
  - **Task:** Map the GitHub Action handoff so one `execute` call spawns `N` tasks.
  - **Entrypoint:** Use `CLOUD_RUN_TASK_INDEX` to pick the leg from the trigger payload.
- [ ] **6.2 Dynamic Resource Overrides**
  - **Task:** Validate Cloud Run Job resource override capabilities; if per-task overrides are unavailable, implement **tiered jobs** (`bmt-heavy`, `bmt-light`) selected by leg profile.
  - **Task:** Define profile mapping rules (dataset size, workers, memory, cpu) in config.
- [ ] **6.3 Zero-Download Refactor (BMT Base)**
  - **File:** `gcp/image/projects/shared/bmt_manager_base.py`
  - **Task:** Detect `/mnt/runtime`. If present, bypass ALL `rsync` or download logic.
  - **Task:** Ensure `path_utils` resolves relative to the mount.
- [ ] **6.4 Post-Execution Coordinator**
  - **Task:** Define concrete coordinator runtime model:
    - Option A: dedicated Cloud Run coordinator job
    - Option B: CI post-step coordinator command
  - **Task:** Define summary artifact contract path (for example: `runtime/triggers/summaries/<workflow_run_id>/<leg>.json`) and optional JSONL telemetry path (for example: `runtime/triggers/telemetry/<workflow_run_id>/<leg>.jsonl`) with aggregation trigger condition.
  - **Task:** Coordinator must own final pointer updates, check/status publication, and cleanup.
- [ ] **6.5 Partial Failure and Retry Semantics**
  - **Task:** Specify behavior for missing leg summaries, retry exhaustion, partial success/failure outcomes, and final gate decision mapping.
  - **Task:** Ensure coordinator logic is idempotent for safe retries.

### Research Insights (Phase 6)

**Best Practices:**

- Keep one execution contract: one task = one leg, resolved by `CLOUD_RUN_TASK_INDEX` from the trigger payload.
- Add explicit worker/resource tiering rules in config so runtime behavior is predictable and reviewable.

**Performance Considerations:**

- For one-pass WAV reads, prioritize metadata cache tuning over aggressive file caching.
- Define resource tiers by dataset class (light/medium/heavy) with explicit CPU/RAM profiles.

**Implementation Details:**

- Add a coordinator requirement: after all tasks complete, aggregate outcomes, update pointer(s), prune stale snapshots, and persist run summary.
- Treat per-leg summary artifacts as the source of truth for aggregation, not task logs.
- Treat JSONL telemetry as observability input only; final decisions come from canonical summary/verdict JSON artifacts.

**Edge Cases:**

- Partial task failures must produce deterministic aggregate verdicts and non-ambiguous final status.
- Quota-driven parallelism limits should degrade gracefully (reduced parallelism or explicit failure reason).

**References:**

- [Cloud Run jobs retries](https://cloud.google.com/run/docs/jobs-retries)
- [Cloud Run task timeout](https://cloud.google.com/run/docs/configuring/task-timeout)

---

## Part III — CI & Cutover

Phases 7–8: direct API handoff, WIF/Eventarc policy, shadow run, cutover, and VM decommission. Delivers production CI on Cloud Run Jobs and retirement of the VM fleet.

---

## Phase 7: CI/CD Integration & Direct API

**Goal:** Replace async polling with synchronous, observable handoffs.

- [ ] **7.0 Trigger + Handshake Semantics (Cloud Run Model)**
  - **Task:** Define whether CI still writes run trigger files when direct API execution is used.
  - **Task:** Document handshake equivalence: `gcloud run jobs execute --wait` completion replaces VM ack semantics.
  - **Task:** Define explicit failure fallback behavior when job execution fails before summary aggregation.

- [ ] **7.1 Direct API Handoff**
  - **File:** `.github/workflows/bmt-handoff.yml`
  - **Task:** Use `gcloud run jobs execute` with the `--wait` flag.
  - **Task:** Stream container logs directly to the CI console.
- [ ] **7.2 WIF Identity Alignment**
  - **Task:** Grant GitHub WIF `roles/run.invoker` (or `roles/run.developer` only when deploy mutation is needed) and `roles/iam.serviceAccountUser` scoped to execution SA.
  - **Task:** Enforce repository/branch attribute conditions for WIF principal bindings.
- [ ] **7.3 Eventarc (Secondary/Internal Trigger)**
  - **Task:** Provision `gcp.eventarc.Trigger` as a fallback for GCS file-based triggers.
  - **Requirement:** Eventarc path must be mutually exclusive with direct API execution mode to prevent duplicate runs.
- [ ] **7.4 Cleanup Ownership in Job Model**
  - **Task:** Assign ownership for trigger/ack/status/summaries cleanup to the coordinator stage.
  - **Task:** Define cleanup order and safety checks to avoid deleting artifacts needed for postmortems.

### Research Insights (Phase 7)

**Best Practices:**

- Keep CI handoff synchronous (`--wait`) for deterministic workflow outcome and simpler rollback handling.
- Define status/check ownership explicitly (CI post-step vs job-side coordinator) before removing VM steps.

**Implementation Details:**

- Standardize execution command shape (`--tasks`, payload override/env, `--wait`) and failure interpretation.
- Ensure logs include `workflow_run_id`, `run_id`, `project`, `bmt_id`, `leg_index` as structured fields.
- If Eventarc remains, define exact non-overlapping activation condition vs direct API path.
- Enforce digest-pinned image execution for all production CI invocations.

**Edge Cases:**

- `--wait` completion does not by itself guarantee pointer update/status posting unless coordinator duties are explicitly wired.
- CLI output formatting on failures can vary; rely on execution state/artifact checks, not only CLI stdout parsing.

**References:**

- [Execute Cloud Run jobs](https://cloud.google.com/run/docs/execute/jobs)
- [Eventarc overview](https://cloud.google.com/eventarc/docs)

---

## Phase 8: Migration, Validation & Cutover

**Goal:** Safely decommission the VM fleet.

- [ ] **8.1 Shadow Testing (1-2 Days)**
  - **Task:** Run BOTH the VM and the Job in parallel.
  - **Task:** Compare `ci_verdict.json` parity.
- [ ] **8.2 Direct API Cutover**
  - **Task:** Set Cloud Run Job as the primary `BMT Gate` status provider.
  - **Task:** Remove `start-vm` and `wait-handshake` steps from CI.
- [ ] **8.2a Rollback Drill (Mandatory Before Decommission)**
  - **Task:** Execute a documented rollback to VM path (`BMT_EXECUTOR=vm` and legacy handoff path restoration) and verify one full successful gate run.
  - **Task:** Capture rollback RTO and operator checklist in roadmap references.
- [ ] **8.3 Decommissioning**
  - **Task:** Remove `infra/packer/` and `infra/scripts/enforce-image-family-policy.sh`.
  - **Task:** Delete GCE instances and images.

### Research Insights (Phase 8)

**Best Practices:**

- Use time-boxed shadow runs with explicit parity criteria before cutover.
- Require rollback drill completion before decommissioning VM infrastructure.

**Implementation Details:**

- Gate cutover on measurable checks: parity rate target, zero untriaged diffs, status/check correctness, and cleanup correctness.
- Keep a fast kill switch (`BMT_EXECUTOR=vm|job|shadow`) during hypercare.

**Edge Cases:**

- Superseded/closed PR logic must remain equivalent after migration to avoid posting stale statuses.
- Verify metadata cleanup and trigger deletion semantics still hold under job-based flow.

**References:**

- [Shadow shipping pattern](https://mergify.com/blog/shadow-shipping-how-we-double-executed-code-to-ship-safely)

---

## Verification Matrix

| Phase | Verification Method |
| :--- | :--- |
| **1-3** | `pytest tests/` (Unit tests for types and extraction) |
| **4** | `docker run` (Local FUSE simulation) |
| **5-6** | `just deploy` + Manual Job Execution in GCP Console |
| **5.5** | IAM/WIF policy validation (resource-scoped secrets/storage, attribute conditions, digest policy checks) |
| **7** | `gh run view` (Logs streaming in GitHub Actions) + fallback behavior verification |
| **8** | Verdict Parity Analysis |
| **8.2a** | Recorded rollback drill with successful VM-gated run |

**Interpretation note:** phase-level checks are blocking criteria for advancing to the next phase; `Research Insights` targets are optimization/quality goals unless promoted into checklist tasks.

### Research Insights (Verification)

**Best Practices:**

- Add explicit go/no-go gates with quantitative thresholds instead of qualitative checks only.

**Suggested Targets:**

- **Parity:** 100% verdict match for deterministic legs, or documented tolerance with triage for non-deterministic metrics.
- **Reliability:** Job completion success >= 99% over shadow window.
- **Performance:** Define baseline-relative target for heavy (40GB) legs and track p50/p95 runtime.
- **Security:** Verify effective IAM/WIF conditions before cutover.

**Additional Verification Checks:**

- Pointer correctness (`current.json latest/last_passing`) after mixed pass/fail task outcomes.
- Status/check run correctness for success, timeout, superseded, and schema-invalid scenarios.
- Cleanup behavior for triggers/acks/status artifacts after each workflow run family.
- Contributor API contract checks: stub/type compatibility, base-class hook coverage, and reference manager conformance.
- Artifact contract checks: canonical JSON schema validation and JSONL parse-error budget enforcement.
