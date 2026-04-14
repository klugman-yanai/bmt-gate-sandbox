"""Tests for direct plugin loading from plugin.py convention."""

from __future__ import annotations

from pathlib import Path

import pytest

from bmt_sdk import BmtPlugin
from bmt_sdk.context import ExecutionContext
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
