"""Trigger/workflow metadata and stale cleanup for vm_watcher. Depends on gcs_helpers and utils."""

from __future__ import annotations

from collections.abc import Callable

from whenever import Instant

from gcp.image.config.bmt_config import STALE_TRIGGER_AGE_HOURS, TRIGGER_METADATA_KEEP_RECENT
from gcp.image.gcs_helpers import _gcloud_download_json, _gcloud_ls, _gcloud_rm
from gcp.image.utils import _bucket_uri


def _run_id_from_json_uri(uri: str) -> str | None:
    """Extract run ID from a trailing `<run_id>.json` object URI."""
    name = uri.rsplit("/", 1)[-1]
    if not name.endswith(".json"):
        return None
    run_id = name[:-5].strip()
    return run_id or None


def _workflow_run_sort_key(run_id: str) -> tuple[int, int | str]:
    """Sort run IDs newest-first by numeric value when possible, else lexicographically."""
    rid = run_id.strip()
    if rid.isdigit():
        return (1, int(rid))
    return (0, rid)


def _trim_trigger_family(
    family_prefix_uri: str,
    *,
    keep_ids: set[str],
    keep_recent: int = TRIGGER_METADATA_KEEP_RECENT,
) -> None:
    """Prune stale JSON objects in one trigger family and keep only recent + explicit IDs."""
    object_uris = [uri for uri in _gcloud_ls(family_prefix_uri) if uri.endswith(".json")]
    entries: list[tuple[str, str]] = []
    for uri in object_uris:
        run_id = _run_id_from_json_uri(uri)
        if run_id is None:
            continue
        entries.append((run_id, uri))
    if not entries:
        return

    normalized_keep = {rid.strip() for rid in keep_ids if rid and rid.strip()}
    sorted_entries = sorted(entries, key=lambda item: _workflow_run_sort_key(item[0]), reverse=True)
    recent_ids: list[str] = []
    for run_id, _ in sorted_entries:
        if run_id not in recent_ids:
            recent_ids.append(run_id)
        if len(recent_ids) >= max(keep_recent, 0):
            break
    retained_ids = normalized_keep.union(recent_ids)

    for run_id, uri in entries:
        if run_id in retained_ids:
            continue
        _gcloud_rm(uri)


def _cleanup_stale_run_triggers(
    runtime_bucket_root: str,
    *,
    stale_hours: int = STALE_TRIGGER_AGE_HOURS,
) -> None:
    """Delete run triggers older than stale_hours from triggers/runs/."""
    runs_uri = _bucket_uri(runtime_bucket_root, "triggers/runs/")
    trigger_uris = [uri for uri in _gcloud_ls(runs_uri) if uri.endswith(".json")]
    if not trigger_uris:
        return
    cutoff = Instant.now().timestamp() - stale_hours * 3600
    for uri in trigger_uris:
        payload, err = _gcloud_download_json(uri)
        if err is not None or payload is None:
            continue
        triggered_at_raw = payload.get("triggered_at")
        if not isinstance(triggered_at_raw, str):
            continue
        try:
            triggered_ts = Instant.parse_iso(triggered_at_raw.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            continue
        if triggered_ts < cutoff:
            _gcloud_rm(uri)


def _cleanup_workflow_artifacts(
    *,
    runtime_bucket_root: str,
    keep_workflow_ids: set[str],
    keep_recent: int = TRIGGER_METADATA_KEEP_RECENT,
    stale_hours: int = STALE_TRIGGER_AGE_HOURS,
    _trim_func: Callable[..., None] | None = None,
) -> None:
    """Keep workflow metadata families bounded to current + previous entries.

    Optional _trim_func allows injection for tests (e.g. from vm_watcher).
    """
    trim = _trim_func if _trim_func is not None else _trim_trigger_family
    if not runtime_bucket_root.strip():
        return

    _cleanup_stale_run_triggers(runtime_bucket_root, stale_hours=stale_hours)

    families = [
        _bucket_uri(runtime_bucket_root, "triggers/acks/"),
        _bucket_uri(runtime_bucket_root, "triggers/status/"),
    ]
    seen: set[str] = set()
    for family_uri in families:
        if family_uri in seen:
            continue
        seen.add(family_uri)
        trim(
            family_uri,
            keep_ids=keep_workflow_ids,
            keep_recent=keep_recent,
        )
