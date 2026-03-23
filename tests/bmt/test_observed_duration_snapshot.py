"""Tests for ETA duration hints from persisted snapshot ``latest.json``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gcp.image.config.value_types import ResultsPath
from gcp.image.runtime.artifacts import load_observed_duration_sec_from_latest_snapshot
from gcp.image.runtime.models import PlanLeg

pytestmark = pytest.mark.unit


def _leg() -> PlanLeg:
    return PlanLeg(
        project="sk",
        bmt_slug="false_alarms",
        bmt_id="id",
        run_id="r1",
        manifest_path="projects/sk/bmts/false_alarms/bmt.json",
        manifest_digest="d",
        plugin_ref="p",
        plugin_digest="pd",
        inputs_prefix="projects/sk/inputs/false_alarms",
        results_path=ResultsPath("projects/sk/results/false_alarms"),
        outputs_prefix="projects/sk/outputs/false_alarms",
    )


def test_load_observed_duration_reads_duration_sec_from_latest_json(tmp_path: Path) -> None:
    leg = _leg()
    results = tmp_path / str(leg.results_path)
    snap = "run-abc"
    (results / "snapshots" / snap).mkdir(parents=True)
    (results / "current.json").write_text(
        json.dumps({"latest": snap, "last_passing": snap}), encoding="utf-8"
    )
    (results / "snapshots" / snap / "latest.json").write_text(
        json.dumps({"duration_sec": 412, "project": "sk"}), encoding="utf-8"
    )
    assert load_observed_duration_sec_from_latest_snapshot(stage_root=tmp_path, leg=leg) == 412


def test_load_observed_duration_returns_none_when_missing_or_invalid(tmp_path: Path) -> None:
    leg = _leg()
    assert load_observed_duration_sec_from_latest_snapshot(stage_root=tmp_path, leg=leg) is None
