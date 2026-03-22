# Contributor API and Manager Contract

**Status:** Proposed
**Urgency:** HIGH IMPACT
**Goal:** Define the canonical API surface and contributor workflow for BMT managers: Protocol, base class, config injection, declarative config, artifact contract, and reference implementations. This is the contract all future BMTs will implement.

> **Supersedes:** `2026-03-15-python-core-interface-architecture.md`. Key differences: (a) Protocol methods return typed value classes (e.g. `FileRunResult`), not `dict`; (b) no `lifecycle.py` hooks registry (YAGNI); (c) no `RuntimeStorage`/`GitHubClient` Protocols in the contributor surface (those are implementation details); (d) declarative config and minimal boilerplate are first-class design goals.

---

## Reading Guide

This document is part of a 5-document roadmap series, split from the former holistic serverless migration plan.

| # | Document | Focus | Urgency |
|---|----------|-------|---------|
| 1 | [gcp-data-separation-and-dev-workflow.md](gcp-data-separation-and-dev-workflow.md) | Bug fixes, manifest, FUSE, WorkspaceLayout | MOST URGENT |
| 2 | [gcp-image-refactor.md](gcp-image-refactor.md) | Constants, types, entrypoint, decoupling | HIGH |
| **3** | **contributor-api-and-manager-contract.md** (this) | Protocol, BaseBmtManager, contributor workflow | **HIGH** |
| 4 | [cloud-run-containerization-and-infra.md](cloud-run-containerization-and-infra.md) | Dockerfile, Cloud Run, Pulumi, coordinator | MEDIUM |
| 5 | [ci-cutover-and-vm-decommission.md](ci-cutover-and-vm-decommission.md) | Direct API, shadow testing, cutover | LOWER |

**Dependency chain:** 1 → 2+3 → 4 → 5

**Depends on:** Document 1 (gcp/ data separation).
**Co-dependent with:** Document 2 (gcp/image refactor) — Phase 1 models are used here; this document defines tasks 3.5/3.6 from Phase 3.

---

## Core Image Contract (Redesign Opportunity)

**Why now:** This migration is a strong opportunity to redesign `gcp/image` as the canonical API/interface that contributors use when implementing new BMTs.

### Decision: API Surface for Contributor BMTs

| Option | Pros | Cons | Recommendation |
| :--- | :--- | :--- | :--- |
| **Documentation-only contract** | Fast to start; low tooling overhead | Drifts easily; weak enforcement | Use only as supplemental narrative docs |
| **Type-stub contract (`.pyi` + Protocols/TypedDicts)** | Strong static guidance; editor-native contributor UX; low runtime coupling | Needs CI type-checking discipline | **Primary contract surface** |
| **Base class contract (runtime ABC)** | Runtime guardrails; clear required hooks; easier onboarding | Can become rigid/over-coupled if overloaded | **Secondary runtime contract** for required lifecycle hooks |
| **Wheel-distributed API package** | Versioned contract; strict dependency boundary | Release/versioning overhead; slows iteration early | Defer until API stabilizes across 2-3 migration iterations |

### Chosen Direction

Use a **hybrid contract** enforced by OOP only (no CLI/argparse in the contributor API):

1. **BmtManagerProtocol** (structural contract) defines the **method signatures** (parameters and return types) that any BMT manager must satisfy. The **contract surface** for the framework is the Protocol: orchestrator and callers type against `BmtManagerProtocol`, so alternative implementations (wrappers, adapters, or future mixin-based code) remain valid without changing the type contract.

2. **BaseBmtManager** is an ABC that **implements** `BmtManagerProtocol` and provides shared orchestration and defaults: `collect_input_files` (recursive walk with optional config for extensions/limit) and `run()` (orchestration loop). Contributors **typically subclass BaseBmtManager** and override the protocol methods they need; they may override `collect_input_files` only when they need custom discovery. Use **`@override`** (from `typing`) on every overridden method so intent is explicit and refactors are safe.

3. **Config is injected by the framework:** the orchestrator (or entrypoint) owns building typed config from **environment and/or a single structured payload**; it does not use a CLI (no argparse, no Typer). The entrypoint is **config-driven**: `main.py` loads config from env and optionally a payload file/path, then calls the appropriate operation. Contributors **never** parse CLI args; they receive config via the base constructor.

4. **The framework defines intuitive value classes** for all config and identity concepts (e.g. `LegIdentity`, `BucketPaths`, `ManagerConfig`, `BmtJobsConfig`, `WorkspacePaths`). Contributors work with clear, typed attributes instead of raw dicts or magic keys.

5. Contributor docs and reference implementations show only the class and its methods; no `main()` or `parse_args()` in the contributor surface.

### Design Principles

- **Comments and docstrings explain why, never what:** Do not use comments or docstrings to describe *what* the code does; the code should be clear from naming and structure. Reserve comments and docstrings for *why* (rationale, non-obvious constraints, business rules).
- **Strict typing; no raw untyped dicts:** The entire framework relies on **strict schemas and strong Pythonic typing**. Never use raw untyped `dict` (or `dict[str, Any]`) in the API or internal boundaries. Use **value classes**, **config classes**, and typed containers (e.g. `list[FileRunResult]`, not `list[dict[str, Any]]`). JSON at the boundary is deserialized into typed models; in-memory data stays in value classes.
- **Contributor API is purely OOP:**
  - **Implement the Protocol** by subclassing `BaseBmtManager` (recommended) or by providing any type that satisfies `BmtManagerProtocol`.
  - Override only the contract methods that are project-specific; use **`@override`** on each overridden method.
  - Receive configuration via constructor parameters (typed value classes with intuitive attribute names), not via argparse or env parsing.
- **Boundary validation:**
  - JSON schema for canonical JSON artifacts (`current.json`, `ci_verdict.json`, `manager_summary.json`)
  - Runtime parser validation for runner stdout and JSONL telemetry before conversion to internal typed models
- **Runner output is per-BMT; no single assumed format:** The framework **must not** assume that all runners produce the same CLI output. Each BMT may have **its own unique** runner and CLI output format; parsing is **project-specific** and implemented in the manager. Where multiple projects share a common output format, that parsing logic can be factored into a **reusable util** used by those projects only. The contract only requires that the manager return typed `FileRunResult`.
- **Declarative config, minimal boilerplate:** Use **declarative config** backed by JSON schemas and typed models. The **base class or framework** hydrates `ManagerConfig` from the declarative source and **automates input file collection**. Derived project BMT manager classes have **minimal boilerplate**: they receive a validated config and implement only the contract methods that are truly project-specific. **Goal: ask as little as possible of the dev adding a new BMT.**
- Defer standalone wheel packaging until contract churn drops and versioning policy is ready.

---

## Image Layout (Single Entrypoint + Submodules)

The container image must have **one single entrypoint**, `main.py`, at the image root. All other code lives in **submodules** under a single top-level package; no other executable scripts at the image root.

- **Entrypoint:** `main.py` at image root (e.g. `/app/main.py`). It is the only script invoked by the container runtime. **No CLI (argparse/Typer):** invocation is config-driven. Import intuitively named operations (e.g. `load_config`, `run_watcher`, `run_orchestrator`) from submodules; `main()` loads config from env and optional payload, then calls the right operation.
- **Submodules:** All other code is organized under one package (e.g. `gcp/image/` or a dedicated `bmt/` package) with clear subpackages: `config/`, `contracts/`, `coordinator`, `gate`, `projects/`, etc. No free-floating modules at the image root besides `main.py`.
- **Rationale:** Single entrypoint simplifies `CMD`/`ENTRYPOINT` and onboarding; naming and call order make the flow obvious without redundant prose.

---

## How to Add a New Project or BMT Manager

This subsection describes the **contributor workflow** and the **decoupled image vs GCS** design: the image is BMT-agnostic; the registry and per-BMT config live in GCS and are read at runtime. **Adding a new BMT does not require rebuilding the image.**

### Decoupled design: image vs GCS

Bucket layout mirrors **`gcp/remote`** (see `gcp/README.md`). Current deployment may use a `runtime/` prefix in the bucket (gcp/remote synced there); target layout is bucket root = gcp/remote (no prefix). Paths below are relative to that root.

| Concern | Lives in | When it changes |
| :--- | :--- | :--- |
| **Orchestrator, contracts, entrypoint** | Image (baked at build) | Image rebuild / deploy |
| **Project registry** (`bmt_projects.json`) | GCS at well-known path under the root (e.g. `config/bmt_projects.json`) | Update object in GCS; no image change |
| **Per-BMT jobs config** | GCS under the root (e.g. `projects/<name>/bmt_jobs.json` as in repo) or baked in image | Upload/update in GCS or image |
| **Project manager code** | **Image** (baked at build; per `gcp/README`: do not upload gcp/image to bucket). Optionally GCS in hybrid layouts only. | Image rebuild or code-sync for GCS-backed hybrid |

The orchestrator **loads the registry from GCS at runtime** (e.g. at trigger processing or job start). New BMTs: add/update the registry (and, in hybrid layouts, project assets in GCS); the same image runs the new leg.

**Prerequisites:** Phase 1-3 contract and layout; orchestrator loads registry from GCS. Registry path: under the bucket/mount root, `RUNTIME_CONFIG_PREFIX`/`BMT_PROJECTS_FILENAME` (e.g. `config/bmt_projects.json`). Optional `BMT_REGISTRY_URI` override is supported (Phase 1.1 in [gcp-image-refactor.md](gcp-image-refactor.md)).

### Steps

1. **Create the project manager code (OOP only; config-driven)**
   - Implement the **Protocol** by subclassing `BaseBmtManager` and overriding the contract methods with the **exact method signatures** from `BmtManagerProtocol`. Use **`@override`** on each overridden method. Config is injected by the framework via the constructor (e.g. `ManagerConfig`); the manager does not parse CLI or env.
   - Implement `bmt_manager.py` (and any project-specific assets) so it can be loaded from GCS or the image's `projects/` tree. Use the contract (Protocol, base class, models, constants) as in the examples below.

2. **Make the code available to the runtime**
   - **Preferred (target layout):** Project manager code is **baked in the image** (`gcp/image/projects/<name>/`); do not upload gcp/image to the bucket. Add the project to the repo and rebuild the image.
   - **Hybrid/current layout:** Optionally upload the project package to GCS if the deployment uses a code prefix; the registry then points `manager_script` at that path.

3. **Register the project in GCS (no image change)**
   - Update the **registry object in GCS** at the well-known path under the bucket root. Add one entry for the new project with `manager_script` and `jobs_config`. Use `gsutil cp`, a deploy tool, or a small script that reads-modify-writes the JSON.

4. **Validate and test**
   - Run contract/layout tests locally. Trigger a run that includes the new leg; the orchestrator will load the registry from GCS and invoke the new manager. Confirm `manager_summary` and `ci_verdict` are produced and conform to schemas.

No image rebuild is required when adding a new BMT: update the registry and project assets in GCS; the same image loads the registry at runtime and runs the new manager.

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

## Reference Code Examples

The following examples are reference material for implementers. The main narrative above is sufficient for understanding the contract and workflow.

### 1. Well-known registry path and loading it at runtime (orchestrator)

Registry lives in GCS; the image never bakes it. Orchestrator loads it once per run (or per trigger).

```python
# In orchestrator or trigger pipeline (e.g. gcp/image/orchestrator.py or trigger_pipeline.py)
# Bucket layout: root mirrors gcp/remote (see gcp/README.md, tools/shared/bucket_env.py).
# BucketPaths.runtime_root = gs://<bucket> (target) or gs://<bucket>/runtime (current prefix layout).
# RUNTIME_CONFIG_PREFIX = "config" (target) or "runtime/config" (current).
from gcp.image.config.constants import RUNTIME_CONFIG_PREFIX, BMT_PROJECTS_FILENAME
from gcp.image.models import BucketPaths

def registry_uri(paths: BucketPaths) -> str:
    """Well-known GCS path for the project registry (under runtime root; no registry in image)."""
    return f"{paths.runtime_root.rstrip('/')}/{RUNTIME_CONFIG_PREFIX}/{BMT_PROJECTS_FILENAME}"

def load_registry(gcs_client, paths: BucketPaths) -> BmtRegistry:
    """Load registry from GCS at runtime; validate and return typed BmtRegistry (no raw dict)."""
    uri = registry_uri(paths)
    bucket_name, blob_name = _parse_gcs_uri(uri)
    blob = gcs_client.bucket(bucket_name).blob(blob_name)
    if not blob.exists():
        return BmtRegistry(projects={})
    payload = json.loads(blob.download_as_text(encoding="utf-8"))
    return BmtRegistry.model_validate(payload)  # or from_dataclass; type: BmtRegistry
```

### 2. Adding a new BMT: update the registry in GCS (no image rebuild)

```bash
# Download current registry, edit, upload back.
# Path under bucket root: config/bmt_projects.json (target) or runtime/config/bmt_projects.json (if bucket uses runtime/ prefix).
gsutil cp gs://MY_BUCKET/config/bmt_projects.json /tmp/bmt_projects.json
# Edit /tmp/bmt_projects.json to add the "sk" entry (or another project), then:
gsutil cp /tmp/bmt_projects.json gs://MY_BUCKET/config/bmt_projects.json
```

Example registry JSON **in GCS**:

```json
{
  "sk": {
    "manager_script": "projects/sk/bmt_manager.py",
    "jobs_config": "projects/sk/bmt_jobs.json"
  }
}
```

(Repo layout: `gcp/image/projects/sk/bmt_jobs.json`; no `config/` segment.)

Optional: a small script to add a project without hand-editing JSON. Use **typed** `BmtRegistry` / `BmtProjectEntry` in memory; serialize to JSON for GCS (no raw dicts).

```python
# tools/remote/registry_add_project.py (or similar)
"""Add or update a project in the GCS registry. Uses BmtRegistry value class; no raw dicts.
Bucket layout: root mirrors gcp/remote. Registry blob at RUNTIME_CONFIG_PREFIX/bmt_projects.json."""
from gcp.image.config.constants import RUNTIME_CONFIG_PREFIX, BMT_PROJECTS_FILENAME
from gcp.image.models import BmtRegistry, BmtProjectEntry

def add_project(bucket: str, project_name: str, manager_script: str, jobs_config: str) -> None:
    """e.g. add_project("my-bucket", "sk", "projects/sk/bmt_manager.py", "projects/sk/bmt_jobs.json")"""
    from google.cloud import storage
    client = storage.Client()
    path = f"{RUNTIME_CONFIG_PREFIX}/{BMT_PROJECTS_FILENAME}"
    blob = client.bucket(bucket).blob(path)
    registry = BmtRegistry.model_validate_json(blob.download_as_text()) if blob.exists() else BmtRegistry(projects={})
    entry = BmtProjectEntry(manager_script=manager_script, jobs_config=jobs_config)
    registry = registry.with_project(project_name, entry)
    blob.upload_from_string(registry.model_dump_json(indent=2), content_type="application/json")
```

### 3. Resolving manager and config from registry (orchestrator)

The orchestrator loads the registry from GCS, builds a **typed config object**, and instantiates the manager by passing that config into the constructor. The contributor's class is never responsible for CLI or env parsing.

```python
# Orchestrator: build config from registry + trigger payload, then instantiate manager
def get_manager_for_leg(
    registry: BmtRegistry,
    leg: LegIdentity,
    bucket_paths: BucketPaths,
    run_id: str,
    workspace_root: Path,
    jobs_config: BmtJobsConfig,
) -> BmtManagerProtocol:
    project = leg.project
    if project not in registry.projects:
        raise ValueError(f"Unknown project: {project}")
    entry = registry.projects[project]  # typed BmtProjectEntry
    # Resolve manager_script to a callable class (dynamic import or registry mapping to baked-in classes)
    manager_cls = load_manager_class(entry.manager_script)
    config = ManagerConfig(
        leg_identity=leg,
        bucket_paths=bucket_paths,
        run_id=run_id,
        workspace_root=workspace_root,
        jobs_config=jobs_config,
    )
    return manager_cls(config)  # config injected; no argparse in contributor code
```

### 4. Contract: method signatures (Protocol + Base implementation)

The **contract** is `BmtManagerProtocol`: any type that implements these method signatures satisfies the framework. The **default implementation** is `BaseBmtManager`, which implements the Protocol and provides default implementations for `collect_input_files` and `run()`.

```python
# gcp/image/contracts/bmt_manager.py (or equivalent). All types are value classes; no raw dicts.
from typing import Protocol, runtime_checkable
from pathlib import Path
from gcp.image.models import FileRunResult, RunnerIdentity, GateResult  # value classes, not dict

@runtime_checkable
class BmtManagerProtocol(Protocol):
    """Structural contract for a BMT manager. Implement every method with these signatures. No dict[str, Any].
    BaseBmtManager implements this Protocol and provides defaults for collect_input_files and run()."""

    def setup_assets(self) -> None: ...
    def collect_input_files(self, inputs_root: Path) -> list[Path]: ...
    def run_file(self, input_file: Path, inputs_root: Path) -> FileRunResult: ...
    def compute_score(self, file_results: list[FileRunResult]) -> float: ...
    def get_runner_identity(self) -> RunnerIdentity: ...
    def evaluate_gate(
        self,
        aggregate_score: float,
        last_score: float | None,
        failed_count: int,
        file_results: list[FileRunResult],
    ) -> GateResult: ...
    def run(self) -> int: ...
```

The base class **`BaseBmtManager`** implements `BmtManagerProtocol`, takes a single **config object** (e.g. `ManagerConfig`) in `__init__`, and exposes it to subclasses. It provides default implementations for `collect_input_files` and `run()`; subclasses override the other protocol methods. All method parameters and return types use value classes, not `dict[str, Any]`.

### 5. Example: SK manager (target design — minimal boilerplate)

The **current** `gcp/image/projects/sk/bmt_manager.py` is a useful reference but uses argparse and manual config plucking. The **target design** uses **declarative config**: the framework validates jobs config and builds a typed `ManagerConfig`; the base class hydrates runner/dataset/paths from that config so the derived class has minimal boilerplate.

```python
"""SK project BMT manager. Declarative config; minimal boilerplate; strict typing (no raw dicts)."""

from __future__ import annotations

from pathlib import Path
from typing import override

from gcp.image.contracts import BaseBmtManager
from gcp.image.models import FileRunResult, RunnerIdentity, GateResult  # value classes


class SKBmtManager(BaseBmtManager):
    """SK BMT: one example of runner + template + dataset; SK-specific parsing (e.g. NAMUH counter).
    Other BMTs may have entirely different runner output."""

    # Base class populates runner_uri, dataset_uri, results_prefix, _inputs_root, runner_path from config.
    # No custom __init__ needed.

    @override
    def setup_assets(self) -> None:
        """Runner bundle, template, dataset — base can offer defaults; override only if SK needs different behavior."""
        self._setup_runner_assets()
        self._setup_template_assets()
        self._setup_dataset_assets()
        self._finalize_assets()

    # collect_input_files: not overridden; base class recursively walks inputs_root, respects config extensions + limit

    @override
    def run_file(self, input_file: Path, inputs_root: Path) -> FileRunResult:
        """Run runner; parse this BMT's runner output into FileRunResult.
        SK uses NAMUH-style log parsing; other BMTs use their own format."""
        return FileRunResult(
            file=str(input_file.relative_to(inputs_root)),
            exit_code=0,
            status="ok",
            error="",
            namuh_count=42,  # SK-specific field
        )

    @override
    def compute_score(self, file_results: list[FileRunResult]) -> float:
        if not file_results:
            return 0.0
        return sum(r.namuh_count for r in file_results) / len(file_results)

    @override
    def get_runner_identity(self) -> RunnerIdentity:
        return RunnerIdentity(
            name=Path(self.runner_uri).name,
            build_id=self.runner_build_id,
            source_ref="",
        )

    @override
    def evaluate_gate(
        self,
        aggregate_score: float,
        last_score: float | None,
        failed_count: int,
        file_results: list[FileRunResult],
    ) -> GateResult:
        from gcp.image.gate import gate_result  # returns GateResult value class
        gate = self.config.jobs_config.gate
        return gate_result(
            gate.comparison, aggregate_score, last_score, failed_count,
            self.config.run_context, gate.tolerance_abs
        )
```

### 6. Single entrypoint `main.py` (image root) — config-driven, no CLI

```python
#!/usr/bin/env python3
from gcp.image.config import load_config
from gcp.image.runner import run_watcher, run_orchestrator

def main() -> None:
    config = load_config()
    if config.mode == "watcher":
        run_watcher(config)
    elif config.mode == "orchestrator":
        run_orchestrator(config)

if __name__ == "__main__":
    main()
```

Invocation: set env (and optionally a payload path), then run the entrypoint once. No subcommands or flags.

```bash
BMT_MODE=watcher GCS_BUCKET=gs://my-bucket python main.py
BMT_MODE=orchestrator BMT_PAYLOAD_PATH=/config/payload.json python main.py
```

### 7. Jobs config path (canonical JSON)

Reference a JSON file that conforms to the artifact contract. Example shape (SK-style):

```json
{
  "runner": { "uri": "projects/sk/kardome_runner", "deps_prefix": "projects/sk/lib" },
  "paths": {
    "dataset_prefix": "projects/sk/inputs/false_rejects",
    "results_prefix": "projects/sk/results/false_rejects",
    "outputs_prefix": "projects/sk/outputs/false_rejects"
  },
  "input_file_extensions": ["*.wav"],
  "template_uri": "projects/shared/input_template.json",
  "gate": { "comparison": "gte", "tolerance_abs": 0.0 },
  "parsing": { "keyword": "NAMUH" }
}
```

(Base class uses `input_file_extensions` to recursively collect inputs from the dataset root; no custom collection code in the project.)

---

## Implementation Tasks (Phase 3, continued)

These tasks continue Phase 3 from [gcp-image-refactor.md](gcp-image-refactor.md) (which covers tasks 3.1-3.4). Tasks 3.5 and 3.6 are here because they define the contributor-facing API surface.

- [ ] **3.5 Contributor API Contract Module Structure (OOP only; declarative config; minimal boilerplate)**
  - **Files:** `gcp/image/contracts/`, `gcp/image/projects/shared/`
  - **Task:** Define **`BmtManagerProtocol`** (structural contract) with **exact method signatures**: `setup_assets()`, `collect_input_files(inputs_root)`, `run_file(input_file, inputs_root)`, `compute_score(file_results)`, `get_runner_identity()`, `evaluate_gate(...)`, and `run()`. The framework types against this Protocol (e.g. orchestrator returns `BmtManagerProtocol`). Define how the orchestrator resolves `manager_script` to a callable class: e.g. dynamic import of a module under the code root, or registry mapping to baked-in classes.
  - **Task:** **Input file collection:** `BaseBmtManager` implements `collect_input_files(inputs_root)` by default (recursive walk, optional declarative config for extensions and limit). Contributors override only for custom discovery.
  - **Task:** Add **`BaseBmtManager`** ABC that **implements** `BmtManagerProtocol`, takes a single **validated config object** (e.g. `ManagerConfig` from declarative JSON schema + Pydantic/dataclass), **hydrates** common fields, and provides default implementations for `collect_input_files` and `run()`. Derived classes override the remaining protocol methods and use **`@override`** on each. Minimal boilerplate — no custom `__init__` or hard-coded key access unless the project truly needs one extra field. **Goal: ask as little as possible of the dev adding a new BMT.**
  - **Task:** Contributor API is config-driven and declarative; no CLI parsing in manager code.

- [ ] **3.6 Parsing boundary (per-BMT; no single assumed runner output)**
  - **Files:** `gcp/image/projects/shared/` (optional shared parsers), per-project manager or parser modules.
  - **Task:** Define a **parsing boundary** so that gate/coordinator logic only consumes **typed models** (e.g. `FileRunResult`), never raw runner stdout. Parsing is **per-BMT**: each project's manager is responsible for interpreting that BMT's runner CLI output. The framework **must not** assume one runner output format.
  - **Task:** Where several projects share a common output format, factor parsing into a **reusable util** (e.g. `parse_counter_log`) used only by those projects; do not impose it on all BMTs.
  - **Requirement:** Downstream gate and aggregation logic consumes normalized typed models only.

---

## Verification

| Check | Method |
| :--- | :--- |
| Contract | Stub/type compatibility, base-class hook coverage, and reference manager conformance |
| Artifact | Canonical JSON schema validation and JSONL parse-error budget enforcement |
| Contributor API | Reference SK manager passes type checks and produces `FileRunResult`/`GateResult` |
