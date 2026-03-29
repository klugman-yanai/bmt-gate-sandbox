from __future__ import annotations

from pathlib import Path

import pytest
from backend.runtime.finalization import (
    LeaseAcquisitionError,
    acquire_results_path_leases,
    load_optional_finalization_record,
    release_results_path_leases,
    update_finalization_record,
)
from backend.runtime.models import FinalizationState

pytestmark = pytest.mark.unit


def test_update_finalization_record_round_trips_phase2_state(tmp_path: Path) -> None:
    stage_root = tmp_path / "stage"
    stage_root.mkdir(parents=True, exist_ok=True)

    record = update_finalization_record(
        stage_root=stage_root,
        workflow_run_id="wf-1",
        repository="owner/repo",
        head_sha="a" * 40,
        state=FinalizationState.PREPARED,
        publish_required=True,
        github_publish_complete=False,
        promoted_results_paths=[],
        lease_keys=["lease-a"],
        expected_leg_count=2,
        present_summary_count=1,
        missing_leg_keys=["sk/false_rejects"],
        extra_summary_keys=["triggers/summaries/wf-1/unexpected.json"],
        needs_reconciliation=True,
        reconciliation_reason="missing_summaries",
    )

    reloaded = load_optional_finalization_record(stage_root=stage_root, workflow_run_id="wf-1")
    assert reloaded is not None
    assert reloaded.workflow_run_id == "wf-1"
    assert reloaded.state == FinalizationState.PREPARED
    assert reloaded.lease_keys == ["lease-a"]
    assert reloaded.expected_leg_count == 2
    assert reloaded.present_summary_count == 1
    assert reloaded.missing_leg_keys == ["sk/false_rejects"]
    assert reloaded.needs_reconciliation is True
    assert reloaded.prepared_at == record.prepared_at


def test_local_results_path_leases_conflict_across_workflow_runs(tmp_path: Path) -> None:
    stage_root = tmp_path / "stage"
    stage_root.mkdir(parents=True, exist_ok=True)
    handles = acquire_results_path_leases(
        stage_root=stage_root,
        workflow_run_id="wf-1",
        results_paths=["projects/sk/results/false_alarms"],
    )

    with pytest.raises(LeaseAcquisitionError, match="results-path lease already held"):
        acquire_results_path_leases(
            stage_root=stage_root,
            workflow_run_id="wf-2",
            results_paths=["projects/sk/results/false_alarms"],
        )

    release_results_path_leases(handles=handles)


def test_local_results_path_leases_are_idempotent_for_same_workflow_run(tmp_path: Path) -> None:
    stage_root = tmp_path / "stage"
    stage_root.mkdir(parents=True, exist_ok=True)
    first = acquire_results_path_leases(
        stage_root=stage_root,
        workflow_run_id="wf-1",
        results_paths=["projects/sk/results/false_alarms"],
    )
    second = acquire_results_path_leases(
        stage_root=stage_root,
        workflow_run_id="wf-1",
        results_paths=["projects/sk/results/false_alarms"],
    )

    assert len(first) == 1
    assert len(second) == 1
    assert first[0].lease_key == second[0].lease_key
    assert first[0].local_path == second[0].local_path

    release_results_path_leases(handles=second)
