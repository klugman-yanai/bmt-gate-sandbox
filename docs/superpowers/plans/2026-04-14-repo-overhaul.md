# Repo Overhaul: Domain Architecture Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `gcp/` monolith with five clean root-level domains (`sdk/`, `plugins/`, `runtime/`, `ci/`, `infra/`) so contributors can navigate the repo without prior knowledge and add a plugin in under 30 minutes.

**Architecture:** Five sequential phases, each mergeable independently. Phase 1 extracts the plugin SDK as a zero-dep installable. Phase 2 renames all top-level directories and updates every import. Phase 3 rewrites the plugin loader to load `plugin.py` directly by convention. Phase 4 flattens the `plugins/sk/` contributor structure. Phase 5 drops backward-compat shims and deletes dead directories.

**Tech Stack:** Python 3.12, uv workspaces, setuptools, pytest, git mv

---

## Import Mappings (reference for all phases)

After Phase 2, every `gcp.image.*` import becomes:

| Before | After |
|---|---|
| `from gcp.image.runtime.models import X` | `from runtime.models import X` |
| `from gcp.image.runtime.planning import X` | `from runtime.planning import X` |
| `from gcp.image.runtime.execution import X` | `from runtime.execution import X` |
| `from gcp.image.runtime.entrypoint import X` | `from runtime.entrypoint import X` |
| `from gcp.image.runtime.facade import X` | `from runtime.facade import X` |
| `from gcp.image.runtime.github_reporting import X` | `from runtime.github_reporting import X` |
| `from gcp.image.runtime.artifacts import X` | `from runtime.artifacts import X` |
| `from gcp.image.runtime.legacy_kardome import X` | `from runtime.legacy_kardome import X` |
| `from gcp.image.runtime.kardome_batch_results import X` | `from runtime.kardome_batch_results import X` |
| `from gcp.image.runtime.stdout_counter_parse import X` | `from runtime.stdout_counter_parse import X` |
| `from gcp.image.runtime.importer import X` | `from runtime.importer import X` |
| `from gcp.image.runtime.plugin_loader import X` | `from runtime.plugin_loader import X` |
| `from gcp.image.runtime.plugin_publisher import X` | `from runtime.plugin_publisher import X` |
| `from gcp.image.runtime.sdk.kardome import X` | `from runtime.kardome import X` |
| `from gcp.image.runtime.sdk.plugin import BmtPlugin` | `from bmt_sdk import BmtPlugin` (Phase 1) |
| `from gcp.image.runtime.sdk.context import X` | `from bmt_sdk import X` (Phase 1) |
| `from gcp.image.runtime.sdk.results import X` | `from bmt_sdk.results import X` (Phase 1) |
| `from gcp.image.config.X import Y` | `from runtime.config.X import Y` |
| `from gcp.image.github.X import Y` | `from runtime.github.X import Y` |
| `from gcp.image.main import X` | `from runtime.main import X` |

CI package intra-imports (all files in `ci/kardome_bmt/`):

| Before | After |
|---|---|
| `from ci import config` | `from kardome_bmt import config` |
| `from ci import core` | `from kardome_bmt import core` |
| `from ci import gcs` | `from kardome_bmt import gcs` |
| `from ci import github, handoff_dataset` | `from kardome_bmt import github, handoff_dataset` |

---

## Phase 1: Extract `bmt-sdk` package

**→ Full plan already written at `docs/superpowers/plans/2026-04-13-restructure-phase-1-sdk.md`.**

Quick summary: create `sdk/bmt_sdk/` with `plugin.py`, `context.py` (using view types), `results.py`, `models.py` (view dataclasses). Add `sdk` to uv workspace. Re-export from `gcp/image/runtime/sdk/` for backward compat. Update SK plugin imports to `from bmt_sdk import BmtPlugin`.

**Gate:** `uv run python -m pytest tests/ -v` passes; `from bmt_sdk import BmtPlugin` works.

---

## Phase 2: Rename top-level directories and update all imports

**Dependency:** Phase 1 complete.

### File Map

| Action | Before | After |
|---|---|---|
| Move (promote) | `gcp/image/runtime/*.py` | `runtime/*.py` (root level of new package) |
| Move (promote) | `gcp/image/runtime/assets/` | `runtime/assets/` |
| Move | `gcp/image/config/` | `runtime/config/` |
| Move | `gcp/image/github/` | `runtime/github/` |
| Move | `gcp/image/schemas/` | `runtime/schemas/` |
| Move | `gcp/image/main.py` | `runtime/main.py` |
| Move | `gcp/image/Dockerfile` | `runtime/Dockerfile` |
| Move | `gcp/image/.dockerignore` | `runtime/.dockerignore` |
| Move (promote SDK helper) | `gcp/image/runtime/sdk/kardome.py` | `runtime/kardome.py` |
| Delete | `gcp/image/runtime/sdk/` | (re-export wrappers no longer needed after this rename) |
| Delete | `gcp/image/projects/` | vestigial |
| Delete | `gcp/__init__.py`, `gcp/README.md` | `gcp/` namespace gone |
| Rename pkg | `gcp/image/pyproject.toml` | `runtime/pyproject.toml` |
| Move | `gcp/stage/` | `plugins/` |
| Move | `.github/bmt/` | `ci/` |
| Rename dir | `ci/ci/` | `ci/kardome_bmt/` |
| Rename pkg | `ci/pyproject.toml` | package `bmt` → `kardome-bmt`, module `ci` → `kardome_bmt` |
| Modify | `pyproject.toml` | workspace members + sources |
| Modify | `runtime/pyproject.toml` | find rules + add `bmt-sdk` dep |
| Modify | `pyrightconfig.json` | extraPaths |
| Modify | `pyproject.toml` tool.ty | extra-paths + exclude |
| Modify | `ruff.toml` per-file-ignores | path patterns |
| Modify | `Justfile` | all `gcp/image` and `gcp/stage` refs |
| Modify | `CLAUDE.md` | all path references |
| Modify | `tests/support/fixtures/paths.py` | 3 fixture paths |
| Modify | 63 source files | `from gcp.image.*` → `from runtime.*` |
| Modify | 8 CI intra-package imports | `from ci import` → `from kardome_bmt import` |

---

### Task 2.1: Create `runtime/` with flattened structure

**Files:**
- Create: `runtime/__init__.py`
- Create: `runtime/pyproject.toml`
- Move (via git): all of `gcp/image/`

- [ ] **Step 1: Confirm baseline tests pass before touching anything**

```bash
uv run python -m pytest tests/ -q --tb=short
```

Expected: 297 passed (or current green count).

- [ ] **Step 2: Create `runtime/` with promoted structure using git mv**

```bash
# Promote gcp/image/runtime/ contents to new runtime/ root
git mv gcp/image runtime
# Now we have runtime/ which contains config/, github/, runtime/, main.py, etc.
# Promote the inner runtime/ contents up one level
cd runtime
git mv runtime/artifacts.py artifacts.py
git mv runtime/entrypoint.py entrypoint.py
git mv runtime/execution.py execution.py
git mv runtime/facade.py facade.py
git mv runtime/github_reporting.py github_reporting.py
git mv runtime/importer.py importer.py
git mv runtime/kardome_batch_results.py kardome_batch_results.py
git mv runtime/legacy_kardome.py legacy_kardome.py
git mv runtime/models.py models.py
git mv runtime/planning.py planning.py
git mv runtime/plugin_loader.py plugin_loader.py
git mv runtime/plugin_publisher.py plugin_publisher.py
git mv runtime/stdout_counter_parse.py stdout_counter_parse.py
git mv runtime/sdk/kardome.py kardome.py
git mv runtime/assets assets
git mv runtime/__init__.py __init__.py_inner
# Delete sdk/ re-export wrappers (now replaced by bmt_sdk direct)
rm -rf runtime/sdk
# Delete vestigial projects/
rm -rf runtime/projects
rm __init__.py_inner
cd ..
# Add a clean __init__.py for the new runtime package
echo '"""Cloud Run execution runtime."""' > runtime/__init__.py
```

Expected: `runtime/` contains `config/`, `github/`, `schemas/`, `assets/`, `models.py`, `planning.py`, etc. at root level.

- [ ] **Step 3: Update `runtime/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

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

[tool.uv]
package = true

[dependency-groups]
dev = []

[tool.setuptools.packages.find]
where = ["."]
include = ["runtime*"]
```

- [ ] **Step 4: Verify `runtime/` package shape**

```bash
ls runtime/
```

Expected: `__init__.py  artifacts.py  assets/  config/  entrypoint.py  execution.py  facade.py  github/  github_reporting.py  importer.py  kardome.py  kardome_batch_results.py  legacy_kardome.py  main.py  models.py  planning.py  plugin_loader.py  plugin_publisher.py  schemas/  stdout_counter_parse.py`

---

### Task 2.2: Move `gcp/stage/` → `plugins/` and clean `gcp/`

**Files:**
- Rename: `gcp/stage/` → `plugins/`
- Delete: `gcp/__init__.py`, `gcp/README.md`

- [ ] **Step 1: Rename staging area to plugins**

```bash
git mv gcp/stage plugins
```

- [ ] **Step 2: Delete gcp namespace remnants**

```bash
git rm gcp/__init__.py
git rm gcp/README.md
# Verify gcp/ is now empty
ls gcp/ 2>/dev/null && echo "gcp/ still has content" || echo "gcp/ gone"
```

Expected: `gcp/` gone.

- [ ] **Step 3: Update `tools/repo/paths.py` — rename stage constant and add plugins constant**

In `tools/repo/paths.py`, update `DEFAULT_STAGE_ROOT`:

```python
# Default roots for VM mirror and plugin space (relative to repo root).
DEFAULT_CONFIG_ROOT = Path("runtime")
DEFAULT_STAGE_ROOT = Path("plugins")   # renamed from gcp/stage
DEFAULT_RUNTIME_ROOT = DEFAULT_STAGE_ROOT  # legacy alias
```

And update `WorkspaceLayout.default()`:

```python
@classmethod
def default(cls) -> WorkspaceLayout:
    return cls(
        stage_root=Path("plugins"),
        image_root=Path("runtime"),
        mnt_root=Path("gcp/mnt"),
        data_root=Path("data"),
    )
```

- [ ] **Step 4: Update `tools/repo/gcp_layout_policy.py`**

Find the `ALLOWED_TOP_LEVEL` reference (now in `tools/shared/layout_patterns.py`) and update:

In `tools/shared/layout_patterns.py`:

```python
ALLOWED_TOP_LEVEL = {"README.md", "plugins", "runtime", "__init__.py"}
```

---

### Task 2.3: Move `.github/bmt/` → `ci/` and rename package

**Files:**
- Move: `.github/bmt/` → `ci/`
- Rename: `ci/ci/` → `ci/kardome_bmt/`
- Modify: `ci/pyproject.toml`
- Modify: all `ci/kardome_bmt/*.py` — `from ci import` → `from kardome_bmt import`

- [ ] **Step 1: Move CI package to repo root**

```bash
git mv .github/bmt ci
```

- [ ] **Step 2: Rename the Python package directory**

```bash
git mv ci/ci ci/kardome_bmt
```

- [ ] **Step 3: Update `ci/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "kardome-bmt"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
description = "Kardome BMT CI driver: matrix discovery, Cloud Run handoff, and runner upload."
dependencies = [
    "bmt-gcloud",
    "google-cloud-compute>=1.45",
    "google-cloud-storage>=2.16",
    "PyGithub>=2.0",
    "pydantic>=2.12.5",
    "typer>=0.15.0",
]

[tool.uv]
package = true

[project.scripts]
kardome-bmt = "kardome_bmt.driver:main"
kardome-bmt-matrix = "kardome_bmt.driver:main_matrix"
kardome-bmt-write-context = "kardome_bmt.driver:main_write_context"
kardome-bmt-write-summary = "kardome_bmt.driver:main_write_handoff_summary"

[tool.setuptools.packages.find]
where = ["."]
include = ["kardome_bmt*"]
```

- [ ] **Step 4: Update intra-package imports in all 8 CI files**

Replace all `from ci import` with `from kardome_bmt import` in these files:
- `ci/kardome_bmt/__init__.py`
- `ci/kardome_bmt/driver.py`
- `ci/kardome_bmt/handoff.py`
- `ci/kardome_bmt/handoff_dataset.py`
- `ci/kardome_bmt/matrix.py`
- `ci/kardome_bmt/runner.py`
- `ci/kardome_bmt/runner_provenance.py`
- `ci/kardome_bmt/workflow_dispatch.py`

In each file, run:

```bash
sd 'from ci import' 'from kardome_bmt import' ci/kardome_bmt/*.py
```

- [ ] **Step 5: Update `ci/kardome_bmt/__init__.py`**

```python
"""Kardome BMT CI driver: matrix, trigger, Cloud Run handoff, runner upload."""

from __future__ import annotations

__all__ = [
    "get_config",
    "get_context",
]

from kardome_bmt import config

get_config = config.get_config
get_context = config.get_context
```

---

### Task 2.4: Update root `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update workspace, sources, and tool.ty paths**

```toml
[project]
name = "bmt-gcloud"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    "kardome-bmt",
    "bmt-sdk",
    "PyGithub>=2.0",
    "google-cloud-storage>=2.16",
    "google-cloud-artifact-registry>=1.14.0",
    "orjson>=3.10",
    "prek>=0.3.5",
    "pulumi-gcp>=9.15.0",
    "pydantic>=2.12.5",
    "pydantic-settings>=2.0.0",
    "requests>=2.31.0",
    "rich>=13.0",
    "typer>=0.15.0",
    "whenever>=0.9.5",
    "google-auth-stubs>=0.3.0",
]

[tool.uv.sources]
kardome-bmt = { workspace = true }
bmt-sdk = { workspace = true }
bmt-gcloud = { workspace = true }

[tool.uv.workspace]
members = ["ci", "runtime", "sdk"]

[tool.uv]
package = true

[tool.setuptools.packages.find]
where = ["."]
include = ["tools*"]

[tool.ty.environment]
python-version = "3.12"
extra-paths = [
    "ci",
    "plugins/sk/plugin_workspaces/default/src",
]

[tool.ty.src]
exclude = [
    "data",
    "sk_runtime",
    "local_batch",
    "secrets",
    "plugins",
]
```

- [ ] **Step 2: Run `uv sync` to rebuild lockfile**

```bash
uv sync
```

Expected: lockfile updated, no errors.

---

### Task 2.5: Update all `from gcp.image.*` imports (63 files)

**Files:** All 63 files that import from `gcp.image.*` (see Import Mappings table above).

Use `sd` for bulk replacements:

- [ ] **Step 1: Replace `from gcp.image.runtime.sdk.plugin import BmtPlugin` → `from bmt_sdk import BmtPlugin`**

```bash
sd 'from gcp\.image\.runtime\.sdk\.plugin import BmtPlugin' 'from bmt_sdk import BmtPlugin' \
  $(grep -rl 'from gcp.image.runtime.sdk.plugin' . --include="*.py" | grep -v __pycache__ | grep -v .worktrees)
```

- [ ] **Step 2: Replace `from gcp.image.runtime.sdk.context import ExecutionContext` → `from bmt_sdk import ExecutionContext`**

```bash
sd 'from gcp\.image\.runtime\.sdk\.context import ExecutionContext' 'from bmt_sdk import ExecutionContext' \
  $(grep -rl 'from gcp.image.runtime.sdk.context' . --include="*.py" | grep -v __pycache__ | grep -v .worktrees)
```

- [ ] **Step 3: Replace `from gcp.image.runtime.sdk.results import` → `from bmt_sdk.results import`**

```bash
sd 'from gcp\.image\.runtime\.sdk\.results import' 'from bmt_sdk.results import' \
  $(grep -rl 'from gcp.image.runtime.sdk.results' . --include="*.py" | grep -v __pycache__ | grep -v .worktrees)
```

- [ ] **Step 4: Replace `from gcp.image.runtime.sdk.kardome import` → `from runtime.kardome import`**

```bash
sd 'from gcp\.image\.runtime\.sdk\.kardome import' 'from runtime.kardome import' \
  $(grep -rl 'from gcp.image.runtime.sdk.kardome' . --include="*.py" | grep -v __pycache__ | grep -v .worktrees)
```

- [ ] **Step 5: Replace all remaining `from gcp.image.runtime.` → `from runtime.`**

```bash
sd 'from gcp\.image\.runtime\.' 'from runtime.' \
  $(grep -rl 'from gcp.image.runtime\.' . --include="*.py" | grep -v __pycache__ | grep -v .worktrees)
```

- [ ] **Step 6: Replace all `from gcp.image.config.` → `from runtime.config.`**

```bash
sd 'from gcp\.image\.config\.' 'from runtime.config.' \
  $(grep -rl 'from gcp.image.config\.' . --include="*.py" | grep -v __pycache__ | grep -v .worktrees)
```

- [ ] **Step 7: Replace all `from gcp.image.github.` → `from runtime.github.`**

```bash
sd 'from gcp\.image\.github\.' 'from runtime.github.' \
  $(grep -rl 'from gcp.image.github\.' . --include="*.py" | grep -v __pycache__ | grep -v .worktrees)
```

- [ ] **Step 8: Replace any remaining `gcp.image` references**

```bash
grep -rn 'gcp\.image\|gcp/image' . --include="*.py" --include="*.toml" --include="*.json" \
  | grep -v __pycache__ | grep -v .worktrees | grep -v ".github-release"
```

Expected: zero results (or only in docs/comments, which are fine).

---

### Task 2.6: Update test fixtures and config files

**Files:**
- Modify: `tests/support/fixtures/paths.py`
- Modify: `pyrightconfig.json`
- Modify: `ruff.toml`

- [ ] **Step 1: Update `tests/support/fixtures/paths.py`**

```python
"""Shared pytest path fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return _ROOT


@pytest.fixture(scope="session")
def runtime_root(repo_root: Path) -> Path:
    """Cloud Run execution runtime package root."""
    path = repo_root / "runtime"
    assert path.exists(), f"Expected runtime root to exist: {path}"
    return path


# Keep old name as alias so tests that use gcp_code_root don't break until updated.
@pytest.fixture(scope="session")
def gcp_code_root(runtime_root: Path) -> Path:
    return runtime_root


@pytest.fixture(scope="session")
def ci_root(repo_root: Path) -> Path:
    path = repo_root / "ci"
    assert path.exists(), f"Expected ci root to exist: {path}"
    return path


# Keep old name as alias.
@pytest.fixture(scope="session")
def github_bmt_root(ci_root: Path) -> Path:
    return ci_root


@pytest.fixture(scope="session")
def plugins_root(repo_root: Path) -> Path:
    path = repo_root / "plugins"
    assert path.exists(), f"Expected plugins root to exist: {path}"
    return path


# Keep old name as alias.
@pytest.fixture(scope="session")
def repo_stage_root(plugins_root: Path) -> Path:
    return plugins_root
```

- [ ] **Step 2: Update `pyrightconfig.json`**

```json
{
    "pythonVersion": "3.12",
    "typeCheckingMode": "standard",
    "include": ["."],
    "exclude": [
        "**/__pycache__",
        "**/.ruff_cache",
        "**/.mypy_cache",
        "build",
        "dist",
        "data",
        "sk_runtime",
        "local_batch",
        "secrets",
        ".venv",
        "node_modules"
    ],
    "extraPaths": [
        "ci",
        "plugins/sk/plugin_workspaces/default/src"
    ],
    "executionEnvironments": [
        {
            "root": ".",
            "extraPaths": [
                "ci",
                "plugins/sk/plugin_workspaces/default/src"
            ]
        }
    ],
    "venvPath": ".",
    "venv": ".venv",
    "reportMissingTypeStubs": "none",
    "reportGeneralTypeIssues": "error",
    "reportUnusedImport": "warning",
    "reportUnusedVariable": "warning",
    "reportUnusedCallResult": "none",
    "reportPrivateUsage": "warning",
    "reportExplicitAny": false,
    "reportAny": false,
    "reportUnknownMemberType": false,
    "reportUnknownVariableType": false,
    "reportUnknownArgumentType": false,
    "reportUnknownParameterType": false
}
```

- [ ] **Step 3: Update `ruff.toml` per-file-ignores paths**

Replace `gcp/image/**` with `runtime/**` and `.github/bmt/**` with `ci/**`:

```toml
[lint.per-file-ignores]
"scripts/**" = ["T20", "C901"]
"infra/pulumi/**" = ["S106"]
"runtime/**" = ["PLC0415"]
"tests/**" = [
    "S101", "PLR2004", "PLR0913", "T20", "ARG001", "RUF059",
    "PLC0415", "FBT001", "FBT002", "F401", "S108", "S110",
    "B007", "B017", "PT011", "PT018", "SLF001",
]
"tools/**" = [
    "ERA001", "T20", "E402", "PLC0415", "PLR0911", "PLR0912",
    "PLR0915", "C901", "G004", "TC003", "FBT001", "FBT002",
    "TRY004", "ARG001", "SIM117",
]
"runtime/vm_watcher.py" = [
    "C901", "PLR0911", "PLR0912", "PLR0915", "S110",
]
"ci/**" = [
    "T20", "ARG001", "PLC0415", "I001", "C901", "PLR0912", "PLR0915",
]
"deploy/**" = [
    "T20", "ARG001", "FBT001", "FBT002", "S108", "C901",
    "PLR0912", "PLR0915", "PLW0603",
]
```

---

### Task 2.7: Update Justfile and CLAUDE.md

**Files:**
- Modify: `Justfile`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Global replace in Justfile**

```bash
sd 'gcp/image' 'runtime' Justfile
sd 'gcp/stage' 'plugins' Justfile
sd '\.github/bmt' 'ci' Justfile
sd 'uv run bmt ' 'uv run kardome-bmt ' Justfile
```

- [ ] **Step 2: Update CLAUDE.md**

Replace all occurrences of `gcp/image` → `runtime`, `gcp/stage` → `plugins`, `.github/bmt` → `ci`, `uv run bmt` → `uv run kardome-bmt` throughout `CLAUDE.md`.

---

### Task 2.8: Run full test suite and commit Phase 2

- [ ] **Step 1: Run tests**

```bash
uv run python -m pytest tests/ -q --tb=short
```

Expected: same pass count as Phase 1 gate.

- [ ] **Step 2: Run linter**

```bash
uv run ruff check . && uv run ruff format --check .
```

Expected: clean.

- [ ] **Step 3: Verify no remaining `gcp.image` or `gcp/image` references in Python source**

```bash
grep -rn 'gcp\.image\|gcp/image\|gcp/stage\|\.github/bmt' \
  --include="*.py" --include="*.toml" \
  . | grep -v __pycache__ | grep -v .worktrees | grep -v ".github-release" | grep -v "docs/"
```

Expected: zero results.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(structure): rename gcp/ → runtime/plugins/, move .github/bmt/ → ci/, rename package bmt → kardome-bmt"
```

---

## Phase 3: Direct plugin loading (keep `published:` fallback)

**Dependency:** Phase 2 complete.

### Goal

`runtime/plugin_loader.py` currently loads plugins via `published:name:sha256-*` directory bundles. After this phase, it loads `plugin.py` directly from the project directory by convention — no `published:` indirection, no `PluginManifest`, no publish step required. The `published:` fallback stays for backward compat during Phase 3 (removed in Phase 5).

### File Map

| File | Action |
|---|---|
| `runtime/plugin_loader.py` | Rewrite — direct `importlib` loading + published fallback |
| `runtime/models.py` | Modify — `BmtManifest.plugin_ref` becomes optional (defaults to `"direct"`) |
| `tests/bmt/test_plugin_loader_direct.py` | Create — tests for direct loading |

---

### Task 3.1: Write tests for direct loading

**Files:**
- Create: `tests/bmt/test_plugin_loader_direct.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for direct plugin loading from plugin.py convention."""

from __future__ import annotations

from pathlib import Path

import pytest

from bmt_sdk import BmtPlugin
from bmt_sdk.context import ExecutionContext
from bmt_sdk.models import BmtManifestView, ProjectManifestView
from bmt_sdk.results import ExecutionResult, PreparedAssets, ScoreResult, VerdictResult
from runtime.plugin_loader import load_plugin_direct

pytestmark = pytest.mark.unit


def _write_plugin(project_dir: Path) -> None:
    plugin_py = project_dir / "plugin.py"
    plugin_py.write_text(
        """\
from bmt_sdk import BmtPlugin
from bmt_sdk.context import ExecutionContext
from bmt_sdk.results import ExecutionResult, PreparedAssets, ScoreResult, VerdictResult


class TestPlugin(BmtPlugin):
    def prepare(self, context: ExecutionContext) -> PreparedAssets:
        return PreparedAssets(dataset_root=context.dataset_root, workspace_root=context.workspace_root)

    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        return ExecutionResult(execution_mode_used="test", case_results=[])

    def score(self, execution_result: ExecutionResult, baseline: ScoreResult | None, context: ExecutionContext) -> ScoreResult:
        return ScoreResult(aggregate_score=1.0)

    def evaluate(self, score_result: ScoreResult, baseline: ScoreResult | None, context: ExecutionContext) -> VerdictResult:
        return VerdictResult(passed=True, status="pass", reason_code="ok")
""",
        encoding="utf-8",
    )


def test_load_plugin_direct_returns_bmt_plugin(tmp_path: Path) -> None:
    project_dir = tmp_path / "plugins" / "acme"
    project_dir.mkdir(parents=True)
    _write_plugin(project_dir)

    plugin, root = load_plugin_direct(project_dir)

    assert isinstance(plugin, BmtPlugin)
    assert root == project_dir


def test_load_plugin_direct_raises_if_no_plugin_py(tmp_path: Path) -> None:
    project_dir = tmp_path / "plugins" / "empty"
    project_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="plugin.py"):
        load_plugin_direct(project_dir)


def test_load_plugin_direct_raises_on_zero_subclasses(tmp_path: Path) -> None:
    project_dir = tmp_path / "plugins" / "noplugin"
    project_dir.mkdir(parents=True)
    (project_dir / "plugin.py").write_text("# no BmtPlugin subclass\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="exactly one BmtPlugin subclass"):
        load_plugin_direct(project_dir)


def test_load_plugin_direct_raises_on_multiple_subclasses(tmp_path: Path) -> None:
    project_dir = tmp_path / "plugins" / "multi"
    project_dir.mkdir(parents=True)
    (project_dir / "plugin.py").write_text(
        """\
from bmt_sdk import BmtPlugin
from bmt_sdk.context import ExecutionContext
from bmt_sdk.results import ExecutionResult, PreparedAssets, ScoreResult, VerdictResult

class PluginA(BmtPlugin):
    def prepare(self, c): return PreparedAssets(dataset_root=c.dataset_root, workspace_root=c.workspace_root)
    def execute(self, c, p): return ExecutionResult(execution_mode_used="test", case_results=[])
    def score(self, r, b, c): return ScoreResult(aggregate_score=1.0)
    def evaluate(self, s, b, c): return VerdictResult(passed=True, status="pass", reason_code="ok")

class PluginB(PluginA):
    pass
""",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="exactly one BmtPlugin subclass"):
        load_plugin_direct(project_dir)


def test_sibling_module_importable(tmp_path: Path) -> None:
    project_dir = tmp_path / "plugins" / "withhelper"
    project_dir.mkdir(parents=True)
    (project_dir / "helpers.py").write_text("HELPER_VALUE = 42\n", encoding="utf-8")
    (project_dir / "plugin.py").write_text(
        """\
from bmt_sdk import BmtPlugin
from bmt_sdk.context import ExecutionContext
from bmt_sdk.results import ExecutionResult, PreparedAssets, ScoreResult, VerdictResult
from helpers import HELPER_VALUE

class MyPlugin(BmtPlugin):
    value = HELPER_VALUE
    def prepare(self, c): return PreparedAssets(dataset_root=c.dataset_root, workspace_root=c.workspace_root)
    def execute(self, c, p): return ExecutionResult(execution_mode_used="test", case_results=[])
    def score(self, r, b, c): return ScoreResult(aggregate_score=1.0)
    def evaluate(self, s, b, c): return VerdictResult(passed=True, status="pass", reason_code="ok")
""",
        encoding="utf-8",
    )

    plugin, _ = load_plugin_direct(project_dir)
    assert plugin.value == 42  # type: ignore[attr-defined]
```

- [ ] **Step 2: Run to verify they fail (function not yet implemented)**

```bash
uv run python -m pytest tests/bmt/test_plugin_loader_direct.py -v
```

Expected: `ImportError: cannot import name 'load_plugin_direct' from 'runtime.plugin_loader'`

---

### Task 3.2: Implement `load_plugin_direct` in `runtime/plugin_loader.py`

**Files:**
- Modify: `runtime/plugin_loader.py`

- [ ] **Step 1: Add `load_plugin_direct` to `runtime/plugin_loader.py`**

Append to the existing file (do not remove `load_plugin` — it's the published fallback):

```python
import importlib.util
import sys


def load_plugin_direct(project_dir: Path) -> tuple[BmtPlugin, Path]:
    """Load a BmtPlugin subclass from <project_dir>/plugin.py by convention.

    Adds project_dir to sys.path so sibling modules (helpers.py, etc.) are importable.
    Returns (plugin_instance, project_dir).

    Raises:
        FileNotFoundError: if plugin.py does not exist.
        RuntimeError: if plugin.py does not contain exactly one BmtPlugin subclass.
    """
    plugin_py = project_dir / "plugin.py"
    if not plugin_py.is_file():
        raise FileNotFoundError(f"Expected plugin.py at {plugin_py}")

    module_name = f"bmt_plugin_{project_dir.name}_{id(project_dir)}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create module spec for {plugin_py}")

    # Add project_dir to sys.path so sibling .py files are importable.
    path_str = str(project_dir)
    added = path_str not in sys.path
    if added:
        sys.path.insert(0, path_str)
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    finally:
        if added and path_str in sys.path:
            sys.path.remove(path_str)

    candidates = [
        cls
        for cls in vars(module).values()
        if isinstance(cls, type) and issubclass(cls, BmtPlugin) and cls is not BmtPlugin
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"plugins/{project_dir.name}/plugin.py must define exactly one BmtPlugin subclass, "
            f"found {len(candidates)}: {[c.__name__ for c in candidates]}"
        )
    return candidates[0](), project_dir
```

- [ ] **Step 2: Run tests**

```bash
uv run python -m pytest tests/bmt/test_plugin_loader_direct.py -v
```

Expected: 5 tests pass.

- [ ] **Step 3: Update `load_plugin` to try direct first, fall back to published**

In `runtime/plugin_loader.py`, update `load_plugin` signature to also accept `"direct"` as a `plugin_ref`:

```python
def load_plugin(
    stage_root: Path,
    project: str,
    plugin_ref: str,
    *,
    allow_workspace: bool = True,
) -> tuple[BmtPlugin, Path]:
    """Load a plugin by plugin_ref.

    Supported refs:
      "direct"            — load plugin.py directly from plugins/<project>/
      "workspace:<name>"  — load from plugin_workspaces/<name>/src/ (dev only)
      "published:<name>:<digest>" — load from immutable published bundle

    For new projects, "direct" is always correct. "published:" is a backward-compat
    fallback for legacy bundles and is removed in Phase 5.
    """
    if plugin_ref == "direct" or not plugin_ref:
        project_dir = stage_root / "projects" / project  # Phase 2: still projects/
        return load_plugin_direct(project_dir)
    # ... existing workspace/published handling unchanged ...
```

- [ ] **Step 4: Run full test suite**

```bash
uv run python -m pytest tests/ -q --tb=short
```

Expected: same pass count as Phase 2 gate.

- [ ] **Step 5: Commit**

```bash
git add runtime/plugin_loader.py tests/bmt/test_plugin_loader_direct.py
git commit -m "feat(runtime): add direct plugin loading from plugin.py convention; keep published: fallback"
```

---

## Phase 4: Flatten `plugins/sk/` contributor structure

**Dependency:** Phase 3 complete.

### Goal

Move the SK plugin from `plugins/sk/plugin_workspaces/default/src/sk_plugin/` to `plugins/sk/` (flat). Flatten BMT configs from `bmts/slug/bmt.json` to `slug.json` at project root. Remove the published bundle indirection. Update bucket path references from `projects/sk/` to `plugins/sk/`.

### File Map

| Action | Before | After |
|---|---|---|
| Move | `plugins/sk/plugin_workspaces/default/src/sk_plugin/plugin.py` | `plugins/sk/plugin.py` |
| Move | `plugins/sk/plugin_workspaces/default/src/sk_plugin/sk_scoring_policy.py` | `plugins/sk/sk_scoring_policy.py` |
| Move | `plugins/sk/bmts/false_alarms/bmt.json` | `plugins/sk/false_alarms.json` |
| Move | `plugins/sk/bmts/false_rejects/bmt.json` | `plugins/sk/false_rejects.json` |
| Delete | `plugins/sk/plugin_workspaces/` | replaced by flat plugin.py |
| Delete | `plugins/sk/plugins/default/sha256-*/` | replaced by direct loading |
| Delete | `plugins/sk/bmts/` | replaced by flat json files |
| Delete | `plugins/sk/runner_bundle/` | `runner` binary stays, dir removed |
| Delete | `plugins/sk/kardome_runner`, `plugins/sk/mock_kardome_runner` | duplicates |
| Delete | `plugins/sk/runner_latest_meta.json` | operational noise |
| Modify | `plugins/sk/false_alarms.json` | strip derived fields, set `plugin_ref: "direct"` |
| Modify | `plugins/sk/false_rejects.json` | same |
| Modify | `plugins/sk/project.json` | add `plugin_digest` field |
| Modify | `runtime/models.py` | derive fields in `BmtManifest` loader |
| Modify | `runtime/planning.py` | update discovery path `bmts/*/bmt.json` → `*.json` |
| Modify | `runtime/plugin_loader.py` | update `"direct"` ref to use `plugins/<project>/` |
| Modify | `tools/shared/bucket_env.py` + others | bucket path refs `projects/` → `plugins/` |

---

### Task 4.1: Flatten SK plugin source

- [ ] **Step 1: Move plugin source files**

```bash
git mv plugins/sk/plugin_workspaces/default/src/sk_plugin/plugin.py plugins/sk/plugin.py
git mv plugins/sk/plugin_workspaces/default/src/sk_plugin/sk_scoring_policy.py plugins/sk/sk_scoring_policy.py
```

- [ ] **Step 2: Update imports in `plugins/sk/plugin.py`**

The plugin previously imported `from sk_plugin.sk_scoring_policy import ...`. Now it's a sibling file:

```python
# Before:
from sk_plugin.sk_scoring_policy import aggregate_mean_ok_cases, build_case_outcomes, scoring_policy_record

# After:
from sk_scoring_policy import aggregate_mean_ok_cases, build_case_outcomes, scoring_policy_record
```

Also update the class name and imports for readability. The `bmt_sdk` imports stay unchanged.

- [ ] **Step 3: Remove plugin_workspaces and published bundles**

```bash
git rm -rf plugins/sk/plugin_workspaces
git rm -rf plugins/sk/plugins
```

- [ ] **Step 4: Verify plugin loads directly**

```bash
uv run python -c "
from pathlib import Path
from runtime.plugin_loader import load_plugin_direct
plugin, root = load_plugin_direct(Path('plugins/sk'))
print('loaded:', type(plugin).__name__, 'from', root)
"
```

Expected: `loaded: SkPlugin from plugins/sk` (or whatever the class is named).

---

### Task 4.2: Flatten BMT configs

- [ ] **Step 1: Move and simplify false_alarms.json**

```bash
git mv plugins/sk/bmts/false_alarms/bmt.json plugins/sk/false_alarms.json
```

Rewrite `plugins/sk/false_alarms.json` to stripped form (only meaningful fields):

```json
{
  "bmt_id": "ac73397e-1162-5004-9ca2-17c969f53ee5",
  "enabled": true,
  "plugin_config": {
    "comparison": "lte",
    "tolerance_abs": 0.25,
    "keyword": "NAMUH",
    "counter_pattern": "Hi NAMUH counter = (\\d+)",
    "num_source_test": 0,
    "enable_overrides": {
      "KWS_CONFIG.KWS_ENABLE": true,
      "BIOMETRICS_CONFIG.BIO_ENABLE": false
    },
    "reporting_hints": {
      "utterances_per_file": 100,
      "dataset_note": "Per-file keyword recognition style; aggregate is the average of per-file counters over passing cases.",
      "metric_short_label": "false alarms per file (avg.)",
      "success_in_words": "Lower is better: **0** means no false keyword detections on average across passing test files. Do not compare this number to false_rejects rows (different metric and direction)."
    }
  }
}
```

- [ ] **Step 2: Move and simplify false_rejects.json**

```bash
git mv plugins/sk/bmts/false_rejects/bmt.json plugins/sk/false_rejects.json
```

Rewrite `plugins/sk/false_rejects.json`:

```json
{
  "bmt_id": "4a5b6e82-a048-5c96-8734-2f64d2288378",
  "enabled": true,
  "plugin_config": {
    "comparison": "gte",
    "tolerance_abs": 0.25,
    "keyword": "NAMUH",
    "counter_pattern": "Hi NAMUH counter = (\\d+)",
    "num_source_test": 0,
    "enable_overrides": {
      "KWS_CONFIG.KWS_ENABLE": true,
      "BIOMETRICS_CONFIG.BIO_ENABLE": false
    },
    "reporting_hints": {
      "utterances_per_file": 100,
      "dataset_note": "Per-file keyword recognition style; aggregate is the average of per-file counters over passing cases.",
      "metric_short_label": "keyword hits per file (avg.)",
      "success_in_words": "Higher is better: counts keyword hits per test file vs your baseline; a larger average means stronger recognition. Do not compare this row to false_alarms (different metric and direction)."
    }
  }
}
```

- [ ] **Step 3: Remove bmts/ directory**

```bash
git rm -rf plugins/sk/bmts
```

---

### Task 4.3: Update `BmtManifest` model and planning discovery

**Files:**
- Modify: `runtime/models.py`
- Modify: `runtime/planning.py`

- [ ] **Step 1: Update `BmtManifest` to derive fields from path context**

Add a class method `from_flat_file` that takes the file path and derives `project`, `bmt_slug`, and GCS prefix fields:

In `runtime/models.py`, add:

```python
@classmethod
def from_flat_file(cls, path: Path) -> BmtManifest:
    """Load a flat BMT config (plugins/sk/false_alarms.json) and derive all path fields."""
    # path = plugins/sk/false_alarms.json
    # project = sk (parent dir name)
    # bmt_slug = false_alarms (stem)
    project = path.parent.name
    bmt_slug = path.stem
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("schema_version", 1)
    data.setdefault("project", project)
    data.setdefault("bmt_slug", bmt_slug)
    data.setdefault("plugin_ref", "direct")
    data.setdefault("inputs_prefix", f"plugins/{project}/inputs/{bmt_slug}")
    data.setdefault("results_prefix", f"plugins/{project}/results/{bmt_slug}")
    data.setdefault("outputs_prefix", f"plugins/{project}/outputs/{bmt_slug}")
    data.setdefault("runner", {"uri": f"plugins/{project}/runner", "deps_prefix": "plugins/shared/dependencies"})
    return cls.model_validate(data)
```

- [ ] **Step 2: Update `runtime/planning.py` to discover flat `*.json` files**

Find the glob pattern that discovers BMT manifests (currently `projects/*/bmts/*/bmt.json`). Change it to:

```python
# Before:
for path in sorted(stage_root.glob("projects/*/bmts/*/bmt.json")):

# After (supports both old and new layout during transition):
manifests: list[Path] = []
for path in sorted(stage_root.glob("projects/*/bmts/*/bmt.json")):
    manifests.append(path)
for path in sorted(stage_root.glob("plugins/*/*[!project].json")):
    # Flat layout: plugins/sk/false_alarms.json (exclude project.json)
    if path.name != "project.json":
        manifests.append(path)
```

And use `BmtManifest.from_flat_file(path)` when loading flat layout files.

- [ ] **Step 3: Update `plugins/sk/project.json` with plugin_digest**

```bash
uv run python -c "
from pathlib import Path
from runtime.plugin_publisher import plugin_digest
d = plugin_digest(Path('plugins/sk'))
print('digest:', d)
"
```

Then update `plugins/sk/project.json`:

```json
{
  "schema_version": 1,
  "project": "sk",
  "description": "Keyword spotting false-alarm and false-reject BMTs",
  "plugin_digest": "<output from above command>"
}
```

---

### Task 4.4: Update GCS bucket path references

**Files:** `tools/shared/trigger_uris.py`, `runtime/models.py` defaults, any hardcoded `projects/sk/` in tools.

- [ ] **Step 1: Find all hardcoded `projects/` GCS path prefixes**

```bash
grep -rn '"projects/' . --include="*.py" --include="*.json" \
  | grep -v __pycache__ | grep -v .worktrees | grep -v ".github-release" | grep -v tests/
```

- [ ] **Step 2: Update `runtime/models.py` RunnerConfig default template path**

```python
class RunnerConfig(BaseModel):
    uri: str = ""
    deps_prefix: str = ""
    template_path: str = "runtime/assets/kardome_input_template.json"
```

- [ ] **Step 3: Update `tools/shared/trigger_uris.py` if it references `projects/` GCS paths**

For any hardcoded `projects/<project>/` bucket paths, add `plugins/<project>/` as the new canonical form.

- [ ] **Step 4: Run tests**

```bash
uv run python -m pytest tests/ -q --tb=short
```

Expected: same pass count.

- [ ] **Step 5: Commit Phase 4**

```bash
git add plugins/sk/ runtime/models.py runtime/planning.py
git commit -m "feat(plugins): flatten sk plugin structure — plugin.py at project root, flat BMT configs, direct loading"
```

---

## Phase 5: Drop backward compat and delete dead directories

**Dependency:** Phase 4 complete + CI verified end-to-end.

### Task 5.1: Remove `published:` fallback from plugin loader

**Files:**
- Modify: `runtime/plugin_loader.py`
- Modify: `runtime/plugin_publisher.py` — keep for historical reference but mark deprecated

- [ ] **Step 1: Remove `workspace:` and `published:` handling from `load_plugin`**

In `runtime/plugin_loader.py`, simplify `load_plugin` to only call `load_plugin_direct`:

```python
def load_plugin(
    stage_root: Path,
    project: str,
    plugin_ref: str = "direct",
    *,
    allow_workspace: bool = True,
) -> tuple[BmtPlugin, Path]:
    """Load a BmtPlugin from plugins/<project>/plugin.py.

    plugin_ref is accepted for API compatibility but ignored — all plugins
    load directly from plugin.py by convention.
    """
    project_dir = stage_root / "plugins" / project
    return load_plugin_direct(project_dir)
```

- [ ] **Step 2: Delete `PluginManifest` from `runtime/models.py`** (if no remaining references)

```bash
grep -rn 'PluginManifest' . --include="*.py" | grep -v __pycache__ | grep -v .worktrees
```

If only `runtime/models.py` and legacy tests reference it, remove it.

---

### Task 5.2: Delete dead directories and files

- [ ] **Step 1: Delete `tests/vm/`**

```bash
git rm -rf tests/vm/
```

- [ ] **Step 2: Remove old `gcp/image/runtime/sdk/` re-export files** (already done in Phase 2 but verify)

```bash
ls runtime/ | grep sdk  # should be nothing
```

- [ ] **Step 3: Clean up `plugins/sk/` of any remaining transitional artifacts**

```bash
ls plugins/sk/
```

Expected: `false_alarms.json  false_rejects.json  inputs/  outputs/  plugin.py  project.json  results/  runner  shared/  sk_scoring_policy.py`

Not expected: `bmts/  kardome_runner  mock_kardome_runner  plugin_workspaces/  plugins/  runner_bundle/  runner_latest_meta.json`

- [ ] **Step 4: Update tests that referenced old paths**

Run tests and fix any fixture references to old paths:

```bash
uv run python -m pytest tests/ -q --tb=short
```

Fix any remaining failures from path changes.

- [ ] **Step 5: Update `tests/bmt/test_stage_bmt_manifests.py`**

The manifest discovery test currently scans `projects/*/bmts/*/bmt.json`. Update it to scan `plugins/*/*[!project].json`:

```python
def _discover_stage_bmt_manifests(plugins_root: Path) -> list[StageBmtRecord]:
    if not plugins_root.is_dir():
        return []
    out: list[StageBmtRecord] = []
    for path in sorted(plugins_root.glob("*/*.json")):
        if path.name == "project.json":
            continue
        rel = path.relative_to(plugins_root).as_posix()
        out.append(StageBmtRecord(manifest_path=path, id_posix=rel))
    return out
```

- [ ] **Step 6: Final lint and type check**

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check
```

Expected: clean.

- [ ] **Step 7: Commit Phase 5**

```bash
git add -A
git commit -m "feat(cleanup): drop published: fallback, delete dead directories, tests/vm — Phase 5 complete"
```

---

## Final verification

```bash
uv run python -m pytest tests/ -v
```

Success criteria:
- `from bmt_sdk import BmtPlugin` works with no `runtime` installed
- `git ls-files plugins/sk/` shows ≤ 8 files
- No `gcp/` directory: `ls gcp/ 2>/dev/null && echo "FAIL: gcp/ still exists" || echo "ok"`
- All tests pass

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Extract `sdk/` | Phase 1 (existing plan) |
| `gcp/image/` → `runtime/` | Task 2.1 |
| `gcp/stage/` → `plugins/` | Task 2.2 |
| `.github/bmt/` → `ci/` | Task 2.3 |
| `bmt` → `kardome-bmt` package | Task 2.3 |
| `ci` → `kardome_bmt` module | Task 2.3 |
| Update 63 files importing `gcp.image.*` | Task 2.5 |
| Delete `gcp/image/projects/`, `gcp/__init__.py` | Task 2.2 |
| Update workspace pyproject.toml | Task 2.4 |
| Direct plugin loading via importlib | Task 3.2 |
| Keep `published:` fallback in Phase 3 | Task 3.2 |
| Flatten `plugins/sk/` — plugin.py at root | Task 4.1 |
| Flat BMT configs `slug.json` | Task 4.2 |
| Derived manifest fields | Task 4.3 |
| plugin_digest in project.json | Task 4.3 |
| Bucket paths `projects/` → `plugins/` | Task 4.4 |
| Drop `published:` fallback | Task 5.1 |
| Delete `tests/vm/` | Task 5.2 |
| No `gcp/` directory exists | Task 5.2 |
