from __future__ import annotations

import pytest
from backend.config import constants as backend_constants, decisions as backend_decisions
from bmtcontract import constants as shared_constants, decisions as shared_decisions
from bmtcontract.models import DispatchReceiptState, DispatchReceiptV1, FinalizationRecordV2, ResultsPointerV2
from bmtcontract.paths import dispatch_receipt_path
from bmtgate.contract import constants as ci_constants

pytestmark = pytest.mark.unit


def test_backend_and_ci_wrappers_reexport_shared_contracts() -> None:
    assert backend_constants.STATUS_CONTEXT == shared_constants.STATUS_CONTEXT
    assert ci_constants.STATUS_CONTEXT == shared_constants.STATUS_CONTEXT
    assert (
        backend_constants.ENV_BMT_DISPATCH_REQUIRE_CANCEL_OK
        == shared_constants.ENV_BMT_DISPATCH_REQUIRE_CANCEL_OK
    )
    assert backend_constants.ENV_BMT_ALLOW_UNSAFE_SUPERSEDE == shared_constants.ENV_BMT_ALLOW_UNSAFE_SUPERSEDE
    assert ci_constants.WORKFLOW_OUTPUT_BMT_RECOVERY_USED == shared_constants.WORKFLOW_OUTPUT_BMT_RECOVERY_USED
    assert (
        ci_constants.WORKFLOW_OUTPUT_BMT_DISPATCH_FALLBACK_USED
        == shared_constants.WORKFLOW_OUTPUT_BMT_DISPATCH_FALLBACK_USED
    )
    assert backend_decisions.ReasonCode.INCOMPLETE_PLAN == shared_decisions.ReasonCode.INCOMPLETE_PLAN


def test_results_pointer_v2_reads_legacy_and_phase2_payloads() -> None:
    legacy = ResultsPointerV2.from_payload({"latest": "run-old", "last_passing": "run-pass", "updated_at": "ts"})
    assert legacy.latest_run_id == "run-old"
    assert legacy.last_passing_run_id == "run-pass"
    assert legacy.schema_version == 2

    phase2 = ResultsPointerV2.from_payload(
        {
            "schema_version": 2,
            "latest_run_id": "run-new",
            "last_passing_run_id": None,
            "updated_at": "ts",
            "promoted_by_workflow_run_id": "wf-77",
        }
    )
    assert phase2.latest_run_id == "run-new"
    assert phase2.last_passing_run_id is None
    assert phase2.promoted_by_workflow_run_id == "wf-77"


def test_results_pointer_v2_rejects_missing_latest_pointer() -> None:
    with pytest.raises(ValueError, match="latest/latest_run_id"):
        ResultsPointerV2.from_payload({"updated_at": "ts"})


def test_dispatch_receipt_v1_and_shared_paths_cover_follow_up_contracts() -> None:
    receipt = DispatchReceiptV1(
        workflow_run_id="wf-123",
        repository="owner/repo",
        head_sha="a" * 40,
        state=DispatchReceiptState.PENDING_START,
        created_at="2026-03-29T10:00:00Z",
        updated_at="2026-03-29T10:00:00Z",
    )

    assert receipt.state == DispatchReceiptState.PENDING_START
    assert dispatch_receipt_path("wf-123") == "triggers/dispatch/wf-123.json"


def test_finalization_record_v2_tracks_completeness_and_reconciliation_fields() -> None:
    record = FinalizationRecordV2(
        workflow_run_id="wf-9",
        state="prepared",
        expected_leg_count=2,
        present_summary_count=1,
        missing_leg_keys=["sk/false_rejects"],
        extra_summary_keys=["triggers/summaries/wf-9/unexpected.json"],
        needs_reconciliation=True,
        reconciliation_reason="missing_summaries,unexpected_summaries",
    )

    assert record.expected_leg_count == 2
    assert record.present_summary_count == 1
    assert record.needs_reconciliation is True
