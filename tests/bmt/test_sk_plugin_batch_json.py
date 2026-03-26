"""Hardening tests for SK plugin batch JSON path and parsing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from backend.runtime.sdk.plugin import BmtPlugin

_SK_PLUGIN_SRC = str(Path(__file__).resolve().parents[2] / "gcp/stage/projects/sk/plugin_workspaces/default/src")

pytestmark = pytest.mark.unit


def _import_plugin_module():
    if _SK_PLUGIN_SRC not in sys.path:
        sys.path.insert(0, _SK_PLUGIN_SRC)
    from sk_plugin import plugin as sk_plugin_mod

    return sk_plugin_mod


def _make_plugin():
    sk_plugin_mod = _import_plugin_module()
    return sk_plugin_mod.SkPlugin()


def test_resolve_batch_results_rejects_absolute_relpath(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "out.json"
    outside.write_text("{}", encoding="utf-8")
    assert BmtPlugin.resolve_workspace_file(ws, str(outside)) is None


def test_resolve_batch_results_rejects_parent_escape(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    assert BmtPlugin.resolve_workspace_file(ws, "../outside.json") is None


def test_resolve_batch_results_accepts_file_under_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    sub = ws / "r" / "out"
    sub.mkdir(parents=True)
    f = sub / "batch.json"
    f.write_text("{}", encoding="utf-8")
    assert BmtPlugin.resolve_workspace_file(ws, "r/out/batch.json") == f.resolve()


def test_parse_batch_json_rejects_path_outside_workspace(tmp_path: Path) -> None:
    plugin = _make_plugin()
    outside = tmp_path / "secret.json"
    outside.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "file": "a.wav",
                        "status": "ok",
                        "namuh_count": 1,
                        "exit_code": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(ValueError, match="outside workspace"):
        plugin._parse_batch_json(outside, ws)


def test_parse_batch_json_requires_non_empty_results(tmp_path: Path) -> None:
    plugin = _make_plugin()
    ws = tmp_path / "ws"
    f = ws / "b.json"
    ws.mkdir()
    f.write_text(json.dumps({"results": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid batch JSON"):
        plugin._parse_batch_json(f, ws)


def test_parse_batch_json_rejects_invalid_status(tmp_path: Path) -> None:
    plugin = _make_plugin()
    ws = tmp_path / "ws"
    ws.mkdir()
    f = ws / "b.json"
    f.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "file": "a.wav",
                        "status": "maybe",
                        "namuh_count": 1,
                        "exit_code": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid batch JSON"):
        plugin._parse_batch_json(f, ws)


def test_parse_batch_json_rejects_non_finite_namuh(tmp_path: Path) -> None:
    plugin = _make_plugin()
    ws = tmp_path / "ws"
    ws.mkdir()
    f = ws / "b.json"
    f.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "file": "a.wav",
                        "status": "ok",
                        "namuh_count": float("nan"),
                        "exit_code": 0,
                    }
                ]
            },
            allow_nan=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be finite"):
        plugin._parse_batch_json(f, ws)


def test_parse_batch_json_ok_minimal(tmp_path: Path) -> None:
    plugin = _make_plugin()
    ws = tmp_path / "ws"
    ws.mkdir()
    f = ws / "b.json"
    f.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "file": "dir/a.wav",
                        "status": "ok",
                        "namuh_count": 42,
                        "exit_code": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = plugin._parse_batch_json(f, ws)
    assert result.execution_mode_used == "kardome_batch_json"
    assert len(result.case_results) == 1
    c = result.case_results[0]
    assert c.case_id == "dir/a.wav"
    assert c.status == "ok"
    assert c.metrics["namuh_count"] == 42.0
