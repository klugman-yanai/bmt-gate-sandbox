"""current.json update and snapshot cleanup for vm_watcher. Depends on gcs_helpers and utils."""

from __future__ import annotations

from typing import Any

from gcp.image.gcs_helpers import (
    _gcloud_download_json,
    _gcloud_ls,
    _gcloud_rm,
    _gcloud_upload_json,
)
from gcp.image.utils import _bucket_uri, _now_iso


def _cleanup_legacy_result_history(bucket_root: str, results_prefix: str) -> None:
    """Delete legacy run-history prefixes no longer used by pointer/snapshot flow."""
    clean_prefix = results_prefix.strip("/")
    if not clean_prefix or "/results/" not in clean_prefix:
        return

    before_results, _, bmt_suffix = clean_prefix.partition("/results/")
    if not bmt_suffix:
        return
    base = f"{before_results}/results" if before_results else "results"
    legacy_prefixes = [
        f"{base}/archive",
        f"{base}/logs/{bmt_suffix}",
    ]
    for rel in legacy_prefixes:
        legacy_uri = _bucket_uri(bucket_root, rel)
        _gcloud_rm(legacy_uri, recursive=True)


def _results_prefix_from_ci_verdict_uri(bucket_root: str, ci_verdict_uri: str) -> str | None:
    """Derive results_prefix from manager summary ci_verdict_uri (snapshot path)."""
    uri = (ci_verdict_uri or "").strip()
    if not uri or not uri.startswith("gs://"):
        return None
    if "/snapshots/" not in uri:
        return None
    prefix = uri.split("/snapshots/")[0]
    root = bucket_root.rstrip("/")
    if not prefix.startswith(root):
        return None
    rel = prefix[len(root) :].lstrip("/")
    return rel or None


def _load_existing_pointer(current_uri: str) -> str | None:
    existing_raw, _ = _gcloud_download_json(current_uri)
    if not isinstance(existing_raw, dict):
        return None
    previous_last_passing = existing_raw.get("last_passing")
    if isinstance(previous_last_passing, str):
        return previous_last_passing.strip() or None
    return None


def _snapshot_run_ids(snapshots_prefix_uri: str, object_uris: list[str]) -> set[str]:
    seen: set[str] = set()
    for obj_uri in object_uris:
        if not obj_uri.startswith(snapshots_prefix_uri):
            continue
        rest = obj_uri[len(snapshots_prefix_uri) :].lstrip("/")
        parts = rest.split("/")
        if parts:
            seen.add(parts[0])
    return seen


def _update_pointer_and_cleanup(
    bucket_root: str,
    summary: dict[str, Any],
) -> None:
    """Update current.json for this leg and delete stale snapshots. No-op if no ci_verdict_uri."""
    ci_verdict_uri = (summary.get("ci_verdict_uri") or "").strip()
    if not ci_verdict_uri or "/snapshots/" not in ci_verdict_uri:
        return
    results_prefix = _results_prefix_from_ci_verdict_uri(bucket_root, ci_verdict_uri)
    if not results_prefix:
        return
    run_id = (summary.get("run_id") or "").strip()
    if not run_id:
        return
    passed = bool(summary.get("passed"))
    current_uri = _bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/current.json")
    previous_last_passing = _load_existing_pointer(current_uri)
    new_latest = run_id
    new_last_passing = run_id if passed else previous_last_passing
    new_pointer = {
        "latest": new_latest,
        "last_passing": new_last_passing,
        "updated_at": _now_iso(),
    }
    if not _gcloud_upload_json(current_uri, new_pointer):
        return
    referenced = {r for r in (new_latest, new_last_passing) if r}
    snapshots_prefix_uri = _bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/snapshots/")
    seen_run_ids = _snapshot_run_ids(snapshots_prefix_uri, _gcloud_ls(snapshots_prefix_uri, recursive=True))
    for run_id_to_delete in seen_run_ids:
        if run_id_to_delete in referenced:
            continue
        delete_prefix = _bucket_uri(bucket_root, f"{results_prefix.rstrip('/')}/snapshots/{run_id_to_delete}")
        _gcloud_rm(delete_prefix, recursive=True)
    _cleanup_legacy_result_history(bucket_root, results_prefix)
