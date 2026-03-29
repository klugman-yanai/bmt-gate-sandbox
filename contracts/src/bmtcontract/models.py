"""Versioned shared coordination models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from bmtcontract.constants import (
    DISPATCH_RECEIPT_SCHEMA_VERSION,
    FINALIZATION_RECORD_SCHEMA_VERSION,
    LEASE_RECORD_SCHEMA_VERSION,
    POINTER_KEY_LAST_PASSING,
    POINTER_KEY_LATEST,
    POINTER_V2_KEY_LAST_PASSING_RUN_ID,
    POINTER_V2_KEY_LATEST_RUN_ID,
    POINTER_V2_KEY_PROMOTED_BY_WORKFLOW_RUN_ID,
    REPORTING_METADATA_SCHEMA_VERSION,
    RESULTS_POINTER_SCHEMA_VERSION,
)


class ResultsPointerV2(BaseModel):
    schema_version: int = RESULTS_POINTER_SCHEMA_VERSION
    latest_run_id: str
    last_passing_run_id: str | None = None
    updated_at: str = ""
    promoted_by_workflow_run_id: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ResultsPointerV2:
        latest_run_id = str(
            payload.get(POINTER_V2_KEY_LATEST_RUN_ID)
            or payload.get(POINTER_KEY_LATEST)
            or ""
        ).strip()
        if not latest_run_id:
            raise ValueError("current.json is missing latest/latest_run_id")
        last_raw = payload.get(POINTER_V2_KEY_LAST_PASSING_RUN_ID)
        if last_raw is None:
            last_raw = payload.get(POINTER_KEY_LAST_PASSING)
        last_passing = str(last_raw).strip() if isinstance(last_raw, str) and str(last_raw).strip() else None
        return cls(
            schema_version=int(payload.get("schema_version") or RESULTS_POINTER_SCHEMA_VERSION),
            latest_run_id=latest_run_id,
            last_passing_run_id=last_passing,
            updated_at=str(payload.get("updated_at") or "").strip(),
            promoted_by_workflow_run_id=str(payload.get(POINTER_V2_KEY_PROMOTED_BY_WORKFLOW_RUN_ID) or "").strip(),
        )


class ReportingMetadataV2(BaseModel):
    schema_version: int = REPORTING_METADATA_SCHEMA_VERSION
    workflow_execution_name: str = ""
    workflow_execution_url: str = ""
    check_run_id: int | None = None
    started_at: str = ""
    github_publish_complete: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ReportingMetadataV2:
        return cls(
            schema_version=int(payload.get("schema_version") or REPORTING_METADATA_SCHEMA_VERSION),
            workflow_execution_name=str(payload.get("workflow_execution_name") or "").strip(),
            workflow_execution_url=str(payload.get("workflow_execution_url") or "").strip(),
            check_run_id=payload.get("check_run_id"),
            started_at=str(payload.get("started_at") or "").strip(),
            github_publish_complete=bool(payload.get("github_publish_complete")),
        )

    def has_check_run_and_details_url(self) -> bool:
        return self.check_run_id is not None and bool(self.workflow_execution_url.strip())

    def started_at_iso_or_none(self) -> str | None:
        t = (self.started_at or "").strip()
        return t or None

    def needs_started_at_backfill(self) -> bool:
        return self.has_check_run_and_details_url() and self.started_at_iso_or_none() is None


class FinalizationState(StrEnum):
    PREPARED = "prepared"
    GITHUB_PUBLISHED = "github_published"
    PROMOTION_COMMITTED = "promotion_committed"
    FAILED_GITHUB_PUBLISH = "failed_github_publish"
    FAILED_PROMOTION = "failed_promotion"


class FinalizationRecordV2(BaseModel):
    schema_version: int = FINALIZATION_RECORD_SCHEMA_VERSION
    workflow_run_id: str
    repository: str = ""
    head_sha: str = ""
    state: FinalizationState
    prepared_at: str = ""
    updated_at: str = ""
    publish_required: bool = False
    github_publish_complete: bool = False
    promoted_results_paths: list[str] = Field(default_factory=list)
    lease_keys: list[str] = Field(default_factory=list)
    expected_leg_count: int = 0
    present_summary_count: int = 0
    missing_leg_keys: list[str] = Field(default_factory=list)
    extra_summary_keys: list[str] = Field(default_factory=list)
    needs_reconciliation: bool = False
    reconciliation_reason: str = ""
    error_message: str = ""


class LeaseRecordV2(BaseModel):
    schema_version: int = LEASE_RECORD_SCHEMA_VERSION
    lease_key: str
    workflow_run_id: str
    results_path: str
    acquired_at: str


class DispatchReceiptState(StrEnum):
    PENDING_START = "pending_start"
    STARTED = "started"
    START_FAILED = "start_failed"


class DispatchReceiptV1(BaseModel):
    schema_version: int = DISPATCH_RECEIPT_SCHEMA_VERSION
    workflow_run_id: str
    repository: str
    head_sha: str
    state: DispatchReceiptState
    created_at: str = ""
    updated_at: str = ""
    workflow_execution_name: str = ""
    workflow_execution_url: str = ""
    workflow_execution_state: str = ""
    error_message: str = ""
