# Python Core Interface Architecture for BMT System

**Status:** Proposed  
**Date:** 2026-03-15  
**Goal:** Define a Python core interface architecture that: (1) manages BMT runtime reliably, (2) auths/communicates with GitHub for PR context and response payloads, (3) manages N BMT legs, (4) works with gcsfuse-mounted bucket runtime, and (5) exposes an intuitive non-RESTful contributor API based on base classes, interfaces, protocols, and JSON schemas.

---

## 1. Architecture Overview

The BMT system orchestrates batch quality tests across multiple project legs, reads/writes artifacts from GCS (or gcsfuse-mounted paths), and reports outcomes to GitHub via commit status and Check Runs. The proposed architecture separates:

- **Core domain** — Models, contracts, lifecycle
- **Runtime management** — Trigger discovery, leg orchestration, pointer/snapshot semantics
- **Storage port** — Abstract interface over GCS API vs gcsfuse filesystem
- **GitHub port** — Auth, status, checks, PR context
- **Contributor API** — Protocols, ABCs, and JSON schemas for project managers

---

## 2. Module Boundaries

```
gcp/image/
├── core/                          # Domain models, contracts, lifecycle
│   ├── __init__.py
│   ├── models.py                  # Value objects, TypedDict payloads
│   ├── constants.py               # Path keys, status enums, decision codes
│   ├── contracts/                 # Contributor-facing interfaces
│   │   ├── __init__.py
│   │   ├── manager.py             # BmtManager Protocol + BaseBmtManager ABC
│   │   ├── storage.py             # RuntimeStorage Protocol
│   │   └── github.py              # GitHubClient Protocol
│   └── lifecycle.py               # Lifecycle hooks registry
│
├── runtime/                       # BMT runtime orchestration
│   ├── __init__.py
│   ├── trigger_pipeline.py       # Trigger discovery → handshake → leg resolution
│   ├── coordinator.py            # Aggregation, pointer update, status/check, cleanup
│   ├── leg_executor.py            # Single-leg execution (orchestrator logic)
│   └── gate.py                    # Gate evaluation (pure, no I/O)
│
├── adapters/                      # Concrete implementations
│   ├── __init__.py
│   ├── storage_gcs.py            # GCS SDK + gcloud CLI adapter
│   ├── storage_fuse.py           # gcsfuse path adapter (Path-based)
│   ├── github_app.py              # GitHub App auth + status/checks
│   └── runner_subprocess.py       # Subprocess-based leg runner
│
├── projects/                      # Project managers (contributor implementations)
│   ├── shared/
│   │   ├── bmt_manager_base.py    # BaseBmtManager implementation
│   │   └── schemas/               # JSON schemas for bmt_jobs, ci_verdict, etc.
│   ├── sk/
│   │   └── bmt_manager.py
│   └── skyworth/
│       └── bmt_manager.py
│
├── cli.py                         # Typer entrypoint (watcher, orchestrator)
├── vm_watcher.py                  # Thin adapter over trigger_pipeline + coordinator
└── root_orchestrator.py           # Thin adapter over leg_executor
```

**Boundary rules:**
- `core/` has **zero** dependencies on `runtime/`, `adapters/`, or `projects/`
- `runtime/` depends only on `core/` and injected ports (Protocols)
- `adapters/` implement `core/contracts/*` and are injected into runtime
- `projects/` depend on `core/contracts/manager` and `projects/shared/bmt_manager_base`

---

## 3. Contracts (Protocols and ABCs)

### 3.1 RuntimeStorage Protocol

Abstracts GCS API vs gcsfuse-mounted filesystem. Enables zero-download when `/mnt/runtime` exists.

```python
# core/contracts/storage.py

from typing import Protocol, runtime_checkable

@runtime_checkable
class RuntimeStorage(Protocol):
    """Port for reading/writing runtime artifacts (triggers, snapshots, current.json)."""

    def read_json(self, path: str) -> dict | None:
        """Read JSON from runtime path. Returns None on 404/invalid."""
        ...

    def write_json(self, path: str, payload: dict) -> bool:
        """Write JSON to runtime path. Returns True on success."""
        ...

    def exists(self, path: str) -> bool:
        """Check if object exists."""
        ...

    def list_prefix(self, prefix: str) -> list[str]:
        """List object keys under prefix. Returns full paths or URIs."""
        ...

    def delete(self, path: str) -> bool:
        """Delete object. Returns True on success or if not found."""
        ...

    def resolve_input_path(self, relative_path: str) -> Path:
        """Resolve relative runtime path to local Path (gcsfuse) or staging path (GCS download)."""
        ...

    @property
    def runtime_root(self) -> str:
        """Runtime root URI or mount path (e.g. gs://bucket or /mnt/runtime)."""
        ...
```

**Implementations:**
- `StorageGcsAdapter` — Uses GCS SDK + gcloud; downloads to staging for reads
- `StorageFuseAdapter` — Uses `Path("/mnt/runtime")`; no download, direct file I/O

### 3.2 GitHubClient Protocol

Abstracts GitHub API for status, checks, PR state, and comments.

```python
# core/contracts/github.py

from typing import Protocol, runtime_checkable

@runtime_checkable
class GitHubClient(Protocol):
    """Port for GitHub API operations."""

    def get_token(self, repository: str) -> str | None:
        """Resolve installation token for repository."""
        ...

    def post_commit_status(
        self,
        repository: str,
        sha: str,
        state: str,
        description: str,
        *,
        context: str,
        target_url: str | None = None,
    ) -> bool:
        """Post commit status. state: pending|success|failure|error."""
        ...

    def create_check_run(
        self,
        repository: str,
        sha: str,
        name: str,
        status: str,
        output: dict,
    ) -> tuple[int | None, str]:
        """Create Check Run. Returns (check_run_id, token)."""
        ...

    def update_check_run(
        self,
        repository: str,
        check_run_id: int,
        output: dict,
        token: str,
    ) -> bool:
        """Update Check Run output."""
        ...

    def complete_check_run(
        self,
        repository: str,
        sha: str,
        check_run_id: int,
        conclusion: str,
        output: dict,
        token: str,
    ) -> bool:
        """Complete Check Run. conclusion: success|failure|neutral|cancelled."""
        ...

    def get_pr_state(self, repository: str, pr_number: int) -> dict:
        """Get PR state (state, head_sha, merged, etc.)."""
        ...

    def upsert_pr_comment(self, repository: str, pr_number: int, marker: str, body: str) -> bool:
        """Upsert PR comment by marker."""
        ...
```

### 3.3 BmtManager Protocol (Structural)

Primary contributor interface for type-checking and IDE support. No runtime coupling.

```python
# core/contracts/manager.py

from typing import Protocol, runtime_checkable
from pathlib import Path

@runtime_checkable
class BmtManagerProtocol(Protocol):
    """Structural protocol for BMT managers. Contributors implement this."""

    def setup_assets(self) -> None:
        """Download/cache runner, template, and assets. Populate run_root staging."""
        ...

    def collect_input_files(self, inputs_root: Path) -> list[Path]:
        """Return list of input files to process."""
        ...

    def run_file(self, input_file: Path, inputs_root: Path) -> dict:
        """Run BMT on single file. Returns {file, exit_code, status, error, ...}."""
        ...

    def compute_score(self, file_results: list[dict]) -> float:
        """Compute aggregate score from per-file results."""
        ...

    def get_runner_identity(self) -> dict:
        """Return runner metadata (name, build_id, source_ref)."""
        ...

    def evaluate_gate(
        self,
        aggregate_score: float,
        last_score: float | None,
        failed_count: int,
        file_results: list[dict],
    ) -> dict:
        """Compute pass/fail. Returns {passed, reason, ...}."""
        ...
```

### 3.4 BaseBmtManager ABC (Runtime Contract)

Thin ABC that enforces mandatory lifecycle hooks and provides orchestration skeleton. Contributors subclass this.

```python
# core/contracts/manager.py (continued)

from abc import ABC, abstractmethod

class BaseBmtManager(ABC, BmtManagerProtocol):
    """Abstract base for BMT managers. Requires lifecycle hooks."""

    # --- Lifecycle hooks (called by framework) ---

    @abstractmethod
    def setup_assets(self) -> None: ...

    @abstractmethod
    def collect_input_files(self, inputs_root: Path) -> list[Path]: ...

    @abstractmethod
    def run_file(self, input_file: Path, inputs_root: Path) -> dict: ...

    @abstractmethod
    def compute_score(self, file_results: list[dict]) -> float: ...

    @abstractmethod
    def get_runner_identity(self) -> dict: ...

    @abstractmethod
    def evaluate_gate(
        self,
        aggregate_score: float,
        last_score: float | None,
        failed_count: int,
        file_results: list[dict],
    ) -> dict: ...

    # --- Optional hooks (override for customization) ---

    def get_inputs_root(self) -> Path:
        """Override to change inputs location. Default: staging_dir/inputs."""
        return getattr(self, "_inputs_root", self.staging_dir / "inputs")

    def artifact_uris(self) -> dict[str, str]:
        """Override to add artifact URIs to latest.json."""
        return {}

    # --- Main entry (framework-owned) ---

    def run(self) -> int:
        """Execute full orchestration. Returns 0 (pass) or 1 (fail)."""
        # Framework orchestrates: setup_assets → collect_input_files → run_file loop
        # → compute_score → evaluate_gate → write outputs. Subclasses do not override.
        ...
```

---

## 4. JSON Schemas (Contributor API)

| Schema | Path | Purpose |
|--------|------|---------|
| `trigger_payload` | `core/schemas/trigger.json` | Run trigger payload (legs, repository, sha, workflow_run_id) |
| `handshake_payload` | `core/schemas/handshake.json` | VM/coordinator ack payload |
| `leg_summary` | `core/schemas/leg_summary.json` | Per-leg outcome (index, project, bmt_id, decision, reason) |
| `manager_summary` | `core/schemas/manager_summary.json` | Manager output (status, reason_code, ci_verdict_uri) |
| `ci_verdict` | `core/schemas/ci_verdict.json` | CI verdict (run_id, status, gate, artifacts) |
| `current_pointer` | `core/schemas/current.json` | Pointer (latest, last_passing, updated_at) |
| `bmt_jobs` | `projects/shared/schemas/bmt_jobs.json` | BMT job config (bmts, paths, gate, parsing) |

Schemas enable:
- Validation at boundaries (trigger ingest, manager summary emit)
- Contributor documentation and examples
- Optional runtime validation (e.g. `jsonschema.validate` in dev)

---

## 5. Lifecycle Hooks

### 5.1 Manager Lifecycle (Per Leg)

```
1. __init__(args, bmt_cfg)
2. _setup_dirs()
3. setup_assets()           # Contributor: download/cache runner, template
4. get_inputs_root()
5. collect_input_files()    # Contributor: list inputs
6. [for each file] run_file()  # Contributor: run single file
7. compute_score()         # Contributor: aggregate score
8. evaluate_gate()         # Contributor: pass/fail decision
9. _write_run_outputs()    # Framework: latest.json, ci_verdict.json, uploads
```

### 5.2 Watcher/Coordinator Lifecycle (Per Run)

```
1. discover_triggers()
2. download_trigger()
3. resolve_legs()
4. check_pr_state()        # Optional: skip if PR closed / superseded
5. write_handshake()
6. write_initial_status()
7. [for each leg] execute_leg()
8. aggregate_verdicts()
9. update_pointers()
10. post_commit_status()
11. finalize_check_run()
12. cleanup_triggers()
```

### 5.3 Extensibility Hooks

| Hook | Module | When | Purpose |
|------|--------|------|---------|
| `before_leg_start` | `lifecycle.py` | Before each leg | Logging, metrics |
| `after_leg_complete` | `lifecycle.py` | After each leg | Custom aggregation |
| `before_pointer_update` | `lifecycle.py` | Before current.json write | Validation |
| `on_cancel` | `lifecycle.py` | On PR close/supersede | Cleanup |

Hooks are registered via a simple registry; default implementation is no-op.

```python
# core/lifecycle.py

_HOOKS: dict[str, list[Callable]] = {}

def register_hook(name: str, fn: Callable) -> None:
    _HOOKS.setdefault(name, []).append(fn)

def invoke_hooks(name: str, *args, **kwargs) -> None:
    for fn in _HOOKS.get(name, []):
        fn(*args, **kwargs)
```

---

## 6. gcsfuse Integration

### 6.1 Path Resolution Strategy

```python
# adapters/storage_fuse.py

FUSE_MOUNT_PATH = Path("/mnt/runtime")

def _is_fuse_mounted() -> bool:
    return FUSE_MOUNT_PATH.exists() and FUSE_MOUNT_PATH.is_dir()

class StorageFuseAdapter:
    """Uses gcsfuse mount for direct file I/O. No download."""

    def __init__(self, bucket: str, runtime_prefix: str = ""):
        self._mount = FUSE_MOUNT_PATH
        self._prefix = runtime_prefix.strip("/")

    def resolve_input_path(self, relative_path: str) -> Path:
        return self._mount / self._prefix / relative_path.lstrip("/")

    def read_json(self, path: str) -> dict | None:
        full = self._mount / self._prefix / path.lstrip("/")
        if not full.is_file():
            return None
        return json.loads(full.read_text())
```

### 6.2 Manager Detection

In `bmt_manager_base.py` (or `StorageFuseAdapter`):

```python
def get_storage_adapter(bucket: str, runtime_prefix: str) -> RuntimeStorage:
    if Path("/mnt/runtime").exists():
        return StorageFuseAdapter(bucket, runtime_prefix)
    return StorageGcsAdapter(bucket, runtime_prefix)
```

When FUSE is present, `setup_assets` skips all `rsync`/download; `get_inputs_root()` returns `Path("/mnt/runtime") / project / dataset_path`.

---

## 7. N-Leg Management

### 7.1 Leg Identity

```python
# core/models.py

@dataclass(frozen=True)
class LegIdentity:
    project: str
    bmt_id: str
    run_id: str
    index: int
```

### 7.2 Parallel vs Sequential

- **VM model:** Sequential legs (one subprocess per leg)
- **Cloud Run model:** Parallel tasks via `CLOUD_RUN_TASK_INDEX`; each task runs one leg
- **Coordinator:** Aggregates N leg summaries; owns pointer update and status posting

### 7.3 Leg Resolution Contract

```python
# runtime/trigger_pipeline.py

def resolve_legs(
    legs_raw: list[dict],
    storage: RuntimeStorage,
    jobs_loader: Callable[[str, str], dict],
) -> list[ResolvedLeg]:
    """Resolve requested legs to accepted/rejected. Returns only accepted."""
    ...
```

`ResolvedLeg` includes `LegIdentity`, `decision`, `reason`, and project/jobs config reference.

---

## 8. Dependency Injection

Runtime components receive ports via constructor injection:

```python
# runtime/coordinator.py

class BmtCoordinator:
    def __init__(
        self,
        storage: RuntimeStorage,
        github: GitHubClient,
        leg_executor: LegExecutor,
    ) -> None:
        self._storage = storage
        self._github = github
        self._leg_executor = leg_executor

    def run(self, trigger_uri: str) -> bool:
        payload = self._storage.read_json(trigger_uri)
        # ...
```

`vm_watcher.py` and `root_orchestrator.py` become thin wiring:

```python
# vm_watcher.py (simplified)

def main():
    storage = StorageGcsAdapter(bucket) if not fuse_mounted else StorageFuseAdapter(bucket)
    github = GitHubAppClient()
    pipeline = TriggerPipeline(storage, github)
    coordinator = BmtCoordinator(storage, github, SubprocessLegExecutor())
    pipeline.run(coordinator)
```

---

## 9. Summary: Deliverables

| Deliverable | Location | Description |
|-------------|----------|-------------|
| Module boundaries | `gcp/image/core`, `runtime`, `adapters`, `projects` | Clear separation; core has no I/O deps |
| RuntimeStorage Protocol | `core/contracts/storage.py` | GCS vs gcsfuse abstraction |
| GitHubClient Protocol | `core/contracts/github.py` | Status, checks, PR state |
| BmtManager Protocol | `core/contracts/manager.py` | Structural interface for contributors |
| BaseBmtManager ABC | `core/contracts/manager.py` | Runtime contract + lifecycle |
| JSON schemas | `core/schemas/`, `projects/shared/schemas/` | trigger, handshake, leg_summary, ci_verdict, bmt_jobs |
| Lifecycle hooks | `core/lifecycle.py` | before_leg_start, after_leg_complete, before_pointer_update |
| StorageFuseAdapter | `adapters/storage_fuse.py` | gcsfuse path-based storage |
| BmtCoordinator | `runtime/coordinator.py` | Aggregation, pointer update, status/check, cleanup |

---

## 10. Migration Path

1. **Phase 1:** Introduce `core/` (models, constants, contracts) without changing existing code.
2. **Phase 2:** Extract `gate.py`, `trigger_pipeline.py`, `coordinator.py` from `vm_watcher.py`; inject storage/github adapters.
3. **Phase 3:** Add `StorageFuseAdapter`; refactor `bmt_manager_base` to use `RuntimeStorage` port.
4. **Phase 4:** Migrate `BmtManagerBase` to implement `BaseBmtManager` from `core/contracts/manager.py`.
5. **Phase 5:** Add JSON schemas and lifecycle hooks; document contributor API.

This aligns with the holistic serverless migration plan (Phases 1–3) and the Cloud Run Jobs migration (gcsfuse, coordinator, parallel legs).
