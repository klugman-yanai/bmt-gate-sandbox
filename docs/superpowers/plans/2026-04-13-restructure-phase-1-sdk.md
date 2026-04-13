# Restructure Phase 1: Extract `bmt-sdk` Package

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a standalone `bmt-sdk` package containing only `BmtPlugin`, `ExecutionContext`, and result types — no Pydantic, no GCS, no runtime deps — so contributors can `pip install bmt-sdk` and write plugins without installing the full runtime.

**Architecture:** Create `sdk/bmt_sdk/` as a new uv workspace member with stdlib-only deps. Define simple dataclass "view" types (`BmtManifestView`, `ProjectManifestView`) that mirror the runtime's Pydantic models without the heavy deps. Update `gcp/image/runtime/execution.py` to construct these views from Pydantic models before building `ExecutionContext`. Re-export from `gcp/image/runtime/sdk/` for backward compat. Update the SK plugin to import from `bmt_sdk`.

**Tech Stack:** Python 3.12, uv workspaces, dataclasses (stdlib only for `bmt_sdk`), pytest

---

## File Map

| File | Action |
|---|---|
| `sdk/pyproject.toml` | Create — `bmt-sdk` package, no external deps |
| `sdk/bmt_sdk/__init__.py` | Create — public exports |
| `sdk/bmt_sdk/models.py` | Create — `BmtManifestView`, `ProjectManifestView`, nested view types |
| `sdk/bmt_sdk/context.py` | Create — `ExecutionContext` using view types |
| `sdk/bmt_sdk/results.py` | Create — `PreparedAssets`, `CaseResult`, `ExecutionResult`, `ScoreResult`, `VerdictResult` |
| `sdk/bmt_sdk/plugin.py` | Create — `BmtPlugin` ABC |
| `pyproject.toml` | Modify — add `sdk` to workspace members, add `bmt-sdk` to sources |
| `gcp/image/pyproject.toml` | Modify — add `bmt-sdk` dependency |
| `gcp/image/runtime/sdk/plugin.py` | Modify — re-export from `bmt_sdk` |
| `gcp/image/runtime/sdk/context.py` | Modify — re-export from `bmt_sdk` |
| `gcp/image/runtime/sdk/results.py` | Modify — re-export from `bmt_sdk` |
| `gcp/image/runtime/sdk/__init__.py` | Modify — update docstring |
| `gcp/image/runtime/execution.py` | Modify — wrap Pydantic models into view types before constructing `ExecutionContext` |
| `gcp/stage/projects/sk/plugin_workspaces/default/src/sk_plugin/plugin.py` | Modify — update imports to `bmt_sdk` |
| `tests/sdk/test_bmt_sdk.py` | Create — tests for `bmt_sdk` with no runtime installed |

---

### Task 1: Create `sdk/pyproject.toml` and package skeleton

**Files:**
- Create: `sdk/pyproject.toml`
- Create: `sdk/bmt_sdk/__init__.py`

- [ ] **Step 1: Create `sdk/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "bmt-sdk"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[tool.uv]
package = true

[tool.setuptools.packages.find]
where = ["."]
include = ["bmt_sdk*"]
```

- [ ] **Step 2: Create `sdk/bmt_sdk/__init__.py`**

```python
"""Stable BMT plugin SDK — zero external dependencies."""
```

- [ ] **Step 3: Verify directory exists**

```bash
ls sdk/
```

Expected: `pyproject.toml  bmt_sdk/`

---

### Task 2: Create `sdk/bmt_sdk/models.py` — view types

**Files:**
- Create: `sdk/bmt_sdk/models.py`

These are pure stdlib dataclasses that mirror the Pydantic models in `gcp/image/runtime/models.py`. They have no Pydantic dependency. The runtime wraps its Pydantic models into these views before passing them to plugins.

- [ ] **Step 1: Write `sdk/bmt_sdk/models.py`**

```python
"""Lightweight read-only views of BMT manifest data.

These are dataclasses (no Pydantic). The runtime constructs them from its
own Pydantic models before passing an ExecutionContext to a plugin. Plugins
read from these views; they never construct them directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ExecutionConfigView:
    policy: str = "adaptive_batch_then_legacy"
    profile: str = "standard"


@dataclass(frozen=True, slots=True)
class RunnerConfigView:
    uri: str = ""
    deps_prefix: str = ""
    template_path: str = "runtime/assets/kardome_input_template.json"


@dataclass(frozen=True, slots=True)
class ProjectManifestView:
    project: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class BmtManifestView:
    project: str
    bmt_slug: str
    bmt_id: str
    enabled: bool
    plugin_config: dict[str, Any]
    inputs_prefix: str = ""
    results_prefix: str = ""
    outputs_prefix: str = ""
    execution: ExecutionConfigView = field(default_factory=ExecutionConfigView)
    runner: RunnerConfigView = field(default_factory=RunnerConfigView)
```

---

### Task 3: Create `sdk/bmt_sdk/results.py` and `sdk/bmt_sdk/context.py`

**Files:**
- Create: `sdk/bmt_sdk/results.py`
- Create: `sdk/bmt_sdk/context.py`

- [ ] **Step 1: Write `sdk/bmt_sdk/results.py`**

This is identical in content to the current `gcp/image/runtime/sdk/results.py` but standalone.

```python
"""Execution and scoring value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

CaseStatus = Literal["ok", "failed"]


@dataclass(frozen=True, slots=True)
class PreparedAssets:
    dataset_root: Path
    workspace_root: Path
    runner_path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    input_path: Path
    exit_code: int
    status: CaseStatus
    metrics: dict[str, float] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    error: str = ""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    execution_mode_used: str
    case_results: list[CaseResult]
    raw_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScoreResult:
    aggregate_score: float
    metrics: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VerdictResult:
    passed: bool
    status: str
    reason_code: str
    summary: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 2: Write `sdk/bmt_sdk/context.py`**

Uses `BmtManifestView` and `ProjectManifestView` — no Pydantic.

```python
"""Plugin execution context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bmt_sdk.models import BmtManifestView, ProjectManifestView


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    project_manifest: ProjectManifestView
    bmt_manifest: BmtManifestView
    plugin_root: Path
    workspace_root: Path
    dataset_root: Path
    outputs_root: Path
    logs_root: Path
    runner_path: Path | None = None
    deps_root: Path | None = None
```

---

### Task 4: Create `sdk/bmt_sdk/plugin.py` and update `__init__.py`

**Files:**
- Create: `sdk/bmt_sdk/plugin.py`
- Modify: `sdk/bmt_sdk/__init__.py`

- [ ] **Step 1: Write `sdk/bmt_sdk/plugin.py`**

```python
"""Contributor plugin contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from bmt_sdk.context import ExecutionContext
from bmt_sdk.results import ExecutionResult, PreparedAssets, ScoreResult, VerdictResult


class BmtPlugin(ABC):
    """Stable BMT plugin contract.

    Subclass this and implement all four methods. Drop your subclass in
    ``plugins/<project>/plugin.py`` — the runtime discovers it automatically.
    """

    plugin_name = "default"
    api_version = "v1"

    @abstractmethod
    def prepare(self, context: ExecutionContext) -> PreparedAssets:
        """Resolve assets needed before execution."""

    @abstractmethod
    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        """Run a BMT leg and return normalized results."""

    @abstractmethod
    def score(
        self,
        execution_result: ExecutionResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> ScoreResult:
        """Convert normalized execution output into a score."""

    @abstractmethod
    def evaluate(
        self,
        score_result: ScoreResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> VerdictResult:
        """Return pass/fail semantics for the score."""
```

- [ ] **Step 2: Update `sdk/bmt_sdk/__init__.py` with public exports**

```python
"""Stable BMT plugin SDK — zero external dependencies.

Typical usage::

    from bmt_sdk import BmtPlugin, ExecutionContext
    from bmt_sdk.results import ExecutionResult, PreparedAssets, ScoreResult, VerdictResult

Install with: pip install bmt-sdk
"""

from bmt_sdk.context import ExecutionContext
from bmt_sdk.models import BmtManifestView, ProjectManifestView
from bmt_sdk.plugin import BmtPlugin
from bmt_sdk.results import (
    CaseResult,
    CaseStatus,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)

__all__ = [
    "BmtPlugin",
    "BmtManifestView",
    "ProjectManifestView",
    "ExecutionContext",
    "CaseResult",
    "CaseStatus",
    "ExecutionResult",
    "PreparedAssets",
    "ScoreResult",
    "VerdictResult",
]
```

---

### Task 5: Add `sdk` to uv workspace

**Files:**
- Modify: `pyproject.toml` (lines 26-32)

- [ ] **Step 1: Write failing test to confirm `bmt_sdk` is not yet importable as a workspace package**

```bash
uv run python -c "import bmt_sdk; print(bmt_sdk.__file__)"
```

Expected: error (ModuleNotFoundError or resolves from wrong location)

- [ ] **Step 2: Update `pyproject.toml` workspace and sources**

In `pyproject.toml`, update these two sections:

```toml
[tool.uv.sources]
bmt = { workspace = true }
bmt-sdk = { workspace = true }
bmt-gcloud = { workspace = true }

[tool.uv.workspace]
members = [".github/bmt", "gcp/image", "sdk"]
```

- [ ] **Step 3: Run `uv sync` to update the lockfile**

```bash
uv sync
```

Expected: lockfile updated, no errors

- [ ] **Step 4: Verify `bmt_sdk` is importable**

```bash
uv run python -c "from bmt_sdk import BmtPlugin; print('ok')"
```

Expected: `ok`

---

### Task 6: Write tests for `bmt_sdk` standalone

**Files:**
- Create: `tests/sdk/test_bmt_sdk.py`
- Create: `tests/sdk/__init__.py`

Tests must pass without importing anything from `gcp.image`.

- [ ] **Step 1: Create `tests/sdk/__init__.py`**

```python
```

- [ ] **Step 2: Write `tests/sdk/test_bmt_sdk.py`**

```python
"""Tests for the bmt_sdk package — no runtime imports allowed."""

from __future__ import annotations

from pathlib import Path

import pytest

# These imports must work without gcp.image installed
from bmt_sdk import BmtPlugin, ExecutionContext
from bmt_sdk.models import (
    BmtManifestView,
    ExecutionConfigView,
    ProjectManifestView,
    RunnerConfigView,
)
from bmt_sdk.results import (
    CaseResult,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)


def _make_context(plugin_config: dict | None = None) -> ExecutionContext:
    return ExecutionContext(
        project_manifest=ProjectManifestView(project="test"),
        bmt_manifest=BmtManifestView(
            project="test",
            bmt_slug="test_bmt",
            bmt_id="00000000-0000-0000-0000-000000000001",
            enabled=True,
            plugin_config=plugin_config or {},
        ),
        plugin_root=Path("/fake/plugin"),
        workspace_root=Path("/fake/workspace"),
        dataset_root=Path("/fake/dataset"),
        outputs_root=Path("/fake/outputs"),
        logs_root=Path("/fake/logs"),
    )


def test_bmt_plugin_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        BmtPlugin()  # type: ignore[abstract]


def test_bmt_plugin_subclass_must_implement_all_methods() -> None:
    class IncompletePlugin(BmtPlugin):
        def prepare(self, context: ExecutionContext) -> PreparedAssets:
            return PreparedAssets(
                dataset_root=context.dataset_root,
                workspace_root=context.workspace_root,
            )
        # Missing: execute, score, evaluate

    with pytest.raises(TypeError):
        IncompletePlugin()  # type: ignore[abstract]


def test_bmt_plugin_subclass_valid() -> None:
    class MinimalPlugin(BmtPlugin):
        def prepare(self, context: ExecutionContext) -> PreparedAssets:
            return PreparedAssets(
                dataset_root=context.dataset_root,
                workspace_root=context.workspace_root,
            )

        def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
            return ExecutionResult(execution_mode_used="test", case_results=[])

        def score(
            self,
            execution_result: ExecutionResult,
            baseline: ScoreResult | None,
            context: ExecutionContext,
        ) -> ScoreResult:
            return ScoreResult(aggregate_score=1.0)

        def evaluate(
            self,
            score_result: ScoreResult,
            baseline: ScoreResult | None,
            context: ExecutionContext,
        ) -> VerdictResult:
            return VerdictResult(passed=True, status="pass", reason_code="ok")

    plugin = MinimalPlugin()
    ctx = _make_context()
    prepared = plugin.prepare(ctx)
    result = plugin.execute(ctx, prepared)
    score = plugin.score(result, None, ctx)
    verdict = plugin.evaluate(score, None, ctx)
    assert verdict.passed is True
    assert verdict.status == "pass"


def test_execution_context_is_frozen() -> None:
    ctx = _make_context()
    with pytest.raises((AttributeError, TypeError)):
        ctx.workspace_root = Path("/other")  # type: ignore[misc]


def test_bmt_manifest_view_defaults() -> None:
    view = BmtManifestView(
        project="acme",
        bmt_slug="false_alarms",
        bmt_id="uuid",
        enabled=True,
        plugin_config={},
    )
    assert view.execution.policy == "adaptive_batch_then_legacy"
    assert view.runner.uri == ""


def test_no_gcp_image_import_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify bmt_sdk has no gcp.image dependency at import time."""
    import sys
    # Remove gcp.image from sys.modules if present and re-import bmt_sdk
    gcp_modules = [k for k in sys.modules if k.startswith("gcp")]
    saved = {k: sys.modules.pop(k) for k in gcp_modules}
    try:
        import importlib
        import bmt_sdk
        importlib.reload(bmt_sdk)
        # If we reach here, bmt_sdk imported fine without gcp.image
    finally:
        sys.modules.update(saved)
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
uv run python -m pytest tests/sdk/ -v
```

Expected: 6 tests passing

---

### Task 7: Update runtime `gcp/image/` to depend on `bmt-sdk` and re-export

**Files:**
- Modify: `gcp/image/pyproject.toml`
- Modify: `gcp/image/runtime/sdk/plugin.py`
- Modify: `gcp/image/runtime/sdk/context.py`
- Modify: `gcp/image/runtime/sdk/results.py`
- Modify: `gcp/image/runtime/sdk/__init__.py`

- [ ] **Step 1: Add `bmt-sdk` to `gcp/image/pyproject.toml` dependencies**

```toml
[project]
name = "bmt-runtime"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "bmt-sdk",
  "google-cloud-secret-manager>=2.23",
  "google-cloud-storage>=2.16",
  "PyGithub>=2.0",
  "PyJWT>=2.0",
  "cryptography>=41.0",
  "pydantic>=2.12.5",
  "typer>=0.12",
  "whenever>=0.9.5",
]
```

- [ ] **Step 2: Replace `gcp/image/runtime/sdk/plugin.py` with re-export**

```python
"""Backward-compatible re-export. Import from bmt_sdk instead."""

from bmt_sdk.plugin import BmtPlugin

__all__ = ["BmtPlugin"]
```

- [ ] **Step 3: Replace `gcp/image/runtime/sdk/context.py` with re-export**

```python
"""Backward-compatible re-export. Import from bmt_sdk instead."""

from bmt_sdk.context import ExecutionContext

__all__ = ["ExecutionContext"]
```

- [ ] **Step 4: Replace `gcp/image/runtime/sdk/results.py` with re-export**

```python
"""Backward-compatible re-export. Import from bmt_sdk instead."""

from bmt_sdk.results import (
    CaseResult,
    CaseStatus,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)

__all__ = [
    "CaseResult",
    "CaseStatus",
    "ExecutionResult",
    "PreparedAssets",
    "ScoreResult",
    "VerdictResult",
]
```

- [ ] **Step 5: Update `gcp/image/runtime/sdk/__init__.py`**

```python
"""Stable plugin SDK surface. Re-exported from bmt_sdk — import from there directly."""
```

- [ ] **Step 6: Run `uv sync` and verify existing runtime imports still resolve**

```bash
uv sync
uv run python -c "from gcp.image.runtime.sdk.plugin import BmtPlugin; print('compat ok')"
```

Expected: `compat ok`

---

### Task 8: Update `execution.py` — wrap Pydantic models into SDK views

**Files:**
- Modify: `gcp/image/runtime/execution.py`

`ExecutionContext` now uses `BmtManifestView` and `ProjectManifestView` from `bmt_sdk`. The runtime constructs these views from its Pydantic models before calling plugin methods.

- [ ] **Step 1: Write a failing test confirming the adapter is needed**

Run existing execution tests:

```bash
uv run python -m pytest tests/bmt/test_framework_execution.py -v
```

Note current pass/fail baseline before changing `execution.py`.

- [ ] **Step 2: Update imports and construction in `gcp/image/runtime/execution.py`**

Replace the current `ExecutionContext` construction (lines 54-64) with the adapter pattern:

```python
"""Execute a planned leg using the new plugin contract."""

from __future__ import annotations

import json

from bmt_sdk.context import ExecutionContext
from bmt_sdk.models import (
    BmtManifestView,
    ExecutionConfigView,
    ProjectManifestView,
    RunnerConfigView,
)
from gcp.image.config.bmt_domain_status import BmtLegStatus
from gcp.image.runtime.models import (
    BmtManifest,
    ExecutionPlan,
    LegSummary,
    PlanLeg,
    ProjectManifest,
    ScorePayload,
    StageRuntimePaths,
)
from gcp.image.runtime.plugin_loader import load_plugin


def _make_manifest_view(m: BmtManifest) -> BmtManifestView:
    return BmtManifestView(
        project=m.project,
        bmt_slug=m.bmt_slug,
        bmt_id=m.bmt_id,
        enabled=m.enabled,
        plugin_config=dict(m.plugin_config),
        inputs_prefix=m.inputs_prefix,
        results_prefix=str(m.results_path),
        outputs_prefix=m.outputs_prefix,
        execution=ExecutionConfigView(
            policy=m.execution.policy,
            profile=m.execution.profile,
        ),
        runner=RunnerConfigView(
            uri=m.runner.uri,
            deps_prefix=m.runner.deps_prefix,
            template_path=m.runner.template_path,
        ),
    )


def _make_project_view(p: ProjectManifest) -> ProjectManifestView:
    return ProjectManifestView(
        project=p.project,
        description=p.description,
    )


def execute_leg(*, plan: ExecutionPlan, leg: PlanLeg, runtime: StageRuntimePaths) -> LegSummary:
    use_mock = plan.use_mock_runner
    del plan
    if use_mock:
        return LegSummary(
            project=leg.project,
            bmt_slug=leg.bmt_slug,
            bmt_id=leg.bmt_id,
            run_id=leg.run_id,
            status=BmtLegStatus.PASS.value,
            reason_code="bootstrap_without_baseline",
            plugin_ref=leg.plugin_ref,
            execution_mode_used="mock",
            score=ScorePayload(aggregate_score=0.0),
        )
    manifest_path = runtime.stage_root / leg.manifest_path
    bmt_manifest = BmtManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    project_manifest_path = runtime.stage_root / "projects" / leg.project / "project.json"
    project_manifest = ProjectManifest.model_validate(
        json.loads(project_manifest_path.read_text(encoding="utf-8"))
    )
    plugin, plugin_root = load_plugin(
        runtime.stage_root,
        leg.project,
        bmt_manifest.plugin_ref,
        allow_workspace=False,
    )

    run_root = runtime.workspace_root / leg.project / leg.bmt_slug / leg.run_id
    outputs_root = run_root / "outputs"
    logs_root = run_root / "logs"
    outputs_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)

    deps_prefix = bmt_manifest.runner.deps_prefix.strip()
    context = ExecutionContext(
        project_manifest=_make_project_view(project_manifest),
        bmt_manifest=_make_manifest_view(bmt_manifest),
        plugin_root=plugin_root,
        workspace_root=run_root,
        dataset_root=runtime.stage_root / bmt_manifest.inputs_prefix,
        outputs_root=outputs_root,
        logs_root=logs_root,
        runner_path=(runtime.stage_root / bmt_manifest.runner.uri) if bmt_manifest.runner.uri else None,
        deps_root=(runtime.stage_root / deps_prefix) if deps_prefix else None,
    )
    prepared = plugin.prepare(context)
    execution_result = plugin.execute(context, prepared)
    score = plugin.score(execution_result, None, context)
    verdict = plugin.evaluate(score, None, context)

    return LegSummary(
        project=leg.project,
        bmt_slug=leg.bmt_slug,
        bmt_id=leg.bmt_id,
        run_id=leg.run_id,
        status=verdict.status,
        reason_code=verdict.reason_code,
        plugin_ref=leg.plugin_ref,
        execution_mode_used=execution_result.execution_mode_used,
        score=ScorePayload(
            aggregate_score=score.aggregate_score,
            metrics=score.metrics,
            extra=score.extra,
        ),
        verdict_summary=verdict.summary,
    )
```

- [ ] **Step 3: Run execution tests**

```bash
uv run python -m pytest tests/bmt/test_framework_execution.py -v
```

Expected: same pass/fail as baseline from Step 1

---

### Task 9: Update SK plugin imports to use `bmt_sdk`

**Files:**
- Modify: `gcp/stage/projects/sk/plugin_workspaces/default/src/sk_plugin/plugin.py`

- [ ] **Step 1: Run the SK plugin load test to establish baseline**

```bash
uv run python -m pytest tests/bmt/ -k "plugin_load or sk_plugin" -v
```

Note current result.

- [ ] **Step 2: Update imports in `sk_plugin/plugin.py`**

Replace the first 8 import lines:

```python
# Before
from gcp.image.config.bmt_domain_status import BmtLegStatus
from gcp.image.runtime.kardome_batch_results import KardomeBatchFile
from gcp.image.runtime.legacy_kardome import LegacyKardomeStdoutConfig, LegacyKardomeStdoutExecutor
from gcp.image.runtime.sdk.context import ExecutionContext
from gcp.image.runtime.sdk.kardome import AdaptiveKardomeExecutor
from gcp.image.runtime.sdk.plugin import BmtPlugin
from gcp.image.runtime.sdk.results import (
    CaseResult,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)
from gcp.image.runtime.stdout_counter_parse import StdoutCounterParseConfig
```

```python
# After
from bmt_sdk import BmtPlugin
from bmt_sdk.context import ExecutionContext
from bmt_sdk.results import (
    CaseResult,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)
from gcp.image.config.bmt_domain_status import BmtLegStatus
from gcp.image.runtime.kardome_batch_results import KardomeBatchFile
from gcp.image.runtime.legacy_kardome import LegacyKardomeStdoutConfig, LegacyKardomeStdoutExecutor
from gcp.image.runtime.sdk.kardome import AdaptiveKardomeExecutor
from gcp.image.runtime.stdout_counter_parse import StdoutCounterParseConfig
```

- [ ] **Step 3: Run SK plugin tests**

```bash
uv run python -m pytest tests/bmt/ -k "plugin_load or sk_plugin" -v
```

Expected: same result as baseline

---

### Task 10: Full test suite and commit

**Files:** none (verification only)

- [ ] **Step 1: Run full test suite**

```bash
uv run python -m pytest tests/ -v --ignore=tests/vm
```

Expected: same pass/fail as before this phase (4 pre-existing failures unrelated to this work are acceptable: `test_committed_bmt_manifest_static` x2, `test_upload_dataset_uses_*` x2)

- [ ] **Step 2: Run type checker**

```bash
uv run ty check
```

Expected: no new errors introduced

- [ ] **Step 3: Run linter**

```bash
uv run ruff check . && uv run ruff format --check .
```

Expected: clean

- [ ] **Step 4: Commit**

```bash
git add sdk/ \
  gcp/image/pyproject.toml \
  gcp/image/runtime/sdk/plugin.py \
  gcp/image/runtime/sdk/context.py \
  gcp/image/runtime/sdk/results.py \
  gcp/image/runtime/sdk/__init__.py \
  gcp/image/runtime/execution.py \
  gcp/stage/projects/sk/plugin_workspaces/default/src/sk_plugin/plugin.py \
  pyproject.toml \
  uv.lock \
  tests/sdk/
git commit -m "feat(sdk): extract bmt-sdk package — BmtPlugin interface with zero external deps"
```
