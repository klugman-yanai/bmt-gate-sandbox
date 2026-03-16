"""Post-run coordination logic (L4 — imports from L0-L3 and L4 siblings, NOT from vm_watcher).

Encapsulates the steps that happen after all legs complete:
  1. Verdict aggregation
  2. Log dump generation (failure cases)
  3. GitHub Check Run finalization
  4. Pointer update and snapshot cleanup
  5. Commit status posting
  6. Trigger and workspace cleanup

Designed to be callable from vm_watcher, a CI post-step, or a Cloud Run coordinator job.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from gcp.image import log_config
from gcp.image.gcs_helpers import generate_signed_url
from gcp.image.github import github_checks
from gcp.image.github_status import (
    _finalize_check_run_resilient,
    _post_commit_status,
    _post_commit_status_resilient as _post_commit_status_resilient_impl,
)
from gcp.image.pointer_update import _update_pointer_and_cleanup
from gcp.image.trigger_pipeline import aggregate_verdicts
from gcp.image.utils import _now_iso
from gcp.image.verdict_aggregation import _failed_legs_display

# ---------------------------------------------------------------------------
# Verdict aggregation (thin re-export so callers import from coordinator)
# ---------------------------------------------------------------------------


def compute_verdicts(summaries: list[dict[str, Any] | None]) -> tuple[str, str]:
    """Aggregate manager summaries into (state, description). state: success|failure."""
    return aggregate_verdicts(summaries)


# ---------------------------------------------------------------------------
# Log dump generation
# ---------------------------------------------------------------------------


def generate_log_dump(
    *,
    workspace_root: Path,
    bucket: str,
    runtime_bucket_root: str,
    run_id: str,
    leg_summaries: list[dict[str, Any] | None],
    latest_run_root_func: Callable[[Path, str, str], Path | None] | None = None,
) -> str | None:
    """Collect logs for failed runner legs, upload to GCS, return signed URL (or None).

    On any non-success outcome with runner failures/timeouts, the coordinator:
    1. Collects recent watcher + orchestrator log content
    2. Appends per-leg runner log tails for failed legs
    3. Uploads concatenated content to GCS under log-dumps prefix
    4. Generates a signed URL (3-day expiry)
    """
    failed_runner_legs = [
        s
        for s in leg_summaries
        if s and (s.get("reason_code") or "") in ("runner_failures", "runner_timeout")
    ]
    if not failed_runner_legs:
        return None

    try:
        content_parts = [log_config.get_recent_log_content(workspace_root, include_orchestrator=True)]
        for summary in failed_runner_legs:
            proj = (summary.get("project_id") or summary.get("project") or "?").strip()
            bid = (summary.get("bmt_id") or "?").strip()
            run_root: Path | None = None
            if latest_run_root_func is not None:
                run_root = latest_run_root_func(workspace_root, proj, bid)
            if run_root is not None:
                log_config._append_runner_log_tail(run_root, content_parts)

        content_final = "\n".join(content_parts)
        if len(content_final.encode("utf-8")) > log_config.DUMP_TOTAL_MAX_BYTES:
            content_final = content_final.encode("utf-8")[: log_config.DUMP_TOTAL_MAX_BYTES].decode(
                "utf-8", errors="replace"
            )

        suffix = f"run_{run_id}_fail_{_now_iso().replace(':', '-').replace('.', '-')}"
        if log_config.dump_logs_to_gcs(bucket, runtime_bucket_root, suffix, content_final):
            info = log_config.log_dump_object_info(bucket, runtime_bucket_root, suffix)
            if info:
                return generate_signed_url(info[0], info[1])
    except Exception:  # noqa: S110 — best-effort log dump must not block run finalization
        pass
    return None


def generate_crash_log_dump(
    *,
    workspace_root: Path,
    bucket: str,
    runtime_bucket_root: str,
    run_id: str,
) -> str | None:
    """Upload a crash/error log dump to GCS. Returns signed URL or None."""
    try:
        content = log_config.get_recent_log_content(workspace_root, include_orchestrator=True)
        suffix = f"run_{run_id}_crash_{_now_iso().replace(':', '-').replace('.', '-')}"
        if log_config.dump_logs_to_gcs(bucket, runtime_bucket_root, suffix, content):
            info = log_config.log_dump_object_info(bucket, runtime_bucket_root, suffix)
            if info:
                return generate_signed_url(info[0], info[1])
    except Exception:  # noqa: S110 — best-effort log dump must not block run finalization
        pass
    return None


# ---------------------------------------------------------------------------
# GitHub Check Run finalization
# ---------------------------------------------------------------------------


def finalize_check_run(
    *,
    state: str,
    leg_summaries: list[dict[str, Any] | None],
    run_id: str,
    runtime_bucket_root: str,
    log_dump_url: str | None,
    github_token: str,
    repository: str,
    sha: str,
    runtime_status_context: str,
    check_run_id: int | None,
    token_resolver: Callable[[str], str | None],
) -> tuple[int | None, str, bool]:
    """Finalize the GitHub Check Run with results table and log dump link."""
    conclusion = "success" if state == "success" else "failure"
    return _finalize_check_run_resilient(
        token=github_token,
        repository=repository,
        sha=sha,
        status_context=runtime_status_context,
        check_run_id=check_run_id,
        conclusion=conclusion,
        output={
            "title": f"BMT Complete: {'PASS' if state == 'success' else 'FAIL'}",
            "summary": github_checks.render_results_table(
                [s for s in leg_summaries if s is not None],
                {
                    "state": "PASS" if state == "success" else "FAIL",
                    "decision": state,
                    "reasons": [],
                },
                run_id=run_id,
                runtime_bucket_root=runtime_bucket_root,
                log_dump_url=log_dump_url,
            ),
        },
        token_resolver=token_resolver,
    )


def finalize_check_run_cancelled(
    *,
    cancel_reason: str | None,
    superseded_by_sha: str | None,
    github_token: str,
    repository: str,
    sha: str,
    runtime_status_context: str,
    check_run_id: int | None,
    token_resolver: Callable[[str], str | None],
) -> tuple[int | None, str, bool]:
    """Finalize the GitHub Check Run as cancelled/neutral."""
    from gcp.image.verdict_aggregation import _short_sha

    check_summary = "Tests cancelled: pull request was closed."
    if cancel_reason == "superseded_by_new_commit":
        short_new = _short_sha(superseded_by_sha or "")
        check_summary = f"Tests cancelled: superseded by newer commit ({short_new})."

    return _finalize_check_run_resilient(
        token=github_token,
        repository=repository,
        sha=sha,
        status_context=runtime_status_context,
        check_run_id=check_run_id,
        conclusion="neutral",
        output={
            "title": "BMT Cancelled",
            "summary": check_summary,
        },
        token_resolver=token_resolver,
    )


def finalize_check_run_error(
    *,
    error_message: str,
    log_dump_url: str | None,
    github_token: str,
    repository: str,
    sha: str,
    runtime_status_context: str,
    check_run_id: int | None,
    token_resolver: Callable[[str], str | None],
) -> tuple[int | None, str, bool]:
    """Finalize the GitHub Check Run as failure due to an unhandled error."""
    summary = error_message
    if log_dump_url:
        summary += f"\n\nLog dump (link expires in 3 days): {log_dump_url}"

    return _finalize_check_run_resilient(
        token=github_token,
        repository=repository,
        sha=sha,
        status_context=runtime_status_context,
        check_run_id=check_run_id,
        conclusion="failure",
        output={
            "title": "BMT VM Error",
            "summary": summary,
        },
        token_resolver=token_resolver,
    )


# ---------------------------------------------------------------------------
# Pointer updates
# ---------------------------------------------------------------------------


def update_pointers(
    runtime_bucket_root: str,
    leg_summaries: list[dict[str, Any] | None],
) -> None:
    """Update current.json pointers and clean stale snapshots for each completed leg."""
    for summary in leg_summaries:
        if summary is not None:
            _update_pointer_and_cleanup(runtime_bucket_root, summary)


# ---------------------------------------------------------------------------
# Commit status posting
# ---------------------------------------------------------------------------


def post_commit_status(
    *,
    repository: str,
    sha: str,
    state: str,
    description: str,
    github_token: str,
    gate_status_context: str,
    token_resolver: Callable[[str], str | None],
) -> bool:
    """Post final commit status to GitHub with retries."""
    return _post_commit_status_resilient_impl(
        repository,
        sha,
        state,
        description,
        None,
        github_token,
        context=gate_status_context,
        token_resolver=token_resolver,
        attempts=3,
        _post_func=_post_commit_status,
    )


def post_commit_status_cancelled(
    *,
    repository: str,
    sha: str,
    cancel_reason: str | None,
    github_token: str,
    gate_status_context: str,
    token_resolver: Callable[[str], str | None],
) -> bool:
    """Post cancelled/error commit status to GitHub."""
    cancel_description = "Tests cancelled: pull request was closed."
    if cancel_reason == "superseded_by_new_commit":
        cancel_description = "Tests cancelled: superseded by a newer commit."
    return _post_commit_status_resilient_impl(
        repository,
        sha,
        "error",
        cancel_description,
        None,
        github_token,
        context=gate_status_context,
        token_resolver=token_resolver,
        attempts=3,
        _post_func=_post_commit_status,
    )


# ---------------------------------------------------------------------------
# Failed legs display (for PR comments)
# ---------------------------------------------------------------------------


def failed_legs_summary(leg_summaries: list[dict[str, Any] | None]) -> str:
    """Human-readable display of which legs failed (for PR comments)."""
    return _failed_legs_display(leg_summaries)
