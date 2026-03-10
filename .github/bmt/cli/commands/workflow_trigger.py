"""Preflight trigger queue cleanup (same logic as bmt_workflow.sh preflight-trigger-queue)."""

from __future__ import annotations

import contextlib
import os
from datetime import UTC, datetime
from pathlib import Path

from cli import gcs
from cli.shared import _workflow_run_id, _workflow_runtime_root


def _trigger_payload_is_valid(uri: str) -> bool:
    payload, err = gcs.download_json(uri)
    if not payload or err:
        return False
    wid = payload.get("workflow_run_id")
    if not (isinstance(wid, (str, int)) and str(wid)):
        return False
    repo = payload.get("repository")
    if not (isinstance(repo, str) and "/" in repo):
        return False
    sha = payload.get("sha")
    if not (
        isinstance(sha, str) and len(sha) == 40 and all(c in "0123456789abcdefABCDEF" for c in sha)
    ):
        return False
    ref = payload.get("ref")
    if not (isinstance(ref, str) and ref.startswith("refs/")):
        return False
    bucket = payload.get("bucket")
    if not (isinstance(bucket, str) and len(bucket) > 0):
        return False
    legs = payload.get("legs")
    if not isinstance(legs, list) or len(legs) == 0:
        return False
    for leg in legs:
        if not isinstance(leg, dict):
            return False
        if not (
            str(leg.get("project", "")).strip()
            and str(leg.get("bmt_id", "")).strip()
            and str(leg.get("run_id", "")).strip()
        ):
            return False
    return True


def _trigger_identity(uri: str) -> tuple[str, str, str]:
    payload, _ = gcs.download_json(uri)
    if not payload:
        return ("", "", "")
    repo = str(payload.get("repository", ""))
    ctx = str(payload.get("run_context", ""))
    pr = str(payload.get("pull_request_number", ""))
    return (repo, ctx, pr)


def _trigger_age_seconds(uri: str, *, now: datetime | None = None) -> int | None:
    """Return trigger age in seconds from payload.triggered_at, or None when unavailable/invalid."""
    payload, _ = gcs.download_json(uri)
    if not payload:
        return None
    raw = payload.get("triggered_at")
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    try:
        triggered_at = datetime.fromisoformat(value)
    except ValueError:
        return None
    if triggered_at.tzinfo is None:
        triggered_at = triggered_at.replace(tzinfo=UTC)
    now_ts = (now or datetime.now(UTC)).timestamp()
    age = int(now_ts - triggered_at.timestamp())
    return max(age, 0)


def _gcs_rm_idempotent(uri: str) -> str:
    """Return 'removed' or 'missing'. Raise on real error."""
    try:
        gcs.delete_object(uri)
        return "removed"
    except gcs.GcsError as e:
        if "404" in str(e) or "not found" in str(e).lower():
            return "missing"
        raise


def _trim_trigger_family_keep_recent(prefix_uri: str, keep_recent: int) -> int:
    uris = [u for u in gcs.list_prefix(prefix_uri) if u.endswith(".json")]
    if not uris:
        return 0
    run_ids = []
    for u in uris:
        name = u.split("/")[-1].replace(".json", "")
        if name:
            run_ids.append(name)
    run_ids.sort(reverse=True)
    keep_ids = run_ids[:keep_recent]
    keep_set = set(keep_ids)
    removed = 0
    for u in uris:
        rid = u.split("/")[-1].replace(".json", "")
        if rid not in keep_set:
            with contextlib.suppress(gcs.GcsError):
                gcs.delete_object(u)
                removed += 1
    return removed


def run_preflight_trigger_queue() -> None:
    run_id = _workflow_run_id()
    run_context = os.environ.get("RUN_CONTEXT", "dev")
    preempt_raw = (os.environ.get("BMT_PREEMPT_ON_PR_STALE_QUEUE") or "1").strip().lower()
    preempt_on_pr = preempt_raw in ("1", "true", "yes", "on")
    stale_sec = int(os.environ.get("BMT_TRIGGER_STALE_SEC", "900"))
    keep_recent = max(1, int(os.environ.get("BMT_TRIGGER_METADATA_KEEP_RECENT", "2")))
    root = _workflow_runtime_root()
    runs_prefix = f"{root}/triggers/runs/"
    current_uri = f"{runs_prefix}{run_id}.json"

    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise RuntimeError("GITHUB_OUTPUT is not set")
    out = Path(path)
    with out.open("a", encoding="utf-8") as f:
        f.write("restart_vm=false\nstale_cleanup_count=0\n")

    existing = [u for u in gcs.list_prefix(runs_prefix) if u.endswith(".json")]
    blocking = []
    invalid = []
    for uri in existing:
        if uri == current_uri:
            continue
        if _trigger_payload_is_valid(uri):
            blocking.append(uri)
        else:
            invalid.append(uri)

    invalid_removed = invalid_missing = invalid_failed = 0
    for uri in invalid:
        try:
            outcome = _gcs_rm_idempotent(uri)
            if outcome == "removed":
                invalid_removed += 1
            else:
                invalid_missing += 1
        except gcs.GcsError:
            invalid_failed += 1
        rid = uri.split("/")[-1].replace(".json", "")
        for sub in ("acks", "status"):
            with contextlib.suppress(gcs.GcsError):
                gcs.delete_object(f"{root}/triggers/{sub}/{rid}.json")

    if invalid_removed or invalid_missing or invalid_failed:
        print(f"::notice::Invalid trigger cleanup: removed={invalid_removed} missing={invalid_missing} failed={invalid_failed}")
    if invalid_failed > 0:
        raise RuntimeError(
            f"Failed to remove {invalid_failed} invalid trigger file(s) under {runs_prefix}. "
            "Ensure the workflow service account has storage.objects.delete on the bucket."
        )

    if not blocking:
        pass  # No summary when no action required.
    elif run_context == "pr" and preempt_on_pr:
        current_pr = os.environ.get("PR_NUMBER", "").strip()
        current_repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
        same_pr_blocking = []
        preserved_blocking = []
        for uri in blocking:
            repo, ctx, pr = _trigger_identity(uri)
            if ctx == "pr" and repo == current_repo and pr == current_pr:
                same_pr_blocking.append(uri)
            else:
                preserved_blocking.append(uri)

        if same_pr_blocking:
            print(f"::notice::Same-PR stale triggers to remove: {len(same_pr_blocking)}")
        if preserved_blocking:
            print(f"::notice::Preserved queue entries (different PR): {len(preserved_blocking)}")

        removed = missing = failed = 0
        for uri in same_pr_blocking:
            try:
                outcome = _gcs_rm_idempotent(uri)
                if outcome == "removed":
                    removed += 1
                else:
                    missing += 1
            except gcs.GcsError:
                failed += 1
            rid = uri.split("/")[-1].replace(".json", "")
            for sub in ("acks", "status"):
                with contextlib.suppress(gcs.GcsError):
                    gcs.delete_object(f"{root}/triggers/{sub}/{rid}.json")

        with out.open("a", encoding="utf-8") as f:
            f.write(f"stale_cleanup_count={removed}\n")
            if removed > 0:
                f.write("restart_vm=true\n")

        if same_pr_blocking:
            restart = "yes" if removed > 0 else "no"
            print(f"::notice::Preflight cleanup: removed={removed} missing={missing} failed={failed} preserved={len(preserved_blocking)} restart_vm={restart}")
        if failed > 0:
            raise RuntimeError(
                f"Failed to remove {failed} same-PR stale trigger file(s) under {runs_prefix}. "
                "Ensure the workflow service account has storage.objects.delete on the bucket."
            )
    else:
        if run_context == "pr" and not preempt_on_pr:
            return

        stale_blocking: list[str] = []
        preserved_blocking = 0
        now = datetime.now(UTC)
        for uri in blocking:
            age_sec = _trigger_age_seconds(uri, now=now)
            if age_sec is not None and age_sec >= stale_sec:
                stale_blocking.append(uri)
            else:
                preserved_blocking += 1

        if stale_blocking:
            print(
                f"::notice::Removing {len(stale_blocking)} stale trigger(s) "
                f"(threshold={stale_sec}s)."
            )
        if preserved_blocking:
            print(
                f"::notice::Preserved {preserved_blocking} active/unknown-age trigger(s); "
                "will not delete in-flight non-PR queue entries."
            )

        removed = missing = failed = 0
        for uri in stale_blocking:
            try:
                outcome = _gcs_rm_idempotent(uri)
                if outcome == "removed":
                    removed += 1
                else:
                    missing += 1
            except gcs.GcsError:
                failed += 1
            rid = uri.split("/")[-1].replace(".json", "")
            for sub in ("acks", "status"):
                with contextlib.suppress(gcs.GcsError):
                    gcs.delete_object(f"{root}/triggers/{sub}/{rid}.json")

        with out.open("a", encoding="utf-8") as f:
            f.write(f"stale_cleanup_count={removed}\n")
            if removed > 0:
                f.write("restart_vm=true\n")

        restart = "yes" if removed > 0 else "no"
        print(
            f"::notice::Preflight cleanup: removed={removed} missing={missing} failed={failed} "
            f"preserved={preserved_blocking} restart_vm={restart}"
        )
        if failed > 0:
            raise RuntimeError(
                f"Failed to remove {failed} stale trigger file(s) under {runs_prefix}. "
                "Ensure the workflow service account has storage.objects.delete on the bucket."
            )

    remaining = [u for u in gcs.list_prefix(runs_prefix) if u.endswith(".json")]
    if remaining:
        trim_runs = 0
    else:
        trim_runs = _trim_trigger_family_keep_recent(f"{root}/triggers/runs/", keep_recent)
    trim_acks = _trim_trigger_family_keep_recent(f"{root}/triggers/acks/", keep_recent)
    trim_status = _trim_trigger_family_keep_recent(f"{root}/triggers/status/", keep_recent)
    total_trimmed = trim_runs + trim_acks + trim_status
    if total_trimmed > 0:
        print(f"::notice::Metadata trim: runs={trim_runs} acks={trim_acks} status={trim_status} total={total_trimmed}")
