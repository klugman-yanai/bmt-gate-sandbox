"""Trigger discovery and leg resolution for vm_watcher. Depends on gcs_helpers and utils."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from gcp.image.gcs_helpers import (
    _gcloud_download_json,
    _gcloud_exists,
    _gcloud_ls,
)
from gcp.image.utils import _bucket_uri

PROJECT_WIDE_BMT_IDS = frozenset({"", "*", "__all__", "all", "project_all", "__project_wide__"})

_RUN_ID_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _load_jobs_config_from_gcs(code_bucket_root: str, project: str) -> tuple[dict[str, Any] | None, str | None]:
    """Load per-project jobs config from code bucket.

    Returns (payload, error_reason_code).
    """
    jobs_uri = _bucket_uri(code_bucket_root, f"projects/{project}/bmt_jobs.json")
    result, err = _gcloud_download_json(jobs_uri)
    if result is None:
        reason = "jobs_schema_invalid" if err == "invalid_json" else "jobs_config_missing"
        return None, reason
    if not isinstance(result.get("bmts"), dict):
        return None, "jobs_schema_invalid"
    return result, None


def _safe_run_token(raw: str) -> str:
    token = _RUN_ID_SAFE.sub("-", raw.strip())
    token = token.strip("-._")
    return token or "bmt"


def _derive_leg_run_id(base_run_id: str, bmt_id: str, used: set[str]) -> str:
    """Build a deterministic unique run_id for one expanded BMT leg."""
    base = _safe_run_token(base_run_id) if base_run_id.strip() else "leg"
    suffix = _safe_run_token(bmt_id) if bmt_id.strip() else "bmt"
    candidate = f"{base}-{suffix}"
    if candidate not in used:
        used.add(candidate)
        return candidate
    idx = 2
    while True:
        alt = f"{candidate}-{idx}"
        if alt not in used:
            used.add(alt)
            return alt
        idx += 1


def _one_leg_dict(project: str, bmt_id: str, run_id: str, reason: str | None, index: int = 0) -> dict[str, Any]:
    return {
        "index": index,
        "project": project,
        "bmt_id": bmt_id,
        "run_id": run_id,
        "decision": "accepted" if reason is None else "rejected",
        "reason": reason,
    }


def _legs_from_jobs_payload(
    project: str,
    bmt_id_raw: str,
    run_id_base: str,
    *,
    project_wide: bool,
    bmts: dict[str, Any],
    used_run_ids: set[str],
) -> list[dict[str, Any]]:
    """Build list of leg dicts from resolved jobs bmts. Caller sets index."""
    out: list[dict[str, Any]] = []
    if project_wide:
        if not bmts:
            out.append(
                _one_leg_dict(
                    project, "?", _derive_leg_run_id(run_id_base, "empty-project", used_run_ids), "bmt_not_defined"
                )
            )
            return out
        for bmt_id_key in sorted(bmts):
            bmt_id = str(bmt_id_key).strip() or "?"
            run_id = _derive_leg_run_id(run_id_base, bmt_id, used_run_ids)
            bmt_cfg = bmts.get(bmt_id_key)
            if not isinstance(bmt_cfg, dict):
                reason = "jobs_schema_invalid"
            elif bmt_cfg.get("enabled", True) is False:
                reason = "bmt_disabled"
            else:
                reason = None
            out.append(_one_leg_dict(project, bmt_id, run_id, reason))
        return out
    bmt_id = bmt_id_raw or "?"
    run_id = _derive_leg_run_id(run_id_base, bmt_id, used_run_ids)
    bmt_cfg = bmts.get(bmt_id)
    if not isinstance(bmt_cfg, dict):
        reason = "bmt_not_defined"
    elif bmt_cfg.get("enabled", True) is False:
        reason = "bmt_disabled"
    else:
        reason = None
    out.append(_one_leg_dict(project, bmt_id, run_id, reason))
    return out


def _resolve_one_leg(
    raw_idx: int,
    leg: Any,
    code_bucket_root: str,
    manager_exists_cache: dict[str, bool],
    jobs_cache: dict[str, tuple[dict[str, Any] | None, str | None]],
    used_run_ids: set[str],
    exists: Callable[[str], bool],
    load_jobs: Callable[[str, str], tuple[dict[str, Any] | None, str | None]],
) -> list[dict[str, Any]]:
    """Resolve one raw leg into a list of leg dicts to append. Mutates caches and used_run_ids."""
    if not isinstance(leg, dict):
        return [_one_leg_dict("?", "?", f"leg-{raw_idx + 1}", "invalid_leg_type")]

    project = str(leg.get("project", "")).strip() or "?"
    bmt_id_raw = str(leg.get("bmt_id", "")).strip()
    run_id_base = str(leg.get("run_id", "")).strip() or f"leg-{raw_idx + 1}-{project}"
    request_scope = str(leg.get("request_scope", "")).strip().lower()
    project_wide = request_scope == "project_wide" or bmt_id_raw.lower() in PROJECT_WIDE_BMT_IDS
    fallback_bmt = (bmt_id_raw or "__all__") if project_wide else (bmt_id_raw or "?")

    if project == "?":
        return [
            _one_leg_dict(
                project, fallback_bmt, _derive_leg_run_id(run_id_base, bmt_id_raw or "invalid", used_run_ids), "invalid_leg_type"
            )
        ]

    if project not in manager_exists_cache:
        manager_uri = _bucket_uri(code_bucket_root, f"projects/{project}/bmt_manager.py")
        manager_exists_cache[project] = exists(manager_uri)
    if not manager_exists_cache[project]:
        return [
            _one_leg_dict(
                project, fallback_bmt, _derive_leg_run_id(run_id_base, bmt_id_raw or "manager-missing", used_run_ids), "manager_missing"
            )
        ]

    if project not in jobs_cache:
        jobs_cache[project] = load_jobs(code_bucket_root, project)
    jobs_payload, jobs_error = jobs_cache[project]
    if jobs_error is not None or jobs_payload is None:
        return [
            _one_leg_dict(
                project, fallback_bmt, _derive_leg_run_id(run_id_base, bmt_id_raw or "jobs-error", used_run_ids), jobs_error or "jobs_schema_invalid"
            )
        ]

    bmts = jobs_payload.get("bmts")
    if not isinstance(bmts, dict):
        return [
            _one_leg_dict(
                project, fallback_bmt, _derive_leg_run_id(run_id_base, bmt_id_raw or "jobs-schema", used_run_ids), "jobs_schema_invalid"
            )
        ]

    return _legs_from_jobs_payload(
        project, bmt_id_raw, run_id_base, project_wide=project_wide, bmts=bmts, used_run_ids=used_run_ids
    )


def _resolve_requested_legs(
    *,
    legs_raw: list[Any],
    code_bucket_root: str,
    _exists_func: Callable[[str], bool] | None = None,
    _load_jobs_func: Callable[[str, str], tuple[dict[str, Any] | None, str | None]] | None = None,
) -> list[dict[str, Any]]:
    """Resolve requested legs against VM runtime support by convention files.

    Supports project-wide request legs (request_scope=project_wide or bmt_id sentinel),
    expanding each project into all BMT entries from jobs config.

    Optional _exists_func and _load_jobs_func allow injection for tests (e.g. from vm_watcher).
    """
    exists = _exists_func if _exists_func is not None else _gcloud_exists
    load_jobs = _load_jobs_func if _load_jobs_func is not None else _load_jobs_config_from_gcs
    requested_legs: list[dict[str, Any]] = []
    manager_exists_cache: dict[str, bool] = {}
    jobs_cache: dict[str, tuple[dict[str, Any] | None, str | None]] = {}
    used_run_ids: set[str] = set()

    for raw_idx, leg in enumerate(legs_raw):
        legs = _resolve_one_leg(
            raw_idx,
            leg,
            code_bucket_root,
            manager_exists_cache,
            jobs_cache,
            used_run_ids,
            exists,
            load_jobs,
        )
        for i, leg_dict in enumerate(legs):
            leg_dict["index"] = len(requested_legs) + i
        requested_legs.extend(legs)

    return requested_legs


def _discover_run_triggers(runtime_bucket_root: str) -> list[str]:
    """List run trigger JSON files under triggers/runs/."""
    runs_uri = _bucket_uri(runtime_bucket_root, "triggers/runs/")
    all_objects = _gcloud_ls(runs_uri)
    return [uri for uri in all_objects if uri.endswith(".json")]


def _run_handshake_uri_from_trigger_uri(run_trigger_uri: str) -> str:
    """Map triggers/runs/<id>.json -> triggers/acks/<id>.json."""
    return run_trigger_uri.replace("/triggers/runs/", "/triggers/acks/", 1)
