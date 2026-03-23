"""Coordinator helpers for frozen plans and leg summaries."""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
from pathlib import Path

from pydantic import ValidationError
from whenever import Instant

from gcp.image.config.bmt_domain_status import BmtLegStatus, leg_status_is_pass
from gcp.image.runtime.models import ExecutionPlan, LegSummary, PlanLeg, ProgressRecord, ReportingMetadata

logger = logging.getLogger(__name__)

# Pointer / snapshot JSON keys (bucket layout under ``gcp/stage``).
_CURRENT_JSON_LATEST_KEY = "latest"
_SNAPSHOT_DURATION_SEC_KEY = "duration_sec"


def parse_optional_instant_iso(raw: str) -> Instant | None:
    """Parse ISO-8601 wall time; invalid input becomes ``None``."""
    with contextlib.suppress(ValueError):
        return Instant.parse_iso(raw.strip())
    return None


def aggregate_status(summaries: list[LegSummary]) -> str:
    """Overall leg verdict: fail if there are no legs (vacuous ``all()`` would wrongly pass)."""
    if not summaries:
        return BmtLegStatus.FAIL.value
    if all(leg_status_is_pass(summary.status) for summary in summaries):
        return BmtLegStatus.PASS.value
    return BmtLegStatus.FAIL.value


def plan_path(workflow_run_id: str) -> str:
    return f"triggers/plans/{workflow_run_id}.json"


def summary_path(workflow_run_id: str, project: str, bmt_slug: str) -> str:
    return f"triggers/summaries/{workflow_run_id}/{project}-{bmt_slug}.json"


def progress_path(workflow_run_id: str, project: str, bmt_slug: str) -> str:
    return f"triggers/progress/{workflow_run_id}/{project}-{bmt_slug}.json"


def reporting_metadata_path(workflow_run_id: str) -> str:
    return f"triggers/reporting/{workflow_run_id}.json"


def snapshot_root(leg: PlanLeg) -> str:
    return f"{leg.results_path}/snapshots/{leg.run_id}"


def latest_result_path(leg: PlanLeg) -> str:
    return f"{snapshot_root(leg)}/latest.json"


def verdict_result_path(leg: PlanLeg) -> str:
    return f"{snapshot_root(leg)}/ci_verdict.json"


def case_digest_result_path(leg: PlanLeg) -> str:
    return f"{snapshot_root(leg)}/case_digest.json"


def load_plan(*, stage_root: Path, workflow_run_id: str) -> ExecutionPlan:
    payload = json.loads((stage_root / plan_path(workflow_run_id)).read_text(encoding="utf-8"))
    return ExecutionPlan.model_validate(payload)


def write_plan(*, stage_root: Path, plan: ExecutionPlan) -> Path:
    path = stage_root / plan_path(plan.workflow_run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def write_summary(*, stage_root: Path, workflow_run_id: str, summary: LegSummary) -> Path:
    path = stage_root / summary_path(workflow_run_id, summary.project, summary.bmt_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def load_summary(*, stage_root: Path, workflow_run_id: str, project: str, bmt_slug: str) -> LegSummary:
    payload = json.loads((stage_root / summary_path(workflow_run_id, project, bmt_slug)).read_text(encoding="utf-8"))
    return LegSummary.model_validate(payload)


def write_progress(*, stage_root: Path, workflow_run_id: str, progress: ProgressRecord) -> Path:
    path = stage_root / progress_path(workflow_run_id, progress.project, progress.bmt_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(progress.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def load_progress(*, stage_root: Path, workflow_run_id: str, project: str, bmt_slug: str) -> ProgressRecord:
    payload = json.loads((stage_root / progress_path(workflow_run_id, project, bmt_slug)).read_text(encoding="utf-8"))
    return ProgressRecord.model_validate(payload)


def load_optional_progress(
    *, stage_root: Path, workflow_run_id: str, project: str, bmt_slug: str
) -> ProgressRecord | None:
    path = stage_root / progress_path(workflow_run_id, project, bmt_slug)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ProgressRecord.model_validate(payload)


def earliest_progress_started_at_iso(*, stage_root: Path, workflow_run_id: str) -> str | None:
    """Earliest leg ``started_at`` under ``triggers/progress/{workflow_run_id}/`` (by parsed instant).

    Used when reporting metadata exists but ``started_at`` was never persisted (legacy or merge-only
    writes) so check-run ETA can still compute elapsed time.
    """
    root = stage_root / "triggers" / "progress" / workflow_run_id
    if not root.is_dir():
        return None
    candidates: list[tuple[Instant, str]] = []
    for path in sorted(root.glob("*.json")):
        try:
            record = ProgressRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValidationError):
            continue
        ins = parse_optional_instant_iso(record.started_at)
        if ins is None:
            continue
        candidates.append((ins, record.started_at.strip()))
    if not candidates:
        return None
    return min(candidates, key=lambda pair: pair[0].timestamp())[1]


def write_reporting_metadata(*, stage_root: Path, workflow_run_id: str, metadata: ReportingMetadata) -> Path:
    path = stage_root / reporting_metadata_path(workflow_run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(metadata.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def load_observed_duration_sec_from_latest_snapshot(  # noqa: PLR0911
    *, stage_root: Path, leg: PlanLeg
) -> int | None:
    """Return ``duration_sec`` from the latest snapshot's ``latest.json`` under this leg's results tree.

    Used to estimate parallel-workflow ETA when no leg has finished in the current run yet. Requires
    ``duration_sec`` to have been written to ``latest.json`` (see task mode snapshot write).
    """
    results_root = stage_root / str(leg.results_path)
    current_path = results_root / "current.json"
    if not current_path.is_file():
        return None
    try:
        payload = json.loads(current_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("%s: invalid JSON; skipping duration hint", current_path)
        return None
    latest = payload.get(_CURRENT_JSON_LATEST_KEY)
    if not isinstance(latest, str) or not latest.strip():
        return None
    latest_json = results_root / "snapshots" / latest / "latest.json"
    if not latest_json.is_file():
        return None
    try:
        snap = json.loads(latest_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("%s: invalid JSON; skipping duration hint", latest_json)
        return None
    raw = snap.get(_SNAPSHOT_DURATION_SEC_KEY)
    if isinstance(raw, int) and raw > 0:
        return raw
    if isinstance(raw, float) and raw > 0:
        return int(raw)
    return None


def load_optional_reporting_metadata(*, stage_root: Path, workflow_run_id: str) -> ReportingMetadata | None:
    path = stage_root / reporting_metadata_path(workflow_run_id)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ReportingMetadata.model_validate(payload)


def read_existing_last_passing(results_root: Path) -> str | None:
    pointer_path = results_root / "current.json"
    if not pointer_path.is_file():
        return None
    try:
        payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("%s contains invalid JSON; treating as no baseline", pointer_path)
        return None
    last_passing = payload.get("last_passing")
    return str(last_passing).strip() if isinstance(last_passing, str) and str(last_passing).strip() else None


def write_current_pointer(*, results_root: Path, run_id: str, last_passing_run_id: str | None) -> None:
    pointer = {
        "latest": run_id,
        "last_passing": last_passing_run_id,
        "updated_at": Instant.now().format_iso(unit="second"),
    }
    results_root.mkdir(parents=True, exist_ok=True)
    (results_root / "current.json").write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")


def prune_snapshots(*, results_root: Path, keep_run_ids: set[str]) -> None:
    snapshots_dir = results_root / "snapshots"
    if not snapshots_dir.is_dir():
        return
    for entry in snapshots_dir.iterdir():
        if entry.name in keep_run_ids:
            continue
        if entry.is_dir():
            shutil.rmtree(entry)


def now_iso() -> str:
    return Instant.now().format_iso(unit="second")


def cleanup_ephemeral_triggers(*, stage_root: Path, plan: ExecutionPlan) -> None:
    """Delete coordinator-era ephemeral paths under ``triggers/`` for this workflow run.

    Call after ``publish_final_results`` when the run is complete. Safe on missing paths.
    Persistent project results under ``projects/`` are not touched.
    """
    wid = plan.workflow_run_id
    candidates: list[Path] = [
        stage_root / plan_path(wid),
        stage_root / reporting_metadata_path(wid),
        stage_root / "triggers" / "progress" / wid,
        stage_root / "triggers" / "summaries" / wid,
    ]
    for path in candidates:
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        except OSError as exc:
            logger.warning("ephemeral trigger cleanup failed path=%s error=%s", path, exc)
