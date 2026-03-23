"""Tests for core-main workflow drift (mocked; no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.repo import core_main_workflows as cm


def test_skip_env_returns_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CORE_MAIN_WORKFLOW_CHECK", "skip")
    (tmp_path / "a.yml").write_text("x: 1\n", encoding="utf-8")
    assert cm.run_drift_check(tmp_path, mode="preflight") == 0


def test_match_when_remote_equals_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CORE_MAIN_WORKFLOW_CHECK", raising=False)
    monkeypatch.setattr(cm, "_gh_authenticated", lambda: True)
    monkeypatch.setattr(cm, "command_available", lambda _cmd: True)

    text = "name: CI\n"

    def fake_names() -> list[str] | None:
        return ["same.yml"]

    def fake_text(name: str) -> str | None:
        assert name == "same.yml"
        return text

    monkeypatch.setattr(cm, "_remote_workflow_names", fake_names)
    monkeypatch.setattr(cm, "_remote_workflow_text", fake_text)
    (tmp_path / "same.yml").write_text(text, encoding="utf-8")
    assert cm.run_drift_check(tmp_path, mode="preflight") == 0


def test_strict_fails_on_diff(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CORE_MAIN_WORKFLOW_CHECK", "strict")
    monkeypatch.setattr(cm, "_gh_authenticated", lambda: True)
    monkeypatch.setattr(cm, "command_available", lambda _cmd: True)

    def fake_names() -> list[str] | None:
        return ["w.yml"]

    def fake_text(_name: str) -> str | None:
        return "remote: true\n"

    monkeypatch.setattr(cm, "_remote_workflow_names", fake_names)
    monkeypatch.setattr(cm, "_remote_workflow_text", fake_text)
    (tmp_path / "w.yml").write_text("local: true\n", encoding="utf-8")
    assert cm.run_drift_check(tmp_path, mode="preflight") == 1
