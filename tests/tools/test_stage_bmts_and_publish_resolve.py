"""Unit tests for staged BMT enumeration and publish target resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from tools.bmt.stage_bmts import iter_staged_bmts
from tools.cli.publish_cmd import _resolve_publish_targets


def test_iter_staged_bmts_sorted_pairs(tmp_path: Path) -> None:
    root = tmp_path / "benchmarks"
    (root / "projects" / "b" / "bmts" / "y" / "bmt.json").parent.mkdir(parents=True)
    (root / "projects" / "b" / "bmts" / "y" / "bmt.json").write_text("{}", encoding="utf-8")
    (root / "projects" / "a" / "bmts" / "x" / "bmt.json").parent.mkdir(parents=True)
    (root / "projects" / "a" / "bmts" / "x" / "bmt.json").write_text("{}", encoding="utf-8")
    assert iter_staged_bmts(stage_root=root) == [("a", "x"), ("b", "y")]


def test_resolve_publish_explicit_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.cli.publish_cmd.repo_root", lambda: tmp_path)
    root = tmp_path / "benchmarks"
    (root / "projects" / "p" / "bmts" / "b1" / "bmt.json").parent.mkdir(parents=True)
    (root / "projects" / "p" / "bmts" / "b1" / "bmt.json").write_text("{}", encoding="utf-8")
    (root / "projects" / "p" / "bmts" / "b2" / "bmt.json").parent.mkdir(parents=True)
    (root / "projects" / "p" / "bmts" / "b2" / "bmt.json").write_text("{}", encoding="utf-8")
    assert _resolve_publish_targets("p", "b2") == ("p", "b2")


def test_resolve_publish_single_under_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.cli.publish_cmd.repo_root", lambda: tmp_path)
    root = tmp_path / "benchmarks"
    (root / "projects" / "p" / "bmts" / "only" / "bmt.json").parent.mkdir(parents=True)
    (root / "projects" / "p" / "bmts" / "only" / "bmt.json").write_text("{}", encoding="utf-8")
    assert _resolve_publish_targets("p", None) == ("p", "only")


def test_resolve_publish_ambiguous_project_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.cli.publish_cmd.repo_root", lambda: tmp_path)
    root = tmp_path / "benchmarks"
    for b in ("b1", "b2"):
        (root / "projects" / "p" / "bmts" / b / "bmt.json").parent.mkdir(parents=True)
        (root / "projects" / "p" / "bmts" / b / "bmt.json").write_text("{}", encoding="utf-8")
    with pytest.raises(typer.BadParameter):
        _resolve_publish_targets("p", None)


def test_resolve_publish_unique_globally(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.cli.publish_cmd.repo_root", lambda: tmp_path)
    root = tmp_path / "benchmarks"
    (root / "projects" / "solo" / "bmts" / "one" / "bmt.json").parent.mkdir(parents=True)
    (root / "projects" / "solo" / "bmts" / "one" / "bmt.json").write_text("{}", encoding="utf-8")
    assert _resolve_publish_targets(None, None) == ("solo", "one")


def test_resolve_publish_multiple_globally_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.cli.publish_cmd.repo_root", lambda: tmp_path)
    root = tmp_path / "benchmarks"
    for proj, bmt in (("a", "x"), ("b", "y")):
        p = root / "projects" / proj / "bmts" / bmt / "bmt.json"
        p.parent.mkdir(parents=True)
        p.write_text("{}", encoding="utf-8")
    with pytest.raises(typer.BadParameter):
        _resolve_publish_targets(None, None)


def test_resolve_publish_env_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tools.cli.publish_cmd.repo_root", lambda: tmp_path)
    root = tmp_path / "benchmarks"
    (root / "projects" / "a" / "bmts" / "x" / "bmt.json").parent.mkdir(parents=True)
    (root / "projects" / "a" / "bmts" / "x" / "bmt.json").write_text("{}", encoding="utf-8")
    (root / "projects" / "a" / "bmts" / "y" / "bmt.json").parent.mkdir(parents=True)
    (root / "projects" / "a" / "bmts" / "y" / "bmt.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("BMT_PROJECT", "a")
    monkeypatch.setenv("BMT_BENCHMARK", "y")
    assert _resolve_publish_targets(None, None) == ("a", "y")
