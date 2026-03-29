"""Transactional coordinator finalization state and results-path lease helpers."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from bmtcontract.constants import ENV_BMT_GCS_BUCKET_NAME, ENV_GCS_BUCKET, FUSE_MOUNT_ROOT
from bmtcontract.models import FinalizationRecordV2, FinalizationState, LeaseRecordV2
from bmtcontract.paths import finalization_record_path, lease_object_path, results_path_lease_key
from google.api_core import exceptions as google_api_exceptions
from google.cloud import storage as gcs_storage

from backend.runtime.artifacts import now_iso

logger = logging.getLogger(__name__)


class LeaseAcquisitionError(RuntimeError):
    """Raised when a coordinator cannot acquire exclusive promotion ownership."""


@dataclass(frozen=True, slots=True)
class LeaseHandle:
    lease_key: str
    results_path: str
    workflow_run_id: str
    local_path: Path | None = None
    bucket_name: str | None = None
    blob_name: str | None = None
    generation: int | None = None


def load_optional_finalization_record(*, stage_root: Path, workflow_run_id: str) -> FinalizationRecordV2 | None:
    path = stage_root / finalization_record_path(workflow_run_id)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return FinalizationRecordV2.model_validate(payload)


def write_finalization_record(*, stage_root: Path, record: FinalizationRecordV2) -> Path:
    path = stage_root / finalization_record_path(record.workflow_run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def update_finalization_record(
    *,
    stage_root: Path,
    workflow_run_id: str,
    repository: str,
    head_sha: str,
    state: FinalizationState,
    publish_required: bool,
    github_publish_complete: bool,
    promoted_results_paths: list[str],
    lease_keys: list[str],
    expected_leg_count: int = 0,
    present_summary_count: int = 0,
    missing_leg_keys: list[str] | None = None,
    extra_summary_keys: list[str] | None = None,
    needs_reconciliation: bool = False,
    reconciliation_reason: str = "",
    error_message: str = "",
    prepared_at: str = "",
) -> FinalizationRecordV2:
    existing = load_optional_finalization_record(stage_root=stage_root, workflow_run_id=workflow_run_id)
    record = FinalizationRecordV2(
        workflow_run_id=workflow_run_id,
        repository=repository,
        head_sha=head_sha,
        state=state,
        prepared_at=prepared_at or (existing.prepared_at if existing is not None else now_iso()),
        updated_at=now_iso(),
        publish_required=publish_required,
        github_publish_complete=github_publish_complete,
        promoted_results_paths=promoted_results_paths,
        lease_keys=lease_keys,
        expected_leg_count=expected_leg_count,
        present_summary_count=present_summary_count,
        missing_leg_keys=list(missing_leg_keys or []),
        extra_summary_keys=list(extra_summary_keys or []),
        needs_reconciliation=needs_reconciliation,
        reconciliation_reason=reconciliation_reason,
        error_message=error_message,
    )
    write_finalization_record(stage_root=stage_root, record=record)
    return record


def acquire_results_path_leases(
    *,
    stage_root: Path,
    workflow_run_id: str,
    results_paths: list[str],
    bucket_name: str = "",
) -> list[LeaseHandle]:
    handles: list[LeaseHandle] = []
    try:
        for results_path in sorted(set(results_paths)):
            handles.append(
                _acquire_single_lease(
                    stage_root=stage_root,
                    workflow_run_id=workflow_run_id,
                    results_path=results_path,
                    bucket_name=bucket_name,
                )
            )
    except Exception:
        release_results_path_leases(handles=handles)
        raise
    return handles


def release_results_path_leases(*, handles: list[LeaseHandle]) -> None:
    for handle in handles:
        try:
            if handle.local_path is not None:
                if handle.local_path.is_file():
                    handle.local_path.unlink()
                continue
            if handle.bucket_name and handle.blob_name and handle.generation is not None:
                blob = gcs_storage.Client().bucket(handle.bucket_name).blob(handle.blob_name)
                blob.delete(if_generation_match=handle.generation)
        except google_api_exceptions.NotFound:
            continue
        except (OSError, google_api_exceptions.GoogleAPIError):
            logger.warning(
                "failed to release results-path lease workflow_run_id=%s lease_key=%s",
                handle.workflow_run_id,
                handle.lease_key,
                exc_info=True,
            )


def _acquire_single_lease(
    *,
    stage_root: Path,
    workflow_run_id: str,
    results_path: str,
    bucket_name: str,
) -> LeaseHandle:
    lease_key = results_path_lease_key(results_path)
    record = LeaseRecordV2(
        lease_key=lease_key,
        workflow_run_id=workflow_run_id,
        results_path=results_path,
        acquired_at=now_iso(),
    )
    if _use_gcs_generation_leases(stage_root=stage_root, bucket_name=bucket_name):
        return _acquire_gcs_lease(bucket_name=bucket_name, record=record)
    return _acquire_local_lease(stage_root=stage_root, record=record)


def _use_gcs_generation_leases(*, stage_root: Path, bucket_name: str) -> bool:
    if not bucket_name.strip():
        return False
    try:
        return stage_root.resolve().as_posix().startswith(FUSE_MOUNT_ROOT)
    except OSError:
        return False


def _acquire_local_lease(*, stage_root: Path, record: LeaseRecordV2) -> LeaseHandle:
    path = stage_root / lease_object_path(record.lease_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(record.model_dump_json(indent=2) + "\n")
    except FileExistsError as exc:
        existing = _read_existing_local_lease(path=path)
        if existing is not None and existing.workflow_run_id == record.workflow_run_id:
            return LeaseHandle(
                lease_key=record.lease_key,
                results_path=record.results_path,
                workflow_run_id=record.workflow_run_id,
                local_path=path,
            )
        raise LeaseAcquisitionError(
            f"results-path lease already held lease_key={record.lease_key} results_path={record.results_path}"
        ) from exc
    return LeaseHandle(
        lease_key=record.lease_key,
        results_path=record.results_path,
        workflow_run_id=record.workflow_run_id,
        local_path=path,
    )


def _read_existing_local_lease(*, path: Path) -> LeaseRecordV2 | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return LeaseRecordV2.model_validate(payload)
    except Exception:
        return None


def _acquire_gcs_lease(*, bucket_name: str, record: LeaseRecordV2) -> LeaseHandle:
    client = gcs_storage.Client()
    blob_name = lease_object_path(record.lease_key)
    blob = client.bucket(bucket_name).blob(blob_name)
    payload = record.model_dump_json(indent=2) + "\n"
    try:
        blob.upload_from_string(payload, content_type="application/json", if_generation_match=0)
    except google_api_exceptions.PreconditionFailed as exc:
        existing = _read_existing_gcs_lease(bucket_name=bucket_name, blob_name=blob_name)
        if existing is not None and existing.workflow_run_id == record.workflow_run_id:
            blob.reload()
            return LeaseHandle(
                lease_key=record.lease_key,
                results_path=record.results_path,
                workflow_run_id=record.workflow_run_id,
                bucket_name=bucket_name,
                blob_name=blob_name,
                generation=int(blob.generation or 0),
            )
        raise LeaseAcquisitionError(
            f"results-path lease already held lease_key={record.lease_key} results_path={record.results_path}"
        ) from exc
    except google_api_exceptions.GoogleAPIError as exc:
        raise LeaseAcquisitionError(
            f"failed to create results-path lease lease_key={record.lease_key}: {exc}"
        ) from exc
    return LeaseHandle(
        lease_key=record.lease_key,
        results_path=record.results_path,
        workflow_run_id=record.workflow_run_id,
        bucket_name=bucket_name,
        blob_name=blob_name,
        generation=int(blob.generation or 0),
    )


def _read_existing_gcs_lease(*, bucket_name: str, blob_name: str) -> LeaseRecordV2 | None:
    try:
        data = gcs_storage.Client().bucket(bucket_name).blob(blob_name).download_as_text()
    except google_api_exceptions.GoogleAPIError:
        return None
    try:
        return LeaseRecordV2.model_validate_json(data)
    except Exception:
        return None


def resolve_stage_bucket_name(*, plan_bucket_name: str = "") -> str:
    return (
        plan_bucket_name.strip()
        or (os.environ.get(ENV_BMT_GCS_BUCKET_NAME) or "").strip()
        or (os.environ.get(ENV_GCS_BUCKET) or "").strip()
    )
