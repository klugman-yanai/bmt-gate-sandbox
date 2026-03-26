"""Tests for :class:`gcp.image.runtime.sdk.plugin.BmtPlugin` framework helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from backend.runtime.models import PluginManifest
from backend.runtime.plugin_errors import PluginLoadError
from backend.runtime.sdk.plugin import PLUGIN_EXECUTE_EXCEPTION_RAW_KEY, BmtPlugin
from backend.runtime.sdk.results import PreparedAssets
from tests.support.fixtures.bmt_sdk import minimal_execution_context

pytestmark = pytest.mark.unit

_SK_PLUGIN_SRC = str(Path(__file__).resolve().parents[2] / "gcp/stage/projects/sk/plugin_workspaces/default/src")


def _sk_plugin():
    if _SK_PLUGIN_SRC not in sys.path:
        sys.path.insert(0, _SK_PLUGIN_SRC)
    from sk_plugin.plugin import SkPlugin

    return SkPlugin()


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pass_threshold: float = 1.0


class _TrivialPlugin(BmtPlugin):
    plugin_name = "trivial"
    api_version = "v1"

    def prepare(self, context):
        return self.prepared_assets_from_context(context)

    def execute(self, context, prepared_assets):
        raise NotImplementedError

    def score(self, execution_result, baseline, context):
        raise NotImplementedError

    def evaluate(self, score_result, baseline, context):
        raise NotImplementedError


class _V2Plugin(_TrivialPlugin):
    plugin_name = "x"
    api_version = "v2"


def test_validate_against_loaded_manifest_ok() -> None:
    manifest = PluginManifest(
        plugin_name="default",
        entrypoint="sk_plugin:SkPlugin",
    )
    _sk_plugin().validate_against_loaded_manifest(manifest)


def test_validate_against_loaded_manifest_plugin_name_mismatch() -> None:
    manifest = PluginManifest(
        plugin_name="wrong",
        entrypoint="sk_plugin:SkPlugin",
    )
    with pytest.raises(PluginLoadError, match="plugin_name"):
        _sk_plugin().validate_against_loaded_manifest(manifest)


def test_validate_rejects_unsupported_api_version() -> None:
    manifest = PluginManifest(plugin_name="x", entrypoint="x:X", api_version="v2")
    with pytest.raises(PluginLoadError, match="supports plugin api_version"):
        _V2Plugin().validate_against_loaded_manifest(manifest)


def test_parse_plugin_config(tmp_path: Path) -> None:
    p = _TrivialPlugin()
    cfg = p.parse_plugin_config(minimal_execution_context(tmp_path), _Cfg)
    assert cfg.pass_threshold == 2.5


def test_resolve_workspace_file(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    ok = ws / "out" / "x.json"
    ok.parent.mkdir(parents=True)
    ok.write_text("{}", encoding="utf-8")
    assert BmtPlugin.resolve_workspace_file(ws, "out/x.json") == ok.resolve()
    assert BmtPlugin.resolve_workspace_file(ws, "../escape/x.json") is None
    assert BmtPlugin.resolve_workspace_file(ws, "missing.json") is None


def test_max_grace_case_failures() -> None:
    assert BmtPlugin.max_grace_case_failures({}) == 1
    assert BmtPlugin.max_grace_case_failures({"max_grace_case_failures": 0}) == 0
    assert BmtPlugin.max_grace_case_failures({"max_grace_case_failures": "bogus"}) == 1


def test_execution_failure_result(tmp_path: Path) -> None:
    ctx = minimal_execution_context(tmp_path)
    prep = PreparedAssets(
        dataset_root=ctx.dataset_root,
        workspace_root=ctx.workspace_root,
    )
    p = _TrivialPlugin()
    r = p.execution_failure_result(RuntimeError("boom"), prepared=prep, context=ctx)
    assert r.raw_summary.get(PLUGIN_EXECUTE_EXCEPTION_RAW_KEY) is True
    assert len(r.case_results) == 1
    assert r.case_results[0].status == "failed"
    assert "RuntimeError" in r.case_results[0].error
