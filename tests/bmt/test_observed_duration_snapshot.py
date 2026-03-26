"""Tests for ETA duration hints from persisted snapshot ``latest.json``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.config.value_types import ResultsPath
from backend.runtime.artifacts import (
    earliest_progress_started_at_iso,
    load_observed_duration_sec_from_latest_snapshot,
    parse_optional_instant_iso,
)
from backend.runtime.models import PlanLeg, ReportingMetadata

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
    (results / "current.json").write_text(json.dumps({"latest": snap, "last_passing": snap}), encoding="utf-8")
    (results / "snapshots" / snap / "latest.json").write_text(
        json.dumps({"duration_sec": 412, "project": "sk"}), encoding="utf-8"
    )
    assert load_observed_duration_sec_from_latest_snapshot(stage_root=tmp_path, leg=leg) == 412


def test_load_observed_duration_returns_none_when_missing_or_invalid(tmp_path: Path) -> None:
    leg = _leg()
    assert load_observed_duration_sec_from_latest_snapshot(stage_root=tmp_path, leg=leg) is None


def test_earliest_progress_started_at_prefers_earliest_leg(tmp_path: Path) -> None:
    wid = "wf-1"
    base = tmp_path / "triggers" / "progress" / wid
    base.mkdir(parents=True)
    (base / "sk-a.json").write_text(
        '{"project":"sk","bmt_slug":"a","status":"running","started_at":"2026-03-20T12:00:00Z","updated_at":"2026-03-20T12:00:01Z"}',
        encoding="utf-8",
    )
    (base / "sk-b.json").write_text(
        '{"project":"sk","bmt_slug":"b","status":"running","started_at":"2026-03-20T11:59:00Z","updated_at":"2026-03-20T12:00:01Z"}',
        encoding="utf-8",
    )
    assert earliest_progress_started_at_iso(stage_root=tmp_path, workflow_run_id=wid) == "2026-03-20T11:59:00Z"


def test_parse_optional_instant_iso_accepts_valid_iso() -> None:
    ins = parse_optional_instant_iso("2026-03-20T11:59:00Z")
    assert ins is not None
    assert ins.timestamp() > 0


def test_parse_optional_instant_iso_rejects_garbage() -> None:
    assert parse_optional_instant_iso("") is None
    assert parse_optional_instant_iso("not-a-date") is None


def test_reporting_metadata_helpers_describe_check_and_started_at() -> None:
    ready = ReportingMetadata(workflow_execution_url="https://wf", check_run_id=1, started_at="")
    assert ready.has_check_run_and_details_url()
    assert ready.started_at_iso_or_none() is None
    assert ready.needs_started_at_backfill()

    complete = ReportingMetadata(workflow_execution_url="https://wf", check_run_id=1, started_at="2026-01-01T00:00:00Z")
    assert not complete.needs_started_at_backfill()
    assert complete.started_at_iso_or_none() == "2026-01-01T00:00:00Z"
