"""Operator-facing reconciliation inspection for control-plane artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bmtcontract.models import (
    DispatchReceiptState,
    DispatchReceiptV1,
    FinalizationRecordV2,
    FinalizationState,
    LeaseRecordV2,
    ReportingMetadataV2,
)
from bmtcontract.paths import (
    dispatch_receipt_path,
    finalization_record_path,
    log_dump_path,
    reporting_metadata_path,
)
from pydantic import BaseModel, ValidationError
from whenever import Instant

from tools.repo.paths import WorkspaceLayout, repo_root


class UnreadableArtifactError(RuntimeError):
    """Raised when a control-plane artifact cannot be parsed safely."""


@dataclass(frozen=True, slots=True)
class DoctorFinding:
    kind: str
    path: str
    detail: str
    workflow_run_id: str = ""
    age_hours: float | None = None

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        if self.age_hours is None:
            payload.pop("age_hours")
        return payload


@dataclass(frozen=True, slots=True)
class DoctorReport:
    exit_code: int
    mode: str
    needs_reconciliation: bool
    findings: list[DoctorFinding] = field(default_factory=list)
    summary: dict[str, object] = field(default_factory=dict)

    def to_payload(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "needs_reconciliation": self.needs_reconciliation,
            "summary": self.summary,
            "findings": [finding.to_payload() for finding in self.findings],
        }


def default_stage_root() -> Path:
    layout = WorkspaceLayout.from_env()
    return (repo_root() / layout.stage_root).resolve()


def inspect_workflow_run(*, stage_root: Path, workflow_run_id: str) -> DoctorReport:
    finalization = _load_optional_model(
        stage_root / finalization_record_path(workflow_run_id),
        FinalizationRecordV2,
    )
    dispatch_receipt = _load_optional_model(
        stage_root / dispatch_receipt_path(workflow_run_id),
        DispatchReceiptV1,
    )
    reporting = _load_optional_model(
        stage_root / reporting_metadata_path(workflow_run_id),
        ReportingMetadataV2,
    )
    lease_records = _load_lease_records_for_workflow(stage_root=stage_root, workflow_run_id=workflow_run_id)
    dump_path = stage_root / log_dump_path(workflow_run_id)

    findings: list[DoctorFinding] = []
    if finalization is not None and finalization.needs_reconciliation:
        findings.append(
            DoctorFinding(
                kind="finalization_needs_reconciliation",
                path=str(stage_root / finalization_record_path(workflow_run_id)),
                detail=finalization.reconciliation_reason or finalization.state.value,
                workflow_run_id=workflow_run_id,
            )
        )
    elif finalization is not None and finalization.state != FinalizationState.PROMOTION_COMMITTED:
        findings.append(
            DoctorFinding(
                kind="finalization_incomplete",
                path=str(stage_root / finalization_record_path(workflow_run_id)),
                detail=finalization.state.value,
                workflow_run_id=workflow_run_id,
            )
        )

    if reporting is not None:
        findings.append(
            DoctorFinding(
                kind="preserved_reporting_metadata",
                path=str(stage_root / reporting_metadata_path(workflow_run_id)),
                detail="reporting metadata still present",
                workflow_run_id=workflow_run_id,
            )
        )

    for lease_path, lease in lease_records:
        findings.append(
            DoctorFinding(
                kind="lease_artifact_present",
                path=str(lease_path),
                detail=lease.lease_key,
                workflow_run_id=workflow_run_id,
            )
        )

    if dispatch_receipt is not None and dispatch_receipt.state != DispatchReceiptState.STARTED:
        findings.append(
            DoctorFinding(
                kind="dispatch_receipt_incomplete",
                path=str(stage_root / dispatch_receipt_path(workflow_run_id)),
                detail=dispatch_receipt.state.value,
                workflow_run_id=workflow_run_id,
            )
        )

    return DoctorReport(
        exit_code=1 if findings else 0,
        mode="workflow_run",
        needs_reconciliation=bool(findings),
        findings=findings,
        summary={
            "workflow_run_id": workflow_run_id,
            "dispatch_receipt_state": dispatch_receipt.state.value if dispatch_receipt is not None else "",
            "finalization_state": finalization.state.value if finalization is not None else "",
            "finalization_needs_reconciliation": finalization.needs_reconciliation if finalization is not None else False,
            "lease_count": len(lease_records),
            "reporting_metadata_present": reporting is not None,
            "log_dump_present": dump_path.is_file(),
        },
    )


def scan_stale_control_plane(*, stage_root: Path, older_than_hours: int) -> DoctorReport:
    if older_than_hours <= 0:
        raise ValueError("older_than_hours must be positive")
    now = Instant.now()
    findings: list[DoctorFinding] = []
    invalid_findings: list[DoctorFinding] = []

    def _collect_model_findings(
        *,
        root: Path,
        model_type: type[BaseModel],
        evaluator,
    ) -> None:
        if not root.is_dir():
            return
        for path in sorted(root.glob("*.json")):
            if not path.is_file():
                continue
            try:
                model = _load_required_model(path, model_type)
            except UnreadableArtifactError as exc:
                invalid_findings.append(
                    DoctorFinding(
                        kind="unreadable_artifact",
                        path=str(path),
                        detail=str(exc),
                    )
                )
                continue
            finding = evaluator(path, model, now, older_than_hours)
            if finding is not None:
                findings.append(finding)

    _collect_model_findings(
        root=stage_root / "triggers" / "finalization",
        model_type=FinalizationRecordV2,
        evaluator=_stale_finalization_finding,
    )
    _collect_model_findings(
        root=stage_root / "triggers" / "dispatch",
        model_type=DispatchReceiptV1,
        evaluator=_stale_dispatch_finding,
    )
    _collect_model_findings(
        root=stage_root / "triggers" / "reporting",
        model_type=ReportingMetadataV2,
        evaluator=_stale_reporting_finding,
    )
    _collect_model_findings(
        root=stage_root / "triggers" / "leases",
        model_type=LeaseRecordV2,
        evaluator=_stale_lease_finding,
    )

    dumps_root = stage_root / "log-dumps"
    if dumps_root.is_dir():
        for path in sorted(dumps_root.glob("*.txt")):
            if not path.is_file():
                continue
            updated_at = _path_instant(path)
            age_hours = _age_hours(now=now, updated_at=updated_at)
            if age_hours > float(older_than_hours):
                findings.append(
                    DoctorFinding(
                        kind="stale_log_dump",
                        path=str(path),
                        detail="old failure log dump",
                        workflow_run_id=path.stem,
                        age_hours=age_hours,
                    )
                )

    if invalid_findings:
        return DoctorReport(
            exit_code=2,
            mode="scan_stale",
            needs_reconciliation=True,
            findings=invalid_findings,
            summary={"older_than_hours": older_than_hours, "invalid_artifact_count": len(invalid_findings)},
        )
    return DoctorReport(
        exit_code=1 if findings else 0,
        mode="scan_stale",
        needs_reconciliation=bool(findings),
        findings=findings,
        summary={"older_than_hours": older_than_hours, "finding_count": len(findings)},
    )


def format_report(report: DoctorReport) -> list[str]:
    if not report.findings:
        if report.mode == "workflow_run":
            wid = str(report.summary.get("workflow_run_id") or "").strip()
            return [f"OK: no reconciliation required for workflow_run_id={wid}"]
        return ["OK: no stale control-plane residue detected"]

    lines: list[str] = []
    if report.mode == "workflow_run":
        wid = str(report.summary.get("workflow_run_id") or "").strip()
        lines.append(f"NEEDS RECONCILIATION: workflow_run_id={wid}")
    else:
        hours = report.summary.get("older_than_hours")
        lines.append(f"STALE CONTROL-PLANE ARTIFACTS (> {hours}h)")
    for finding in report.findings:
        age = f" age_hours={finding.age_hours:.2f}" if finding.age_hours is not None else ""
        wid = f" workflow_run_id={finding.workflow_run_id}" if finding.workflow_run_id else ""
        lines.append(f"- {finding.kind}:{wid}{age} path={finding.path} detail={finding.detail}")
    return lines


def _stale_finalization_finding(
    path: Path,
    record: FinalizationRecordV2,
    now: Instant,
    older_than_hours: int,
) -> DoctorFinding | None:
    updated_at = _best_instant(path=path, preferred_iso=record.updated_at, fallback_iso=record.prepared_at)
    age_hours = _age_hours(now=now, updated_at=updated_at)
    if age_hours <= float(older_than_hours):
        return None
    if not record.needs_reconciliation and record.state == FinalizationState.PROMOTION_COMMITTED:
        return None
    return DoctorFinding(
        kind="stale_finalization",
        path=str(path),
        detail=record.reconciliation_reason or record.state.value,
        workflow_run_id=record.workflow_run_id,
        age_hours=age_hours,
    )


def _stale_dispatch_finding(
    path: Path,
    receipt: DispatchReceiptV1,
    now: Instant,
    older_than_hours: int,
) -> DoctorFinding | None:
    updated_at = _best_instant(path=path, preferred_iso=receipt.updated_at, fallback_iso=receipt.created_at)
    age_hours = _age_hours(now=now, updated_at=updated_at)
    if age_hours <= float(older_than_hours):
        return None
    if receipt.state == DispatchReceiptState.STARTED:
        return None
    return DoctorFinding(
        kind="stale_dispatch_receipt",
        path=str(path),
        detail=receipt.state.value,
        workflow_run_id=receipt.workflow_run_id,
        age_hours=age_hours,
    )


def _stale_reporting_finding(
    path: Path,
    metadata: ReportingMetadataV2,
    now: Instant,
    older_than_hours: int,
) -> DoctorFinding | None:
    updated_at = _best_instant(path=path, preferred_iso=metadata.started_at, fallback_iso="")
    age_hours = _age_hours(now=now, updated_at=updated_at)
    if age_hours <= float(older_than_hours):
        return None
    return DoctorFinding(
        kind="stale_reporting_metadata",
        path=str(path),
        detail="reporting metadata still present",
        workflow_run_id=path.stem,
        age_hours=age_hours,
    )


def _stale_lease_finding(
    path: Path,
    lease: LeaseRecordV2,
    now: Instant,
    older_than_hours: int,
) -> DoctorFinding | None:
    updated_at = _best_instant(path=path, preferred_iso=lease.acquired_at, fallback_iso="")
    age_hours = _age_hours(now=now, updated_at=updated_at)
    if age_hours <= float(older_than_hours):
        return None
    return DoctorFinding(
        kind="stale_lease",
        path=str(path),
        detail=lease.lease_key,
        workflow_run_id=lease.workflow_run_id,
        age_hours=age_hours,
    )


def _load_lease_records_for_workflow(*, stage_root: Path, workflow_run_id: str) -> list[tuple[Path, LeaseRecordV2]]:
    root = stage_root / "triggers" / "leases"
    if not root.is_dir():
        return []
    matches: list[tuple[Path, LeaseRecordV2]] = []
    for path in sorted(root.glob("*.json")):
        if not path.is_file():
            continue
        record = _load_optional_model(path, LeaseRecordV2)
        if record is not None and record.workflow_run_id == workflow_run_id:
            matches.append((path, record))
    return matches


def _load_optional_model[TModel: BaseModel](path: Path, model_type: type[TModel]) -> TModel | None:
    if not path.is_file():
        return None
    return _load_required_model(path, model_type)


def _load_required_model[TModel: BaseModel](path: Path, model_type: type[TModel]) -> TModel:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UnreadableArtifactError(f"{path}: {exc}") from exc
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        raise UnreadableArtifactError(f"{path}: {exc}") from exc


def _parse_instant(raw: str) -> Instant | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return Instant.parse_iso(text)
    except ValueError:
        return None


def _path_instant(path: Path) -> Instant:
    return Instant.from_timestamp(path.stat().st_mtime)


def _best_instant(*, path: Path, preferred_iso: str, fallback_iso: str) -> Instant:
    return _parse_instant(preferred_iso) or _parse_instant(fallback_iso) or _path_instant(path)


def _age_hours(*, now: Instant, updated_at: Instant) -> float:
    return round(float((now - updated_at).in_seconds()) / 3600.0, 3)
