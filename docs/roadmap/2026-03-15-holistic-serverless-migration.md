# Holistic Serverless Migration: Detailed Implementation Plan

**Status:** Proposed / Integrated Master Plan
**Date:** 2026-03-15
**Goal:** A high-fidelity, meticulously ordered migration to a serverless architecture. This plan integrates the **Refactor Alpha** (code quality/structure) with the **Cloud Run Jobs Migration** (infrastructure/scalability) to solve the "40GB startup wall" and support 20+ projects.

---

## Reading Guide

- **What is authoritative:** checklist tasks in each phase and the verification matrix.
- **What is advisory:** each `Research Insights` block (implementation guidance and pitfalls); they are not checklist items.
- **Artifact terminology:** use **JSON** for canonical control/state artifacts and **JSONL** for high-volume telemetry streams.
- **Invocation terminology:** **payload** = the single structured JSON (file at `BMT_PAYLOAD_PATH` or env) describing a run; **leg** = one BMT run in a trigger; **entrypoint config** or **config** = the typed object from `load_config()` (mode, bucket, payload, etc.). **Trigger file** = CI-written JSON (e.g. in GCS); the entrypoint **payload** may be that same content or a path to it.
- **Invocation:** Config-driven (env + optional payload); no CLI (argparse/Typer) in contributor or entrypoint.

### Quick Navigation

- **gcp/ code/data separation (prerequisite):** § Phase 0
- **Contract & contributor workflow:** § Contract & contributor workflow (core contract, image layout, how to add a BMT, reference code examples), Phase 1, Phase 2, Phase 3
- **Cloud Run/GCS Fuse infra:** Phase 4, Phase 5
- **Coordinator/failure semantics:** Phase 6, Phase 7
- **Cutover/rollback:** Phase 8, Verification Matrix

### Plan structure (higher-level grouping)

Phases are grouped into three **parts** to separate code/contract work from infrastructure and from cutover:

| Part | Phases | Focus |
| :--- | :--- | :--- |
| **0 — gcp/ Layout & Data Separation (Prerequisite)** | 0 | Manifest-based dataset visibility; protect sync tooling from data paths; fix pre-existing layout_patterns bug |
| **I — Refactor Alpha (Code & Contract)** | 1–3 | Boundary foundations, config-driven entrypoint, structural decoupling; testable contract-driven code |
| **II — Container & Cloud Run** | 4–6 | Containerization, Pulumi Job + GCS Fuse, scale and coordinator model |
| **III — CI & Cutover** | 7–8 | Direct API handoff, shadow run, cutover, VM decommission |

---

## Enhancement Summary

**Deepened on:** 2026-03-15  
**Tech review:** 2026-03-15 (code-reviewer); feedback applied to close critical/recommended gaps.  
**Sections enhanced:** Phases 1–8, Verification Matrix, Contract & contributor workflow, Artifact Contract, Reading Guide.

### Key Improvements

1. Added explicit ownership requirements for aggregation, pointer update (`current.json`), status/check posting, and cleanup in the Cloud Run model.
2. Tightened Cloud Run + GCS Fuse implementation details (mount options, task model, memory/cache tradeoffs, WIF/IAM scoping, CI execution semantics).
3. Added measurable migration/cutover guardrails (shadow parity, rollback drill, observability thresholds, and go/no-go checks).
4. **Post–tech review:** Coordinator obtains registry and per-leg `results_prefix`; who runs coordinator when using `--wait` defined; partial-failure rules and idempotency specified; mutual exclusion of direct-API vs Eventarc and rollback `BMT_EXECUTOR` wiring documented; `BMT_REGISTRY_URI` override and typed `entry.manager_script` in examples; artifact vs contributor contract clarified; 20+ legs / 40GB verification in matrix.

### New Considerations Discovered

- Do not run direct API trigger and Eventarc fallback in a way that can produce duplicate executions.
- Define post-execution coordinator behavior before cutover to preserve existing pointer/snapshot semantics.
- Prefer least-privilege WIF + SA bindings and digest-pinned container execution for safer CI handoff.
- Use **JSON** for canonical control/state artifacts and **JSONL** for high-volume telemetry streams.

---

## Contract & contributor workflow

This section defines the canonical API and contributor workflow: the image contract, layout, how to add a BMT, and reference code. Phases 1–3 implement it; Part II (container/Cloud Run) depends on it.

### Core image contract (redesign opportunity)

**Why now:** This migration is a strong opportunity to redesign `gcp/image` as the canonical API/interface that contributors use when implementing new BMTs.

### Decision: API Surface for Contributor BMTs

| Option | Pros | Cons | Recommendation |
| :--- | :--- | :--- | :--- |
| **Documentation-only contract** | Fast to start; low tooling overhead | Drifts easily; weak enforcement | Use only as supplemental narrative docs |
| **Type-stub contract (`.pyi` + Protocols/TypedDicts)** | Strong static guidance; editor-native contributor UX; low runtime coupling | Needs CI type-checking discipline | **Primary contract surface** |
| **Base class contract (runtime ABC)** | Runtime guardrails; clear required hooks; easier onboarding | Can become rigid/over-coupled if overloaded | **Secondary runtime contract** for required lifecycle hooks |
| **Wheel-distributed API package** | Versioned contract; strict dependency boundary | Release/versioning overhead; slows iteration early | Defer until API stabilizes across 2-3 migration iterations |

### Chosen Direction (This Plan)

- Use a **hybrid contract** enforced by OOP only (no CLI/argparse in the contributor API):
  1. **BmtManagerProtocol** (structural contract) defines the **method signatures** (parameters and return types) that any BMT manager must satisfy. The **contract surface** for the framework is the Protocol: orchestrator and callers type against `BmtManagerProtocol`, so alternative implementations (wrappers, adapters, or future mixin-based code) remain valid without changing the type contract.
  2. **BaseBmtManager** is an ABC that **implements** `BmtManagerProtocol` and provides shared orchestration and defaults: `collect_input_files` (recursive walk with optional config for extensions/limit) and `run()` (orchestration loop). Contributors **typically subclass BaseBmtManager** and override the protocol methods they need; they may override `collect_input_files` only when they need custom discovery. Use **`@override`** (from `typing`) on every overridden method so intent is explicit and refactors are safe.
  3. **Config is injected by the framework:** the orchestrator (or entrypoint) owns building typed config from **environment and/or a single structured payload**; it does not use a CLI (no argparse, no Typer). The entrypoint is **config-driven**: `main.py` loads config from env and optionally a payload file/path, then calls the appropriate operation. Contributors **never** parse CLI args; they receive config via the base constructor.
  4. **The framework defines intuitive value classes** for all config and identity concepts (e.g. `LegIdentity`, `BucketPaths`, `ManagerConfig`, `BmtJobsConfig`, `WorkspacePaths`). Contributors work with clear, typed attributes instead of raw dicts or magic keys.
  5. Contributor docs and reference implementations show only the class and its methods; no `main()` or `parse_args()` in the contributor surface.
- **Comments and docstrings explain why, never what:** Do not use comments or docstrings to describe *what* the code does; the code should be clear from naming and structure. Reserve comments and docstrings for *why* (rationale, non-obvious constraints, business rules).
- **Strict typing; no raw untyped dicts:** The entire framework relies on **strict schemas and strong Pythonic typing**. Never use raw untyped `dict` (or `dict[str, Any]`) in the API or internal boundaries. Use **value classes**, **config classes**, and typed containers (e.g. `list[FileRunResult]`, not `list[dict[str, Any]]`). Use primitives only when absolutely necessary (e.g. a single string or int field). JSON at the boundary is deserialized into typed models; in-memory data stays in value classes or Pydantic/dataclass instances.
- Contributor API is **purely OOP**:
  - **Implement the Protocol** by subclassing `BaseBmtManager` (recommended) or by providing any type that satisfies `BmtManagerProtocol`.
  - Override only the contract methods that are project-specific; use **`@override`** on each overridden method.
  - Receive configuration via constructor parameters (typed value classes with intuitive attribute names), not via argparse or env parsing
- Use **boundary validation**:
  - JSON schema for canonical JSON artifacts (`current.json`, `ci_verdict.json`, `manager_summary.json`)
  - Runtime parser validation for runner stdout and JSONL telemetry before conversion to internal typed models
- **Runner output is per-BMT; no single assumed format:** The framework **must not** assume that all runners produce the same CLI output (e.g. kardome_runner or NAMUH-style). Each BMT may have **its own unique** runner and CLI output format; parsing is **project-specific** and implemented in the manager (e.g. in `run_file`, or via a project-specific parser the manager calls). Where multiple projects share a common output format, that parsing logic can be factored into a **reusable util** used by those projects only. The contract only requires that the manager return typed `FileRunResult` (and similar); how that result is derived from runner stdout is entirely up to the project.
- **Declarative config, minimal boilerplate:** Avoid brittle, error-prone designs that rely on hard-coded strings and manual key plucking. Use **declarative config** backed by JSON schemas and typed models (Pydantic, dataclasses, or a hybrid):
  - Jobs config and registry are defined by **JSON schemas**; the framework loads and validates them into **Pydantic or dataclass models** (or equivalent) so that config is typed and validated at the boundary.
  - The **base class or framework** hydrates `ManagerConfig` (and project-specific shapes) from the declarative source and **automates input file collection**: the base class implements discovery of input files by recursively walking the inputs root (including all subdirectories), with optional declarative config for file extensions (e.g. `*.wav`) and limit. Contributors **do not** implement `collect_input_files` unless they need custom discovery. Derived project BMT manager classes have **minimal boilerplate**: they receive a validated config and implement only the contract methods that are truly project-specific (e.g. `setup_assets`, `run_file`, `compute_score`, `get_runner_identity`, `evaluate_gate`). No custom `__init__` parsing, no hard-coded keys, no repeated wiring—the declarative config and contracts drive the behavior. **Goal: ask as little as possible of the dev adding a new BMT.**
- Defer standalone wheel packaging until contract churn drops and versioning policy is ready.

### Image layout (single entrypoint + submodules)

The container image must have **one single entrypoint**, `main.py`, at the image root. All other code lives in **submodules** under a single top-level package; no other executable scripts at the image root.

- **Entrypoint:** `main.py` at image root (e.g. `/app/main.py`). It is the only script invoked by the container runtime. **No CLI (argparse/Typer):** invocation is config-driven. Import intuitively named operations (e.g. `load_config`, `run_watcher`, `run_orchestrator`) from submodules; `main()` loads config from env and optional payload, then calls the right operation. The flow is obvious from the sequence of calls. Comments and docstrings explain **why**, never **what**.
- **Submodules:** All other code is organized under one package (e.g. `gcp/image/` or a dedicated `bmt/` package) with clear subpackages: `config/`, `contracts/`, `coordinator`, `gate`, `projects/`, etc. No free-floating modules at the image root besides `main.py`.
- **Rationale:** Single entrypoint simplifies `CMD`/`ENTRYPOINT` and onboarding; naming and call order make the flow obvious without redundant prose.

### How to add a new project or BMT manager

This subsection describes the **contributor workflow** and the **decoupled image vs GCS** design: the image is BMT-agnostic; the registry and per-BMT config live in GCS and are read at runtime. **Adding a new BMT does not require rebuilding the image.**

The **SK project** (`gcp/image/projects/sk/bmt_manager.py`) is used as one example: it uses a runner with NAMUH-style counter output and project-specific parsing. **Other BMTs may have completely different runner CLI output**; the framework does not assume a single format. Each project’s manager is responsible for parsing its runner’s output into the typed `FileRunResult` (and related) contract; shared output formats can be implemented as reusable utils. See **Reference: code examples** below for the target design (config injection, Protocol/base class, config-driven entrypoint; no CLI in the manager).

### Decoupled design: image vs GCS

Bucket layout mirrors **`gcp/remote`** (see `gcp/README.md`). Current deployment may use a `runtime/` prefix in the bucket (gcp/remote synced there); target layout is bucket root = gcp/remote (no prefix). Paths below are relative to that root (the mounted root or bucket root).

| Concern | Lives in | When it changes |
| :--- | :--- | :--- |
| **Orchestrator, contracts, entrypoint** | Image (baked at build) | Image rebuild / deploy |
| **Project registry** (`bmt_projects.json`) | GCS at well-known path under the root (e.g. `config/bmt_projects.json`) | Update object in GCS; no image change |
| **Per-BMT jobs config** | GCS under the root (e.g. `projects/<name>/bmt_jobs.json` as in repo) or baked in image | Upload/update in GCS or image |
| **Project manager code** | **Image** (baked at build; per `gcp/README`: do not upload gcp/image to bucket). Optionally GCS in hybrid layouts only. | Image rebuild or code-sync for GCS-backed hybrid |

The orchestrator **loads the registry from GCS at runtime** (e.g. at trigger processing or job start). New BMTs: add/update the registry (and, in hybrid layouts, project assets in GCS); the same image runs the new leg.

**Prerequisites:** Phase 1–3 contract and layout; orchestrator loads registry from GCS. Registry path: under the bucket/mount root, `RUNTIME_CONFIG_PREFIX`/`BMT_PROJECTS_FILENAME` (e.g. `config/bmt_projects.json` when root = gcp/remote; or `runtime/config/bmt_projects.json` when bucket uses a `runtime/` prefix). Optional `BMT_REGISTRY_URI` override is supported (Phase 1.1).

**Steps:**

1. **Create the project manager code (OOP only; config-driven)**
   - Implement the **Protocol** by subclassing `BaseBmtManager` and overriding the contract methods with the **exact method signatures** from `BmtManagerProtocol`. Use **`@override`** on each overridden method. Config is injected by the framework via the constructor (e.g. `ManagerConfig`); the manager does not parse CLI or env (see Contract above).
   - Implement `bmt_manager.py` (and any project-specific assets) so it can be loaded from GCS or the image's `projects/` tree. Use the contract (Protocol, base class, models, constants) as in the examples below.

2. **Make the code available to the runtime**
   - **Preferred (target layout):** Project manager code is **baked in the image** (`gcp/image/projects/<name>/`); do not upload gcp/image to the bucket (see `gcp/README.md`). Add the project to the repo and rebuild the image (or use an image that already bundles it).
   - **Hybrid/current layout:** Optionally upload the project package to GCS if the deployment uses a code prefix; the registry then points `manager_script` at that path. Otherwise the image bundles a base set of projects and the registry references them.

3. **Register the project in GCS (no image change)**
   - Update the **registry object in GCS** at the well-known path under the bucket root (e.g. `config/bmt_projects.json` when root = gcp/remote; or `runtime/config/bmt_projects.json` if the bucket uses a `runtime/` prefix). Add one entry for the new project with `manager_script` and `jobs_config` (and any other keys the contract expects). Use `gsutil cp`, a deploy tool, or a small script that reads–modify–writes the JSON.

4. **Validate and test**
   - Run contract/layout tests locally. Trigger a run that includes the new leg; the orchestrator will load the registry from GCS and invoke the new manager. Confirm `manager_summary` and `ci_verdict` are produced and conform to schemas.

---

### Reference: code examples

The following examples are reference material for implementers; the main narrative above is sufficient for understanding the contract and workflow.

**1. Well-known registry path and loading it at runtime (orchestrator)**

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

**2. Adding a new BMT: update the registry in GCS (no image rebuild)**

Example: append or merge a new project into the registry object in GCS.

```bash
# Download current registry, edit, upload back (or use a script that does this).
# Path under bucket root: config/bmt_projects.json (target) or runtime/config/bmt_projects.json (if bucket uses runtime/ prefix).
gsutil cp gs://MY_BUCKET/config/bmt_projects.json /tmp/bmt_projects.json
# Edit /tmp/bmt_projects.json to add the "sk" entry (or another project), then:
gsutil cp /tmp/bmt_projects.json gs://MY_BUCKET/config/bmt_projects.json
```

Example registry JSON **in GCS** (same shape as before; the key point is it lives in GCS):

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
Bucket layout: root mirrors gcp/remote. Registry blob at RUNTIME_CONFIG_PREFIX/bmt_projects.json
(e.g. config/bmt_projects.json when bucket root = gcp/remote)."""
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
    registry = registry.with_project(project_name, entry)  # or new BmtRegistry(projects={**registry.projects, project_name: entry})
    blob.upload_from_string(registry.model_dump_json(indent=2), content_type="application/json")
```

**3. Resolving manager and config from registry (orchestrator)**

The orchestrator loads the registry from GCS, builds a **typed config object** (no argparse in the manager), and instantiates the manager by passing that config into the constructor. The contributor’s class is never responsible for CLI or env parsing.

```python
# Orchestrator: build config from registry + trigger payload, then instantiate manager (no argparse; typed only)
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
    # Resolve manager_script to a callable class (dynamic import under code root, or registry mapping to baked-in classes)
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

**4. Contract: method signatures (Protocol + Base implementation)**

The **contract** is `BmtManagerProtocol`: any type that implements these method signatures satisfies the framework. The **default implementation** is `BaseBmtManager`, which implements the Protocol and provides default implementations for `collect_input_files` (recursive walk of `inputs_root`, configurable via jobs config extensions/limit) and `run()` (orchestration loop). Contributors implement these methods with the exact signatures below. Config is provided via the constructor, not parsed by the manager. Use **`@override`** on every overridden method in subclasses.

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

The base class **`BaseBmtManager`** implements `BmtManagerProtocol`, takes a single **config object** (e.g. `ManagerConfig`) in `__init__`, and exposes it to subclasses; it does not take `argparse.Namespace` or raw dicts. It provides default implementations for `collect_input_files` and `run()`; subclasses override the other protocol methods (and optionally `collect_input_files` for custom discovery). All method parameters and return types use value classes (e.g. `FileRunResult`, `RunnerIdentity`, `GateResult`), not `dict[str, Any]`.

**5. Example: SK manager in `gcp/image/projects/sk/bmt_manager.py` (target design — minimal boilerplate)**

The **current** `gcp/image/projects/sk/bmt_manager.py` is a useful reference but uses argparse and manual config plucking. The **target design** uses **declarative config** (JSON schema + Pydantic/dataclass): the framework validates jobs config and builds a typed `ManagerConfig`; the **base class** hydrates runner/dataset/paths from that config so the derived class has **minimal boilerplate**—no custom `__init__`, no hard-coded keys, only the contract method implementations.

```python
"""SK project BMT manager. Declarative config; minimal boilerplate; strict typing (no raw dicts)."""

from __future__ import annotations

from pathlib import Path
from typing import override

from gcp.image.contracts import BaseBmtManager
from gcp.image.models import FileRunResult, RunnerIdentity, GateResult  # value classes


class SKBmtManager(BaseBmtManager):
    """SK BMT: one example of runner + template + dataset; SK-specific parsing (e.g. NAMUH counter). Other BMTs may have entirely different runner output."""

    # Base class populates runner_uri, dataset_uri, results_prefix, _inputs_root, runner_path from config.jobs_config
    # (validated by JSON schema + Pydantic/dataclass). No custom __init__ needed.

    @override
    def setup_assets(self) -> None:
        """Runner bundle, template, dataset—base can offer defaults; override only if SK needs different behavior."""
        self._setup_runner_assets()
        self._setup_template_assets()
        self._setup_dataset_assets()
        self._finalize_assets()

    # collect_input_files: not overridden; base class recursively walks inputs_root (all subdirs), respects config extensions + limit

    @override
    def run_file(self, input_file: Path, inputs_root: Path) -> FileRunResult:
        """Run runner; parse this BMT's runner output into FileRunResult. SK uses NAMUH-style log parsing; other BMTs use their own format."""
        # Parsing is project-specific: SK parses NAMUH from log; another BMT might parse JSON lines or a different CLI. Reusable utils only where formats are shared.
        return FileRunResult(
            file=str(input_file.relative_to(inputs_root)),
            exit_code=0,
            status="ok",
            error="",
            namuh_count=42,  # SK-specific field; other BMTs have different typed attributes
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

Config is loaded from the declarative jobs JSON (validated against the schema and turned into Pydantic/dataclass models); the base class wires common path/runner fields from that config. **Runner output parsing is per-BMT**: SK parses NAMUH-style output; other projects use their own runner and output format. Shared parsing logic can live in a reusable util where multiple BMTs share a format. The current SK file remains the reference for runner/template/dataset and SK-specific parsing until refactored to this shape.

**5. Single entrypoint `main.py` (image root) — config-driven, no CLI**

The image root has one script. **No argparse or Typer:** invocation is config-driven. Config is read from **environment variables** and optionally a **single structured payload** (e.g. a JSON file path in `BMT_PAYLOAD_PATH` or a JSON string in an env var). `main()` imports intuitively named operations, loads config, then calls the appropriate runner; the code tells the story.

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

**6. Jobs config path (canonical JSON)**

Reference a JSON file that conforms to the artifact contract (no JSONL for control state). The registry points each project to a jobs config path (e.g. `projects/sk/config/bmt_jobs.json` or `projects/sk/bmt_jobs.json` depending on repo layout). Example shape (SK-style):

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

(Example is SK-style; paths follow the bucket layout that mirrors `gcp/remote` (e.g. `projects/sk/...`). In the repo, jobs config uses a `bmts` map keyed by bmt_id—see `gcp/image/projects/sk/bmt_jobs.json`. Runner output format is not assumed to be shared across BMTs.)

---

No image rebuild is required when adding a new BMT: update the registry and project assets in GCS; the same image loads the registry at runtime and runs the new manager.

---

## Artifact Contract (JSON + JSONL)

This section defines the **artifact** contract (schemas and rules for JSON/JSONL artifacts). The **contributor** contract (Protocol, base class, config injection) is in § Contract & contributor workflow and Phase 3.5.

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

## Phased implementation (Parts I–III)

The following parts implement the contract and workflow above. Each part states what "done" looks like and what the next part depends on.

---

## Phase 0: gcp/ Code/Data Separation

**Goal:** Establish a clean and sustainable split between BMT code/config (fully local, editable) and BMT data (WAV audio corpora, potentially 30 GB per project) so that contributors can work against a real directory tree without storing large binary files locally.

**Context:** `gcp/remote/` is the local mirror of the GCS bucket. It already holds runner binaries, config, and input placeholders (`inputs/**/.keep`) but `gcp/README.md` already forbids real WAV files under `gcp/remote/**/inputs` ("keep local corpora under `data/` and upload explicitly"). The problem is that local contributors have no visibility into _which_ WAV files exist in GCS without downloading everything or running `gcloud storage ls`. With 30 GB+ per project this is not practical.

**Pre-existing bugs discovered during this design (block Phase 1):**

1. `FORBIDDEN_RUNTIME_SEED` in `tools/shared/layout_patterns.py` uses the pattern `r"(^|/)sk/inputs(/|$)"` (hard-coded old project prefix) but the current layout is `projects/sk/inputs/`. The exclusion never fires. `local_digest()` already silently walks `inputs/` if any files land there.
2. `local_digest()` in `tools/shared/bucket_sync.py` performs a recursive filesystem walk + full file read of every file under `gcp/remote/`. If a FUSE mount is active (or real WAVs are present) at any `inputs/` path, it reads the entire corpus on every `just deploy` and on every pre-commit hook invocation that touches `gcp/`. This makes the dev workflow unusable unless `SKIP_SYNC_VERIFY=1` is permanently set.

Both must be fixed in Phase 0 before FUSE or manifest tooling is layered on top.

---

### Decision: Local data access approach

The design space covers five options. The pre-existing `.gitignore` rule (`gcp/remote/**/inputs/**/*.wav`) already excludes real WAVs from git; the question is how to restore visibility.

| Approach | Complexity | Filename visibility (offline) | Tooling compat. | WSL2 safety | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Manifest JSON** (tracked in git) | Low | Full (names + sizes in JSON) | Requires manifest-aware enumeration | Excellent | **Primary — recommended** |
| **gcsfuse `--only-dir` mount** | Medium | Full (real filesystem tree) | Transparent — any tool works | Mostly fine (see pitfalls) | **Secondary — opt-in** |
| **rclone mount** | Medium | Full | Transparent | Same as gcsfuse | Alternative to gcsfuse |
| **0-byte stub files** | Low | Names visible, content absent | Breaks naive `open()` silently | Excellent | Not recommended |
| **DVC** | High | Opaque (`.dvc` dir file) | Requires DVC everywhere | Excellent | Too heavy for this use case |

**Chosen direction:** Manifest JSON as the primary mechanism + optional gcsfuse mount as a transparent opt-in layer.

---

### Phase 0 checklist

- [ ] **0.1 Fix `FORBIDDEN_RUNTIME_SEED` pattern (pre-existing bug)**
  - **File:** `tools/shared/layout_patterns.py`
  - **Task:** Change the hard-coded `r"(^|/)sk/inputs(/|$)"` pattern in `DEFAULT_CODE_EXCLUDES`, `FORBIDDEN_RUNTIME_SEED`, and `CODE_CLEAN_PATTERNS` to the project-agnostic `r"(^|/)inputs(/|$)"`. Verify by running `just test` and `just validate-layout`.
  - **Why:** The current pattern is keyed to the `sk` project name and does not match the actual path layout `projects/sk/inputs/`, so no inputs exclusion fires today.

- [ ] **0.2 Protect `local_digest()` from data paths**
  - **File:** `tools/shared/bucket_sync.py`
  - **Task:** Add an explicit skip condition for any path under an `inputs/` subtree that is not a `.keep` file or a `dataset_manifest.json`. The fix to 0.1 should already make the `exclude_patterns` path work; verify with a unit test that passes a synthetic `inputs/` directory with a `.wav` file and asserts it is excluded from the digest.
  - **Why:** `local_digest()` opens and SHA256-hashes every file. If a FUSE mount is active or real WAVs are present, this function reads gigabytes of audio on every `git commit` that touches `gcp/`.

- [ ] **0.3 Add `DatasetManifest` model and generation tool**
  - **Files:** `tools/shared/dataset_manifest.py` (new), `tools/remote/gen_input_manifest.py` (new)
  - **Task:** Define a `DatasetEntry` (path relative to dataset root, size_bytes, sha256, updated) and `DatasetManifest` (schema_version, dataset, project, bucket, prefix, generated_at, entries) as frozen dataclasses (or Pydantic models matching the project style). Emit `dataset_manifest.json` at the dataset root (e.g. `gcp/remote/projects/sk/inputs/false_rejects/dataset_manifest.json`). The generation tool calls `gcloud storage ls --json gs://$GCS_BUCKET/<prefix>/` to enumerate, normalises paths, and writes the manifest. Manifest files are tracked in git (they are tiny; the existing `.gitignore` excludes only `*.wav` under inputs, not JSON).
  - **Manifest shape:**
    ```json
    {
      "schema_version": 1,
      "project": "sk",
      "dataset": "false_rejects",
      "bucket": "my-bmt-bucket",
      "prefix": "projects/sk/inputs/false_rejects",
      "generated_at": "2026-03-15T12:00:00Z",
      "files": [
        {"name": "ambient/cafe_001.wav", "size_bytes": 4812800, "sha256": "abc123…", "updated": "2026-02-01T10:00:00Z"}
      ]
    }
    ```

- [ ] **0.4 Add `InputFileRegistry` and manifest-aware enumeration to shared tooling**
  - **File:** `tools/shared/dataset_manifest.py`
  - **Task:** Add an `InputFileRegistry` class with a `list_wavs(require_materialized: bool = False) -> list[Path]` method. When local `*.wav` files exist under `dataset_root`, return them. Otherwise, read `dataset_manifest.json` and return virtual `Path` objects (correct names, may not exist on disk). When `require_materialized=True` and files are absent, raise with a clear message pointing to `just fetch-inputs`. **No tool should call `rglob("*.wav")` directly on a dataset root; they must go through `InputFileRegistry`.**
  - **Update `tools/bmt/bmt_run_local.py`:** Replace the `dataset_root.rglob("*.wav")` walk with `InputFileRegistry(dataset_root).list_wavs(require_materialized=True)`.

- [ ] **0.5 Hook manifest regeneration into the upload tool**
  - **File:** `tools/remote/bucket_upload_wavs.py` (or `bucket_upload_dataset.py`)
  - **Task:** After a successful upload, call the manifest generation tool for the affected dataset. Commit the updated `dataset_manifest.json` as part of the deploy workflow (or instruct the developer to do so via a `just` recipe).

- [ ] **0.6 Add `just` recipes for on-demand materialization**
  - **File:** `Justfile`
  - **Task:** Add the following recipes:
    - `just fetch-inputs <project> <dataset>` — `gcloud storage cp -r gs://$GCS_BUCKET/projects/<project>/inputs/<dataset>/ gcp/remote/projects/<project>/inputs/<dataset>/`
    - `just fetch-wav <path>` — fetch a single file: `gcloud storage cp gs://$GCS_BUCKET/<path> gcp/remote/<path>`
    - `just gen-manifest <project> <dataset>` — run the generation tool for one dataset
    - `just mount-inputs <project>` (optional, documented as dev QoL) — gcsfuse `--only-dir` mount; see gcsfuse section below
    - `just umount-inputs <project>` — unmount

- [ ] **0.7 Update `gcp/README.md` and `docs/development.md`**
  - **Task:** Document the manifest contract (what `dataset_manifest.json` contains, where it lives, when to regenerate it). Document the three tiers of local data access: (1) manifest-only (offline, zero deps — see WAV names without content); (2) on-demand fetch via `just fetch-inputs`; (3) FUSE mount via `just mount-inputs` for full fidelity. Document WSL2 FUSE pitfalls.

---

### Research Insights (Phase 0)

**Why manifest JSON is the right primary mechanism:**

- Zero runtime dependencies; works completely offline for structure visibility.
- Stored in git alongside the code mirror so any `git clone` gives the full directory tree shape without any files.
- Naturally composable with the existing `gcloud storage cp` materialisation pattern used by `bmt_manager.py`.
- Manifest generation is a one-liner on top of `gcloud storage ls --json`; no new infra required.
- Manifests are small: ~10 KB for 1 000 WAV files; negligible storage.

**gcsfuse opt-in (full fidelity for editors and shell tools):**

When a contributor wants to see real filenames in their editor's file tree or wants shell autocomplete on WAV paths, they can mount the inputs prefix directly over the correct directory:

```bash
# just mount-inputs sk
gcsfuse \
  --only-dir=projects/sk/inputs \
  --file-mode=444 \
  --dir-mode=555 \
  --implicit-dirs \
  --stat-cache-ttl=300s \
  --type-cache-ttl=300s \
  --kernel-list-cache-ttl-secs=60 \
  $GCS_BUCKET \
  gcp/remote/projects/sk/inputs
```

Unmount with `fusermount -u gcp/remote/projects/sk/inputs` (Linux/WSL2).

**WSL2 FUSE pitfalls (kernel 6.6, Microsoft standard):**

- WSL2 kernel 6.6 includes FUSE 3.x — gcsfuse works. However:
  - `chmod`/`chown` silently fail; gcsfuse pins all file ownership to the mounting user's UID. Any tool that calls `os.chmod()` on a mounted path gets `Operation not permitted`.
  - The FUSE mount is torn down when the WSL session exits. Manage with `just mount-inputs` / `just umount-inputs`; document that contributors need to re-mount on each session. Optionally use systemd (available with `systemd=true` in `.wslconfig`).
  - Heavy traversal (e.g. `rg`, `find`, basedpyright scanning) without `--stat-cache-ttl` floods the GCS List API. Use `--stat-cache-ttl=300s` to mitigate.
  - `--implicit-dirs` is required; GCS does not store directory marker objects.
  - **Add the inputs mount point to `.cursorignore`** (and IDE ignore lists) so the IDE does not index WAV files or traverse 30 GB of audio.
- FUSE should be **opt-in and undocumented as a requirement**. The manifest path must work without it.

**What would break if FUSE were active and 0.1/0.2 were not fixed first:**

- `local_digest()` reads the entire FUSE mount on every `just deploy` and every pre-commit hook invocation that touches `gcp/` — effectively reading 30 GB on every commit.
- `BucketVerifyRuntimeSeedSync` calls `local_digest()` — CI verify step reads FUSE.
- `bucket_upload_wavs.py` pre-flight stats all local WAVs — floods GCS metadata API.

This is why 0.1 and 0.2 are the mandatory first steps.

**Python `NewType` for path semantics (optional but recommended):**

The existing tooling passes `Path` for runner binaries, config files, and 30 GB WAV corpus roots with no semantic distinction. Adding `NewType` aliases signals intent and enables grep-based auditing:

```python
from typing import NewType
from pathlib import Path

CodePath = NewType("CodePath", Path)   # always fully local; safe to hash/read
DataPath = NewType("DataPath", Path)   # may be FUSE/manifest; never hash contents
GcsUri  = NewType("GcsUri", str)       # gs://bucket/...
```

Key enforcement rule: **`local_digest()` and `BucketVerifyRuntimeSeedSync` must never receive a `DataPath`**. Document this in the function signatures. In `bmt_run_local.py` `ResolvedConfig`, separate `runner_path: CodePath` from `dataset_root: DataPath`.

**References:**

- [gcsfuse `--only-dir` docs](https://cloud.google.com/storage/docs/cloud-storage-fuse/cli-options)
- [gcsfuse implicit-dirs](https://cloud.google.com/storage/docs/cloud-storage-fuse/implicit-directories)
- [rclone mount](https://rclone.org/commands/rclone_mount/)

---

## Part I — Refactor Alpha (Code & Contract)

Phases 1–3: boundary foundations, single entrypoint (config-driven, no CLI), and structural decoupling. Delivers type-safe contracts, testable extraction, and a clear contributor API.

**Done when:** Constants and value classes are in place; single entrypoint `main.py` loads config from env and optional payload and invokes watcher or orchestrator; trigger pipeline is extracted and must NOT import `vm_watcher`; gate/trigger/coordinator logic and contributor Protocol/base class and parsing boundary are defined. All Phase 1–3 checklist items are complete and unit tests pass.

**Part II depends on:** Contract & contributor workflow (above) and Part I checklist completion so the container image can use the same entrypoint and config model.

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
    - **Config for managers:** `ManagerConfig` (e.g. `leg_identity`, `bucket_paths`, `jobs_config`, `workspace_paths`, `run_context`, `limit`); `BmtJobsConfig` (or nested value classes) for runner, paths, template_uri, gate, **optional input file discovery** (e.g. `input_file_extensions: ["*.wav"]` or glob pattern) so the base class can recursively collect input files from the inputs root (including subdirs) without contributor code, and **optional project-specific parsing config** (e.g. keyword, regex) so that each BMT can define how to parse its runner’s CLI output—no assumption of a single format across all BMTs.
    - **Results and runner I/O:** `FileRunResult` (per-file result: `file`, `exit_code`, `status`, `error`, plus **project-specific fields** as typed attributes—e.g. SK’s `namuh_count`, another BMT’s custom metrics). The manager produces `FileRunResult` from **its** runner’s output; the framework does not assume one output shape. `RunnerIdentity`, `GateResult` as above. Use these in Protocol method signatures instead of `dict[str, Any]`.
    - **Results (boundaries):** `GatePhaseResult` (`status`, `summary`, `metrics`) and any other result shapes used at boundaries.
  - **Task:** Prefer immutable value classes (`frozen=True`) where appropriate; use descriptive attribute names. Primitives only when necessary. These types are the **target of declarative config** (1.8)—no raw dicts or hard-coded key strings in manager code.
- [ ] **1.5 Typed boundary payloads (value classes / TypedDict; no raw dicts)**
  - **File:** `gcp/image/models.py`
  - **Task:** All boundary payloads are **typed**: use dataclasses or TypedDict (or Pydantic models), never `dict[str, Any]`. Define `TriggerPayload` (legs, repository, sha, workflow_run_id, run_context), `LegSummary` (index, project, bmt_id, decision, reason), `ManagerSummary`, `CiVerdict`, and any registry/ack/status shapes as value classes or TypedDict with full field typing.
  - **Task:** Internal code and contributor contract use these types only; no raw dicts at boundaries.
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
  - **Task:** Base class (or a factory) builds `ManagerConfig` and any project-specific config from the **validated** declarative config. Derived manager classes **do not** parse config or pluck keys—they receive a fully hydrated, typed config and implement only the contract methods. Goal: **minimal boilerplate** in each project’s `bmt_manager.py` (no custom `__init__` beyond `super().__init__(config)` unless the project truly needs one extra field).

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

**Goal:** One entrypoint at image root; invocation is **config-driven** (env vars and optionally a single payload file or JSON in env). No CLI (argparse/Typer). Aligns with Contract & contributor workflow and container/serverless patterns (Cloud Run Jobs, 12-factor).

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
- [ ] **3.5 Contributor API Contract Module Structure (OOP only; declarative config; minimal boilerplate)**
  - **Files:** `gcp/image/contracts/`, `gcp/image/projects/shared/`
  - **Task:** Define **`BmtManagerProtocol`** (structural contract) with **exact method signatures**: `setup_assets()`, `collect_input_files(inputs_root)`, `run_file(input_file, inputs_root)`, `compute_score(file_results)`, `get_runner_identity()`, `evaluate_gate(...)`, and `run()`. The framework types against this Protocol (e.g. orchestrator returns `BmtManagerProtocol`). Define how the orchestrator resolves `manager_script` (e.g. GCS path or relative path) to a callable class: e.g. dynamic import of a module under the code root, or registry mapping to baked-in classes.
  - **Task:** **Input file collection:** `BaseBmtManager` implements `collect_input_files(inputs_root)` by default (recursive walk, optional declarative config for extensions and limit). Contributors override only for custom discovery.
  - **Task:** Add **`BaseBmtManager`** ABC that **implements** `BmtManagerProtocol`, takes a single **validated config object** (e.g. `ManagerConfig` from declarative JSON schema + Pydantic/dataclass), **hydrates** common fields (e.g. `runner_uri`, `dataset_uri`, `results_prefix`, `runner_path`, `_inputs_root`), and provides default implementations for `collect_input_files` and `run()`. Derived classes override the remaining protocol methods and use **`@override`** on each overridden method. Minimal boilerplate—no custom `__init__` or hard-coded key access unless the project truly needs one extra field. **Goal: ask as little as possible of the dev adding a new BMT.**
  - **Task:** Contributor API is config-driven and declarative (see Contract & contributor workflow); no CLI parsing in manager code. Contributor docs and reference implementations show only the contract methods and `@override` usage; no `main()` or `parse_args()` in the manager surface.
- [ ] **3.6 Parsing boundary (per-BMT; no single assumed runner output)**
  - **Files:** `gcp/image/projects/shared/` (optional shared parsers), per-project manager or parser modules.
  - **Task:** Define a **parsing boundary** so that gate/coordinator logic only consumes **typed models** (e.g. `FileRunResult`), never raw runner stdout. Parsing is **per-BMT**: each project’s manager (or a project-specific parser it calls) is responsible for interpreting that BMT’s runner CLI output. The framework **must not** assume one runner output format (e.g. kardome_runner or NAMUH); different BMTs may have completely different output.
  - **Task:** Where several projects share a common output format, factor parsing into a **reusable util** (e.g. `parse_counter_log`) used only by those projects; do not impose it on all BMTs.
  - **Requirement:** Downstream gate and aggregation logic consumes normalized typed models only; how each manager produces those models from runner output is project-defined.

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

**Done when:** Docker image builds and runs with config-driven invocation; Cloud Run Job is provisioned with GCS Fuse; task parallelism and coordinator ownership (aggregation, pointer update, status/check, cleanup) are defined and validated (e.g. tested with a multi-leg run and documented).

**Part III depends on:** Part II completion so CI can call `gcloud run jobs execute` and rely on the coordinator for status and cleanup.

---

## Phase 4: High-Performance Containerization

**Goal:** Create a "Zero-Download" execution environment.

- [ ] **4.1 Create `gcp/image/Dockerfile`**
  - **Base:** `python:3.12-slim-bookworm`.
  - **Deps:** `libsndfile1`, `ffmpeg`, `curl`, `gnupg`, `uv`.
  - **Image layout:** One entrypoint at image root: `main.py` (e.g. `/app/main.py`). Copy the rest of the code into submodules under `/app` (e.g. `/app/config/`, `/app/contracts/`, `/app/projects/`, or `/app/gcp/image/` as a package). Set `PYTHONPATH` so `main.py` can import the package. `CMD`/`ENTRYPOINT` invoke only `python main.py` (config via env and optional payload).
  - **Code:** Copy `gcp/image` (required) and optionally `tools` (e.g. for local dev); image root has exactly `main.py` and one top-level package; no other scripts at root. For minimal job image, `gcp/image` alone may suffice.
- [ ] **4.2 Project code: image vs GCS (decoupled)**
  - **Task:** Do **not** bake the project registry (`bmt_projects.json`) into the image. The registry lives in GCS and is loaded at runtime so new BMTs can be added without image rebuild.
  - **Task:** Bake project manager code in the image (per `gcp/README.md`: gcp/image is not uploaded to the bucket; publish = image build). Optionally bake a default set of project plugins (e.g. `gcp/image/projects/` tree); the orchestrator resolves which projects exist from the GCS registry. New projects are added by adding code to the repo and rebuilding the image, and updating the registry in GCS to point at the new project.
  - **Impact:** Same image can run any BMT listed in the GCS registry; adding a BMT = image rebuild (to include new project code) + update registry in GCS. Hybrid layouts that upload code to GCS are possible but not the target.
- [ ] **4.3 Local validation**
  - **Task:** Build `bmt-orchestrator:latest`.
  - **Task:** Run config-driven invocation to verify local FUSE simulation, e.g. `docker run -v $(pwd)/gcp/remote:/mnt/runtime -e GCS_BUCKET=... -e BMT_MODE=orchestrator -e BMT_PAYLOAD_PATH=/config/payload.json bmt-orchestrator` (or `python main.py` with the same env). No `--leg-json` or subcommands; entrypoint reads config from env and optional payload path.

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
  - **Volume:** **Mandatory GCS Fuse Mount.** If the bucket uses a `runtime/` prefix (current layout: gcp/remote synced to `runtime/`), map `gs://{BUCKET}/runtime` to `/mnt/runtime`. If the bucket root is the gcp/remote mirror (target layout; see `tools/shared/bucket_env.py`), map `gs://{BUCKET}` to `/mnt/runtime`. The mounted root must be the 1:1 gcp/remote layout (config/, triggers/, projects/, etc.).
  - **FUSE Tuning:** Set `file-cache`, `stat-cache-capacity`, and `type: "gcs"` for optimal read-heavy WAV streaming.
- [ ] **5.2 IAM & Secret Access**
  - **Task:** Create `bmt-job-runner` Service Account.
  - **Task:** Grant least-privilege, resource-scoped access. **Bucket layout:** The bucket (or the mounted prefix) is a **1:1 mirror of `gcp/remote`** (see `gcp/README.md`, `tools/shared/bucket_env.py`). Paths below are relative to that root; do not assume separate top-level `code/` or `runtime/` namespaces unless the deployment actually uses them.
    - **Read:** `config/` (registry, etc.), `triggers/`, `projects/` (runners, inputs/datasets — structure as in `gcp/remote`).
    - **Write:** `triggers/` (acks, status, summaries), `<results_prefix>/snapshots/`, `<results_prefix>/current.json` (where `results_prefix` is per-BMT from jobs config, e.g. `projects/sk/results/false_rejects` as in repo).
    - **Secrets:** Secret Manager access limited to required GitHub App secrets only; list exact secret names in config/docs.
- [ ] **5.3 Artifact Registry**
  - **Task:** Provision Docker repository and set CI push permissions.
- [ ] **5.4 Trigger-Source Policy (Direct API vs Eventarc)**
  - **Task:** Choose and document one primary trigger path for CI (`direct-api` or `eventarc`) and enforce mutual exclusion. Implement a single source of truth for execution path (e.g. `BMT_EXECUTOR=job` vs Eventarc-only for internal triggers); ensure CI never enables both for the same workflow run.
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

- Prefer mount options such as `metadata-cache-ttl-secs`, `stat-cache-max-size-mb`, and `type-cache-max-size-mb`. Use `only-dir=runtime` only when the bucket has a `runtime/` prefix (current layout); when bucket root = gcp/remote (target), the mount is the whole bucket.
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
  - **File:** `gcp/image/projects/shared/bmt_manager_base.py` (in-image path consistent with Phase 4.1 layout).
  - **Task:** Detect `/mnt/runtime`. If present, bypass ALL `rsync` or download logic.
  - **Task:** Ensure `path_utils` resolves relative to the mount.
- [ ] **6.4 Post-Execution Coordinator**
  - **Task:** Define concrete coordinator runtime model: Option A (dedicated Cloud Run coordinator job) vs Option B (CI post-step coordinator command). Choose and document the default (e.g. CI post-step for Phase 7; optional Cloud Run coordinator job for later).
  - **Task:** Coordinator obtains registry and per-leg `results_prefix` from GCS (registry + jobs config) or from aggregated leg summaries; document how the coordinator gets registry/jobs (e.g. download from GCS, or from CI env).
  - **Task:** Define summary artifact contract path (e.g. `triggers/summaries/<workflow_run_id>/<leg>.json` under the mount root) and optional JSONL telemetry path with aggregation trigger condition.
  - **Task:** Coordinator must own final pointer updates, check/status publication, and cleanup. Define and document **who runs the coordinator** when CI uses `gcloud run jobs execute --wait`: e.g. last task in the same job, or a CI step after `--wait` that reads summary artifacts; ensure pointer/status/cleanup run exactly once.
- [ ] **6.5 Partial Failure and Retry Semantics**
  - **Task:** Specify behavior for missing leg summaries, retry exhaustion, partial success/failure outcomes, and final gate decision mapping. **Explicit rules:** If any leg has no summary by timeout → aggregate = failure, reason = partial_missing. If all legs have summaries → aggregate = failure if any leg failed; success only if all passed. Retry exhaustion for one leg → that leg = failure; others unchanged.
  - **Task:** Ensure coordinator logic is idempotent for safe retries (e.g. write pointer/status keyed by workflow_run_id; overwrite or skip-if-already-final so retries do not duplicate status or corrupt pointer).

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

**Done when:** CI uses direct API handoff with `--wait`; shadow parity and rollback drill are complete (per Verification Matrix: parity target, rollback drill with VM-gated run); VM fleet is decommissioned and Verification Matrix criteria are met.

---

## Phase 7: CI/CD Integration & Direct API

**Goal:** Replace async polling with synchronous, observable handoffs.

- [ ] **7.0 Trigger + Handshake Semantics (Cloud Run Model)**
  - **Task:** Define whether CI still writes run trigger files when direct API execution is used.
  - **Task:** Document handshake equivalence: `gcloud run jobs execute --wait` completion replaces VM ack semantics.
  - **Task:** Define explicit failure fallback behavior when job execution fails before summary aggregation. Align with Phase 6.4: who runs the coordinator when using `--wait` (same job’s final task vs CI step) so pointer/status/cleanup always run exactly once.

- [ ] **7.1 Direct API Handoff**
  - **File:** `.github/workflows/bmt-handoff.yml`
  - **Task:** Use `gcloud run jobs execute` with the `--wait` flag. Pass the image digest (or tag that resolves to digest) so the executed image is immutable for the run.
  - **Task:** Stream container logs directly to the CI console.
- [ ] **7.2 WIF Identity Alignment**
  - **Task:** Grant GitHub WIF `roles/run.invoker` (or `roles/run.developer` only when deploy mutation is needed) and `roles/iam.serviceAccountUser` scoped to execution SA.
  - **Task:** Enforce repository/branch attribute conditions for WIF principal bindings.
- [ ] **7.3 Eventarc (Secondary/Internal Trigger)**
  - **Task:** Provision `gcp.eventarc.Trigger` as a fallback for GCS file-based triggers.
  - **Requirement:** Eventarc path must be mutually exclusive with direct API execution mode to prevent duplicate runs.
- [ ] **7.4 Cleanup Ownership in Job Model**
  - **Task:** Assign ownership for trigger/ack/status/summaries cleanup to the coordinator stage.
  - **Task:** Define cleanup order (e.g. post status/check last, then delete trigger/ack/status) and retention rule (e.g. delete only after N hours or after run is finalized) so artifacts needed for postmortems are not removed too early.

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
  - **Task:** Execute a documented rollback to VM path (`BMT_EXECUTOR=vm` and legacy handoff path restoration) and verify one full successful gate run. Ensure the workflow (or bmt command) reads `BMT_EXECUTOR`; when `vm`, use start-vm + wait-handshake and do not call `gcloud run jobs execute`. Document where the variable is set and the exact conditional.
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
| **0** | `pytest tests/` passes with fixed pattern; `just validate-layout` passes; unit test for `local_digest()` asserts `inputs/` WAVs are excluded; manifest JSON generated and round-trips through `InputFileRegistry` |
| **1-3** | `pytest tests/` (Unit tests for types and extraction) |
| **4** | `docker run` (Local FUSE simulation) |
| **5-6** | `just deploy` + Manual Job Execution in GCP Console |
| **5.5** | IAM/WIF policy validation (resource-scoped secrets/storage, attribute conditions, digest policy checks) |
| **7** | `gh run view` (Logs streaming in GitHub Actions) + fallback behavior verification |
| **6** | Run matrix of ≥20 legs and single leg with 40GB dataset; document resource tier and success criteria (goal: 20+ projects, 40GB startup wall) |
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
