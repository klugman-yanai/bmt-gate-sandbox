"""Tests for project-wide request expansion in vm_watcher."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import gcp.image.vm_watcher as watcher  # type: ignore[import-not-found]
from tools.repo.sk_bmt_ids import SK_BMT_FALSE_REJECT_NAMUH


def _write_jobs(repo_root: Path, project: str, bmts: dict) -> None:
    """Write a minimal bmt_jobs.json for a project under repo_root."""
    project_dir = repo_root / "projects" / project
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "bmt_manager.py").write_text("# stub manager\n")
    (project_dir / "bmt_jobs.json").write_text(json.dumps({"bmts": bmts}))


def test_resolve_requested_legs_expands_project_wide_requests(tmp_path: Path):
    _write_jobs(
        tmp_path,
        "sk",
        {
            SK_BMT_FALSE_REJECT_NAMUH: {"enabled": True},
            "legacy_disabled": {"enabled": False},
        },
    )

    resolved = watcher._resolve_requested_legs(
        legs_raw=[{"project": "sk", "bmt_id": "__all__", "run_id": "gh-1"}],
        repo_root=tmp_path,
    )

    assert len(resolved) == 2
    by_id = {row["bmt_id"]: row for row in resolved}

    assert by_id[SK_BMT_FALSE_REJECT_NAMUH]["decision"] == "accepted"
    assert by_id[SK_BMT_FALSE_REJECT_NAMUH]["reason"] is None

    assert by_id["legacy_disabled"]["decision"] == "rejected"
    assert by_id["legacy_disabled"]["reason"] == "bmt_disabled"

    run_ids = [str(row["run_id"]) for row in resolved]
    assert len(run_ids) == len(set(run_ids))


def test_resolve_requested_legs_keeps_explicit_bmt_mode(tmp_path: Path):
    _write_jobs(
        tmp_path,
        "sk",
        {SK_BMT_FALSE_REJECT_NAMUH: {"enabled": True}},
    )

    resolved = watcher._resolve_requested_legs(
        legs_raw=[{"project": "sk", "bmt_id": SK_BMT_FALSE_REJECT_NAMUH, "run_id": "gh-1"}],
        repo_root=tmp_path,
    )

    assert len(resolved) == 1
    assert resolved[0]["project"] == "sk"
    assert resolved[0]["bmt_id"] == SK_BMT_FALSE_REJECT_NAMUH
    assert resolved[0]["decision"] == "accepted"
    assert resolved[0]["reason"] is None
