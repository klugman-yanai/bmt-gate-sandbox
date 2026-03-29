from __future__ import annotations

import os
from pathlib import Path

import pytest
from backend.runtime.artifacts import write_reporting_metadata
from backend.runtime.finalization import update_finalization_record
from backend.runtime.models import FinalizationState, ReportingMetadata
from bmtcontract.models import DispatchReceiptState, DispatchReceiptV1, FinalizationRecordV2, LeaseRecordV2
from bmtcontract.paths import dispatch_receipt_path, finalization_record_path, lease_object_path, log_dump_path

from tools.bmt.ops_doctor import inspect_workflow_run, scan_stale_control_plane

pytestmark = pytest.mark.unit


def test_inspect_workflow_run_surfaces_reconciliation_artifacts(tmp_path: Path) -> None:
    stage_root = tmp_path / "benchmarks"
    stage_root.mkdir(parents=True, exist_ok=True)
    workflow_run_id = "wf-123"

    update_finalization_record(
        stage_root=stage_root,
        workflow_run_id=workflow_run_id,
        repository="owner/repo",
        head_sha="a" * 40,
        state=FinalizationState.FAILED_GITHUB_PUBLISH,
        publish_required=True,
        github_publish_complete=False,
        promoted_results_paths=[],
        lease_keys=["lease-a"],
        expected_leg_count=2,
        present_summary_count=1,
        missing_leg_keys=["sk/false_rejects"],
        extra_summary_keys=[],
        needs_reconciliation=True,
        reconciliation_reason="missing_summaries,github_publish_failed",
    )
    write_reporting_metadata(
        stage_root=stage_root,
        workflow_run_id=workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url="https://example.test/workflows/123",
            check_run_id=91,
            started_at="2026-03-28T10:00:00Z",
        ),
    )
    lease_path = stage_root / lease_object_path("lease-a")
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_path.write_text(
        LeaseRecordV2(
            lease_key="lease-a",
            workflow_run_id=workflow_run_id,
            results_path="projects/sk/results/false_rejects",
            acquired_at="2026-03-28T10:00:00Z",
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    dump_path = stage_root / log_dump_path(workflow_run_id)
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    dump_path.write_text("boom", encoding="utf-8")

    report = inspect_workflow_run(stage_root=stage_root, workflow_run_id=workflow_run_id)

    assert report.exit_code == 1
    assert report.needs_reconciliation is True
    kinds = {finding.kind for finding in report.findings}
    assert "finalization_needs_reconciliation" in kinds
    assert "preserved_reporting_metadata" in kinds
    assert "lease_artifact_present" in kinds
    assert report.summary["log_dump_present"] is True


def test_scan_stale_control_plane_flags_old_receipts_and_logs(tmp_path: Path) -> None:
    stage_root = tmp_path / "benchmarks"
    stage_root.mkdir(parents=True, exist_ok=True)

    finalization_path = stage_root / finalization_record_path("wf-old")
    finalization_path.parent.mkdir(parents=True, exist_ok=True)
    finalization_path.write_text(
        FinalizationRecordV2(
            workflow_run_id="wf-old",
            repository="owner/repo",
            head_sha="b" * 40,
            state=FinalizationState.FAILED_PROMOTION,
            prepared_at="2026-03-20T09:55:00Z",
            updated_at="2026-03-20T10:05:00Z",
            publish_required=False,
            github_publish_complete=False,
            promoted_results_paths=[],
            lease_keys=[],
            expected_leg_count=1,
            present_summary_count=0,
            missing_leg_keys=[],
            extra_summary_keys=[],
            needs_reconciliation=True,
            reconciliation_reason="promotion_failed",
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    dispatch_path = stage_root / dispatch_receipt_path("wf-dispatch")
    dispatch_path.parent.mkdir(parents=True, exist_ok=True)
    dispatch_path.write_text(
        DispatchReceiptV1(
            workflow_run_id="wf-dispatch",
            repository="owner/repo",
            head_sha="c" * 40,
            state=DispatchReceiptState.START_FAILED,
            created_at="2026-03-20T10:00:00Z",
            updated_at="2026-03-20T10:05:00Z",
            error_message="boom",
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    lease_path = stage_root / lease_object_path("lease-old")
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_path.write_text(
        LeaseRecordV2(
            lease_key="lease-old",
            workflow_run_id="wf-old",
            results_path="projects/sk/results/false_rejects",
            acquired_at="2026-03-20T09:00:00Z",
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    log_path = stage_root / log_dump_path("wf-old")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("old", encoding="utf-8")
    old_ts = 1_742_462_400  # 2025-03-20T00:00:00Z
    for path in (finalization_path, dispatch_path, lease_path, log_path):
        os.utime(path, (old_ts, old_ts))

    report = scan_stale_control_plane(stage_root=stage_root, older_than_hours=1)

    assert report.exit_code == 1
    kinds = {finding.kind for finding in report.findings}
    assert "stale_finalization" in kinds
    assert "stale_dispatch_receipt" in kinds
    assert "stale_lease" in kinds
    assert "stale_log_dump" in kinds


def test_scan_stale_control_plane_returns_exit_two_for_unreadable_artifact(tmp_path: Path) -> None:
    stage_root = tmp_path / "benchmarks"
    path = stage_root / "triggers" / "finalization" / "wf-bad.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    report = scan_stale_control_plane(stage_root=stage_root, older_than_hours=1)

    assert report.exit_code == 2
    assert report.findings[0].kind == "unreadable_artifact"
