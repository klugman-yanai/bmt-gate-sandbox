"""Tests for local run retention in root_orchestrator."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import gcp.code.root_orchestrator as orchestrator


def _make_run(parent: Path, name: str, mtime: int) -> Path:
    run_dir = parent / name
    run_dir.mkdir(parents=True, exist_ok=True)
    marker = run_dir / "marker.txt"
    marker.write_text("x\n", encoding="utf-8")
    os.utime(run_dir, (mtime, mtime))
    os.utime(marker, (mtime, mtime))
    return run_dir


def test_prune_run_dirs_keeps_two_newest(tmp_path: Path) -> None:
    bmt_root = tmp_path / "sk" / "false_reject_namuh"
    bmt_root.mkdir(parents=True, exist_ok=True)

    old = _make_run(bmt_root, "run_20260220T010101Z_1", 1000)
    prev = _make_run(bmt_root, "run_20260221T010101Z_2", 2000)
    cur = _make_run(bmt_root, "run_20260222T010101Z_3", 3000)
    (bmt_root / "notes").mkdir()

    orchestrator._prune_run_dirs(bmt_root, keep_recent=2)

    assert not old.exists()
    assert prev.exists()
    assert cur.exists()
    assert (bmt_root / "notes").exists()


def test_prune_workspace_keeps_two_per_bmt(tmp_path: Path) -> None:
    bmt_a = tmp_path / "sk" / "false_reject_namuh"
    bmt_b = tmp_path / "foo" / "wakeword"
    bmt_a.mkdir(parents=True, exist_ok=True)
    bmt_b.mkdir(parents=True, exist_ok=True)

    _make_run(bmt_a, "run_a1", 1000)
    _make_run(bmt_a, "run_a2", 2000)
    _make_run(bmt_a, "run_a3", 3000)
    _make_run(bmt_b, "run_b1", 1100)
    _make_run(bmt_b, "run_b2", 2100)
    _make_run(bmt_b, "run_b3", 3100)

    orchestrator._prune_workspace(tmp_path, keep_recent_per_bmt=2)

    remaining_a = sorted(p.name for p in bmt_a.iterdir() if p.is_dir() and p.name.startswith("run_"))
    remaining_b = sorted(p.name for p in bmt_b.iterdir() if p.is_dir() and p.name.startswith("run_"))
    assert remaining_a == ["run_a2", "run_a3"]
    assert remaining_b == ["run_b2", "run_b3"]


def test_convention_paths_use_project_layout() -> None:
    assert orchestrator._manager_rel_path("sk") == "sk/bmt_manager.py"
    assert orchestrator._jobs_rel_path("sk") == "sk/config/bmt_jobs.json"


def test_validate_jobs_config_requires_defined_enabled_bmt(tmp_path: Path) -> None:
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text("{}", encoding="utf-8")

    with pytest.raises(orchestrator.OrchestratorError, match="missing object key 'bmts'"):
        orchestrator._validate_jobs_config({}, project="sk", bmt_id="foo", jobs_path=jobs_path)

    with pytest.raises(orchestrator.OrchestratorError, match="not defined"):
        orchestrator._validate_jobs_config({"bmts": {}}, project="sk", bmt_id="foo", jobs_path=jobs_path)

    with pytest.raises(orchestrator.OrchestratorError, match="is disabled"):
        orchestrator._validate_jobs_config(
            {"bmts": {"foo": {"enabled": False}}},
            project="sk",
            bmt_id="foo",
            jobs_path=jobs_path,
        )

    orchestrator._validate_jobs_config(
        {"bmts": {"foo": {"enabled": True}}},
        project="sk",
        bmt_id="foo",
        jobs_path=jobs_path,
    )
