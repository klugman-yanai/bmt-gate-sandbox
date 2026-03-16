"""Callable entry points for watcher, orchestrator, Cloud Run task, and coordinator (L5).

These accept typed config objects and bridge to the existing implementation.
Watcher/orchestrator delegate to vm_watcher and root_orchestrator.
Task and coordinator implement the Cloud Run execution model: task reads trigger,
runs one leg, writes summary artifact; coordinator reads all summaries,
aggregates verdicts, posts status/Check Run, updates pointers, cleans up.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from google.cloud import secretmanager

from gcp.image.config.constants import DECISION_ACCEPTED, REASON_PARTIAL_MISSING
from gcp.image.coordinator import summary_artifact_path
from gcp.image.entrypoint_config import (
    CoordinatorEntrypointConfig,
    OrchestratorConfig,
    TaskConfig,
    WatcherConfig,
)
from gcp.image.gcs_helpers import _gcloud_download_json, _gcloud_rm, _gcloud_upload_json
from gcp.image.trigger_pipeline import download_trigger, resolve_legs, split_legs
from gcp.image.utils import _bucket_uri, _runtime_bucket_root

logger = logging.getLogger(__name__)


def run_watcher(config: WatcherConfig) -> int:
    """Run the trigger watcher. Bridges typed config to vm_watcher.main()."""
    # Ensure env vars that vm_watcher and downstream code read are set
    os.environ.setdefault("GCS_BUCKET", config.bucket)
    os.environ.setdefault("BMT_REPO_ROOT", str(config.repo_root))
    if config.gcp_project:
        os.environ.setdefault("GCP_PROJECT", config.gcp_project)
    os.environ.setdefault("BMT_WORKSPACE_ROOT", str(config.workspace_root))
    if not config.self_stop:
        os.environ["BMT_SELF_STOP"] = "0"

    # Build an argparse.Namespace matching what vm_watcher.main() expects
    args = argparse.Namespace(
        bucket=config.bucket,
        poll_interval_sec=config.poll_interval_sec,
        workspace_root=str(config.workspace_root),
        exit_after_run=config.exit_after_run,
        idle_timeout_sec=config.idle_timeout_sec,
        subscription=config.subscription,
        gcp_project=config.gcp_project,
    )

    # Patch vm_watcher.parse_args to return our pre-built args, then call main()
    from gcp.image import vm_watcher

    _original_parse = vm_watcher.parse_args
    vm_watcher.parse_args = lambda: args  # type: ignore[assignment]
    try:
        return vm_watcher.main()
    finally:
        vm_watcher.parse_args = _original_parse  # type: ignore[assignment]


def run_orchestrator(config: OrchestratorConfig) -> int:
    """Run a single BMT leg. Bridges typed config to root_orchestrator."""
    os.environ.setdefault("GCS_BUCKET", config.bucket)
    os.environ.setdefault("BMT_REPO_ROOT", str(config.repo_root))

    from gcp.image import root_orchestrator

    # Build argparse.Namespace matching root_orchestrator expectations
    args = argparse.Namespace(
        bucket=config.bucket,
        project=config.project,
        bmt_id=config.bmt_id,
        run_id=config.run_id,
        workspace_root=str(config.workspace_root),
        run_context=config.run_context,
        summary_out=str(config.summary_out),
        human=False,
        leg_index=None,
        workflow_run_id=None,
    )

    # root_orchestrator.main() uses parse_args internally; patch it
    _original_parse = root_orchestrator.parse_args
    root_orchestrator.parse_args = lambda: args  # type: ignore[assignment]
    try:
        return root_orchestrator.main()
    finally:
        root_orchestrator.parse_args = _original_parse  # type: ignore[assignment]


def run_task(config: TaskConfig) -> int:
    """Cloud Run task: read trigger from GCS, select leg by CLOUD_RUN_TASK_INDEX, run manager, write summary artifact.

    Flow:
    1. Build trigger URI from config.bucket + config.trigger_object, download trigger.
    2. Resolve legs; select leg at config.task_index.
    3. If leg is rejected or index out of range, write a failure summary artifact and return non-zero.
    4. Run orchestrator for that leg (invokes manager, writes local summary).
    5. Read root summary from workspace, ensure it has "status" for aggregation, upload to
       triggers/summaries/<workflow_run_id>/<project>-<bmt_id>.json.
    """
    os.environ.setdefault("GCS_BUCKET", config.bucket)
    os.environ.setdefault("BMT_REPO_ROOT", str(config.repo_root))

    bucket_root = _runtime_bucket_root(config.bucket)
    trigger_uri = _bucket_uri(bucket_root, config.trigger_object)
    trigger = download_trigger(trigger_uri)
    if not trigger:
        logger.error("Failed to download trigger %s", trigger_uri)
        return 1

    workflow_run_id = (trigger.get("workflow_run_id") or "").strip() or "?"
    requested_legs = resolve_legs(trigger, config.repo_root)

    if config.task_index >= len(requested_legs):
        logger.error("task_index %s out of range (legs=%s)", config.task_index, len(requested_legs))
        wrote = _write_rejected_summary_artifact(
            bucket_root, workflow_run_id, config.task_index, requested_legs, "task_index_out_of_range"
        )
        # Keep Cloud Run execution successful when a summary artifact exists.
        return 0 if wrote else 1

    leg = requested_legs[config.task_index]
    if leg.get("decision") != DECISION_ACCEPTED:
        wrote = _write_rejected_summary_artifact(
            bucket_root, workflow_run_id, config.task_index, [leg], leg.get("reason") or "rejected"
        )
        # Keep Cloud Run execution successful when a summary artifact exists.
        return 0 if wrote else 1

    project = str(leg.get("project", "?"))
    bmt_id = str(leg.get("bmt_id", "?"))
    run_id = str(leg.get("run_id", "?"))
    run_context = config.run_context
    if run_context == "ci":
        run_context = "pr"

    orch_cfg = OrchestratorConfig(
        bucket=config.bucket,
        project=project,
        bmt_id=bmt_id,
        run_id=run_id,
        workspace_root=config.workspace_root,
        repo_root=config.repo_root,
        run_context=run_context,
        summary_out=config.summary_out,
    )
    exit_code = run_orchestrator(orch_cfg)

    summary = _read_task_summary_after_orchestrator(config.workspace_root, project, bmt_id, config.summary_out)
    if summary is None:
        summary = _make_failure_summary(
            bucket=config.bucket,
            project=project,
            bmt_id=bmt_id,
            run_id=run_id,
            run_context=config.run_context,
            manager_exit_code=exit_code,
            reason="no_summary_after_run",
        )
    elif "status" not in summary:
        summary["status"] = summary.get("manager_status") or ("pass" if summary.get("passed") else "fail")

    artifact_path = summary_artifact_path(workflow_run_id, project, bmt_id)
    artifact_uri = _bucket_uri(bucket_root, artifact_path)
    if not _gcloud_upload_json(artifact_uri, summary):
        logger.error("Failed to upload summary artifact %s", artifact_uri)
        return 1

    _task_update_check_run_progress(
        trigger=trigger,
        bucket_root=bucket_root,
        workflow_run_id=workflow_run_id,
        requested_legs=requested_legs,
    )

    # Task-level BMT verdict is represented in uploaded summary artifacts and finalized by coordinator.
    # Returning non-zero here aborts workflow before coordinator can aggregate and report.
    return 0


def _write_rejected_summary_artifact(
    bucket_root: str,
    workflow_run_id: str,
    task_index: int,
    requested_legs: list[dict[str, Any]],
    reason: str,
) -> bool:
    """Write a failure summary artifact for a rejected or out-of-range leg so coordinator can aggregate."""
    if task_index < len(requested_legs):
        leg = requested_legs[task_index]
        project = str(leg.get("project", "?"))
        bmt_id = str(leg.get("bmt_id", "?"))
        run_id = str(leg.get("run_id", "?"))
    else:
        project, bmt_id, run_id = "?", "?", "?"
    summary = _make_failure_summary(
        bucket=bucket_root.replace("gs://", "").split("/")[0] or "?",
        project=project,
        bmt_id=bmt_id,
        run_id=run_id,
        run_context="ci",
        manager_exit_code=1,
        reason=reason,
    )
    artifact_path = summary_artifact_path(workflow_run_id, project, bmt_id)
    artifact_uri = _bucket_uri(bucket_root, artifact_path)
    return _gcloud_upload_json(artifact_uri, summary)


def _make_failure_summary(
    *,
    bucket: str,
    project: str,
    bmt_id: str,
    run_id: str,
    run_context: str,
    manager_exit_code: int,
    reason: str,
) -> dict[str, Any]:
    """Build a root-summary-shaped dict for a failed or rejected leg."""
    from gcp.image.utils import _now_iso

    return {
        "timestamp": _now_iso(),
        "bucket": bucket,
        "project": project,
        "bmt_id": bmt_id,
        "run_context": run_context,
        "run_id": run_id,
        "workspace": "",
        "manager_exit_code": manager_exit_code,
        "passed": False,
        "manager_status": "fail",
        "status": "fail",
        "manager_reason_code": reason,
        "manager_verdict_uri": None,
        "manager_summary": None,
    }


def _read_task_summary_after_orchestrator(
    workspace_root: Path,
    project: str,
    bmt_id: str,
    summary_out: Path,
) -> dict[str, Any] | None:
    """Find the latest run_* dir for this leg and read the root summary JSON."""
    parent = workspace_root / project / bmt_id
    if not parent.is_dir():
        return None
    run_dirs = sorted(
        [d for d in parent.iterdir() if d.is_dir() and d.name.startswith("run_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not run_dirs:
        return None
    summary_path = run_dirs[0] / summary_out
    if not summary_path.is_file():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def run_coordinator_entrypoint(config: CoordinatorEntrypointConfig) -> int:  # noqa: C901, PLR0915
    """Coordinator: read all leg summaries from GCS, aggregate verdicts, post GitHub status/Check Run, update pointers, cleanup.

    Expects GITHUB_TOKEN (or equivalent) in env for posting status and Check Run.
    Flow:
    1. Read trigger from GCS for repository, sha, workflow_run_id.
    2. Resolve accepted legs; for each, download summary from triggers/summaries/<workflow_run_id>/<project>-<bmt_id>.json.
    3. If any summary is missing -> aggregate failure with reason partial_missing.
    4. Aggregate verdicts, build log dump URL from GCS snapshot logs if needed (best-effort).
    5. Create and complete Check Run with conclusion and output (including log dump link when failure).
    6. Update current.json pointers and clean stale snapshots per leg.
    7. Post commit status.
    8. Delete run trigger and trim workflow artifacts.
    """
    bucket_root = _runtime_bucket_root(config.bucket)
    trigger_uri = _bucket_uri(bucket_root, config.trigger_object)
    payload, err = _gcloud_download_json(trigger_uri)
    if err is not None or payload is None:
        logger.error("Coordinator: failed to read trigger %s", trigger_uri)
        return 1

    trigger = payload
    workflow_run_id = (trigger.get("workflow_run_id") or "").strip() or config.workflow_run_id
    repository = (trigger.get("repository") or "").strip()
    sha = (trigger.get("sha") or "").strip()
    pr_number = _coordinator_pr_number(trigger)

    requested_legs = resolve_legs(trigger, config.repo_root)
    accepted_legs, rejected_legs = split_legs(requested_legs)
    no_accepted_legs = not accepted_legs
    if no_accepted_legs:
        logger.warning("Coordinator: no accepted legs for run %s", workflow_run_id)
        leg_summaries: list[dict[str, Any] | None] = [
            _rejected_leg_summary(rejected_leg) for rejected_leg in rejected_legs
        ]
        if not leg_summaries:
            # Defensive fallback for malformed/empty trigger payloads.
            leg_summaries = [_partial_missing_summary("?", "?", workflow_run_id)]
        state, description = "failure", "No supported BMT legs were accepted for execution."
    else:
        leg_summaries = []
        for leg in accepted_legs:
            artifact_path = summary_artifact_path(workflow_run_id, leg.project, leg.bmt_id)
            artifact_uri = _bucket_uri(bucket_root, artifact_path)
            raw, _ = _gcloud_download_json(artifact_uri)
            if raw is None:
                logger.warning("Coordinator: missing summary for leg %s-%s", leg.project, leg.bmt_id)
                leg_summaries.append(_partial_missing_summary(leg.project, leg.bmt_id, leg.run_id))
            else:
                if "status" not in raw:
                    raw["status"] = raw.get("manager_status") or ("pass" if raw.get("passed") else "fail")
                leg_summaries.append(raw)
        state, description = _coordinator_aggregate(leg_summaries)
    runtime_bucket_root = bucket_root

    github_token = _coordinator_resolve_github_token(repository)

    def _token_resolver(repo: str) -> str | None:
        if github_token:
            return github_token
        return _coordinator_resolve_github_token(repo)

    gate_status_context = os.environ.get("BMT_STATUS_CONTEXT", "").strip() or str(
        trigger.get("status_context") or "BMT Gate"
    )
    run_id = workflow_run_id

    log_dump_url: str | None = None
    if state == "failure" and not no_accepted_legs:
        log_dump_url = _coordinator_log_dump_url(
            bucket_root=runtime_bucket_root,
            workspace_root=config.workspace_root,
            run_id=run_id,
            leg_summaries=leg_summaries,
        )

    existing_check_run_id = _find_check_run_id(
        token=github_token,
        repository=repository,
        sha=sha,
        check_name=gate_status_context,
    )

    if repository and sha and github_token:
        from gcp.image.github import github_checks
        from gcp.image.github_status import _finalize_check_run_resilient

        _check_run_id, _tok, _ = _finalize_check_run_resilient(
            token=github_token,
            repository=repository,
            sha=sha,
            status_context=gate_status_context,
            check_run_id=existing_check_run_id,
            conclusion="success" if state == "success" else "failure",
            output={
                "title": f"BMT Complete: {'PASS' if state == 'success' else 'FAIL'}",
                "summary": github_checks.render_results_table(
                    [s for s in leg_summaries if s is not None],
                    {"state": "PASS" if state == "success" else "FAIL", "decision": state, "reasons": []},
                    run_id=run_id,
                    runtime_bucket_root=runtime_bucket_root,
                    log_dump_url=log_dump_url,
                ),
            },
            token_resolver=_token_resolver,
        )
    elif repository and sha:
        logger.warning("Coordinator: GitHub token unavailable; skipping Check Run finalization for %s", repository)

    from gcp.image.coordinator import post_commit_status, update_pointers

    if not no_accepted_legs:
        update_pointers(runtime_bucket_root, leg_summaries)

    if repository and sha and github_token:
        post_commit_status(
            repository=repository,
            sha=sha,
            state=state,
            description=description,
            github_token=github_token,
            gate_status_context=gate_status_context,
            token_resolver=_token_resolver,
        )
    elif repository and sha:
        logger.warning("Coordinator: GitHub token unavailable; skipping commit status post for %s", repository)

    _coordinator_upsert_pr_comment(
        repository=repository,
        sha=sha,
        pr_number=pr_number,
        workflow_run_id=workflow_run_id,
        state=state,
        leg_summaries=leg_summaries,
        log_dump_url=log_dump_url,
        github_token=github_token,
    )

    _coordinator_cleanup(bucket_root, trigger_uri, workflow_run_id)
    return 0


def _coordinator_pr_number(trigger: dict[str, Any]) -> int | None:
    raw = trigger.get("pull_request_number")
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str) and raw.strip().isdigit():
        val = int(raw.strip())
        return val if val > 0 else None
    return None


def _coordinator_resolve_github_token(repository: str) -> str:
    project = os.environ.get("GCP_PROJECT", "").strip()
    if repository and project:
        _load_github_app_credentials_from_secret_manager(project, repository=repository)
        try:
            from gcp.image.github import github_auth

            return (github_auth.resolve_auth_for_repository(repository) or "").strip()
        except Exception:
            return ""
    # Legacy local fallback (disabled in Cloud Run by default).
    if os.environ.get("BMT_ALLOW_LEGACY_TOKEN_AUTH", "").strip().lower() in {"1", "true", "yes"}:
        token = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("BMT_GITHUB_TOKEN", "").strip()
        if token:
            return token
    return ""


def _github_request_json(
    *,
    token: str,
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Any | None:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8") or "null"
            return json.loads(text)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def _list_check_runs(token: str, repository: str, sha: str) -> list[dict[str, Any]]:
    if not (token and repository and sha):
        return []
    url = (
        f"https://api.github.com/repos/{repository}/commits/{sha}/check-runs"
        f"?filter=latest&per_page=100"
    )
    payload = _github_request_json(token=token, url=url)
    if not isinstance(payload, dict):
        return []
    runs = payload.get("check_runs")
    if not isinstance(runs, list):
        return []
    return [r for r in runs if isinstance(r, dict)]


def _find_check_run_id(token: str, repository: str, sha: str, check_name: str) -> int | None:
    runs = _list_check_runs(token, repository, sha)
    if not runs:
        return None
    for run in runs:
        if str(run.get("name") or "") != check_name:
            continue
        if str(run.get("status") or "") == "in_progress":
            rid = run.get("id")
            if isinstance(rid, int):
                return rid
    for run in runs:
        if str(run.get("name") or "") != check_name:
            continue
        rid = run.get("id")
        if isinstance(rid, int):
            return rid
    return None


def _secretmanager_location() -> str | None:
    explicit = os.environ.get("BMT_SECRETS_LOCATION", "").strip()
    if explicit:
        return explicit
    region = os.environ.get("GOOGLE_CLOUD_REGION", "").strip()
    return region or None


def _access_secret(secret_name: str, project: str, location: str | None) -> str:
    if location:
        name = f"projects/{project}/locations/{location}/secrets/{secret_name}/versions/latest"
    else:
        name = f"projects/{project}/secrets/{secret_name}/versions/latest"
    try:
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": name})
        payload = response.payload.data.decode("utf-8").strip()
        return payload
    except Exception as exc:
        logger.warning(
            "Secret access failed for %s (project=%s, location=%s): %s",
            secret_name,
            project,
            location or "<none>",
            exc,
        )
        return ""


def _load_github_app_prefix_from_secret_manager(prefix: str, project: str, location: str | None) -> None:
    app_id = _access_secret(f"{prefix}_ID", project, location)
    installation_id = _access_secret(f"{prefix}_INSTALLATION_ID", project, location)
    private_key = _access_secret(f"{prefix}_PRIVATE_KEY", project, location)
    if not (app_id and installation_id and private_key):
        return
    os.environ[f"{prefix}_ID"] = app_id
    os.environ[f"{prefix}_INSTALLATION_ID"] = installation_id
    os.environ[f"{prefix}_PRIVATE_KEY"] = private_key


def _load_github_app_credentials_from_secret_manager(project: str, repository: str | None = None) -> None:
    location = _secretmanager_location()
    prefixes: list[str] = []
    if repository:
        # Use repository mapping to load only the expected app credentials for this repo.
        try:
            from gcp.image.github import github_auth

            cfg_path = github_auth._resolve_config_path(None)  # type: ignore[attr-defined]
            config = github_auth.load_github_repos_config(cfg_path)
            repo_cfg = ((config or {}).get("repositories") or {}).get(repository, {})
            mapped = str((repo_cfg or {}).get("secret_prefix") or "").strip()
            if mapped:
                prefixes = [mapped]
        except Exception:
            prefixes = []
    if not prefixes:
        prefixes = ["GITHUB_APP_TEST", "GITHUB_APP_PROD"]
    for prefix in prefixes:
        _load_github_app_prefix_from_secret_manager(prefix, project, location)


def _task_update_check_run_progress(
    *,
    trigger: dict[str, Any],
    bucket_root: str,
    workflow_run_id: str,
    requested_legs: list[dict[str, Any]],
) -> None:
    repository = str(trigger.get("repository") or "").strip()
    sha = str(trigger.get("sha") or "").strip()
    if not repository or not sha:
        return
    status_context = str(trigger.get("status_context") or os.environ.get("BMT_STATUS_CONTEXT") or "BMT Gate")
    token = _coordinator_resolve_github_token(repository)
    if not token:
        return

    accepted: list[dict[str, Any]] = [leg for leg in requested_legs if leg.get("decision") == DECISION_ACCEPTED]
    total = len(accepted)
    if total <= 0:
        return
    completed = 0
    for leg in accepted:
        project = str(leg.get("project") or "")
        bmt_id = str(leg.get("bmt_id") or "")
        if not project or not bmt_id:
            continue
        artifact_path = summary_artifact_path(workflow_run_id, project, bmt_id)
        artifact_uri = _bucket_uri(bucket_root, artifact_path)
        payload, _err = _gcloud_download_json(artifact_uri)
        if payload is not None:
            completed += 1

    try:
        from gcp.image.github import github_checks

        summary = f"Cloud BMT progress: **{completed}/{total}** tasks complete."
        check_run_id = _find_check_run_id(token, repository, sha, status_context)
        if check_run_id is None:
            github_checks.create_check_run(
                token,
                repository,
                sha,
                name=status_context,
                status="in_progress",
                output={"title": "BMT In Progress", "summary": summary},
            )
            return
        github_checks.update_check_run(
            token,
            repository,
            check_run_id,
            status="in_progress",
            output={"title": "BMT In Progress", "summary": summary},
        )
    except Exception:
        logger.exception("Task progress check update failed")


def _coordinator_upsert_pr_comment(
    *,
    repository: str,
    sha: str,
    pr_number: int | None,
    workflow_run_id: str,
    state: str,
    leg_summaries: list[dict[str, Any] | None],
    log_dump_url: str | None,
    github_token: str,
) -> None:
    if not repository or not sha or pr_number is None or not github_token:
        return
    try:
        from gcp.image.coordinator import failed_legs_summary
        from gcp.image.github import github_pr_comment
        from gcp.image.verdict_aggregation import _comment_marker_for_sha, _format_bmt_comment

        if state == "success":
            result = "✅ Tests passed"
            summary_line = "All test suites passed."
            details_line = ""
        else:
            result = "❌ Tests failed"
            summary_line = failed_legs_summary(leg_summaries)
            details_line = "For details, open the **Checks** tab on this PR."
            if log_dump_url:
                details_line += f"\n\nLog dump (link expires in 3 days): {log_dump_url}"

        body = _format_bmt_comment(
            result=result,
            summary_line=summary_line,
            details_line=details_line,
            repository=repository,
            tested_sha=sha,
            workflow_run_id=workflow_run_id,
            pr_number=pr_number,
        )
        marker = _comment_marker_for_sha(sha)
        ok = github_pr_comment.upsert_pr_comment_by_marker(github_token, repository, pr_number, marker, body)
        if not ok:
            logger.warning("Coordinator: failed to upsert PR comment for %s#%s", repository, pr_number)
    except Exception:
        logger.exception("Coordinator: PR comment upsert failed")


def _partial_missing_summary(project: str, bmt_id: str, run_id: str) -> dict[str, Any]:
    """Build a summary dict for a missing leg (partial_missing)."""
    return {
        "project": project,
        "bmt_id": bmt_id,
        "run_id": run_id,
        "passed": False,
        "manager_status": "fail",
        "status": "fail",
        "manager_reason_code": REASON_PARTIAL_MISSING,
        "manager_verdict_uri": None,
        "manager_summary": None,
    }


def _rejected_leg_summary(rejected_leg: dict[str, Any]) -> dict[str, Any]:
    """Build a summary dict for a rejected leg so coordinator can finalize status deterministically."""
    project = str(rejected_leg.get("project") or "?")
    bmt_id = str(rejected_leg.get("bmt_id") or "?")
    run_id = str(rejected_leg.get("run_id") or "?")
    reason = str(rejected_leg.get("reason") or "rejected")
    return {
        "project": project,
        "bmt_id": bmt_id,
        "run_id": run_id,
        "passed": False,
        "manager_status": "fail",
        "status": "fail",
        "manager_reason_code": reason,
        "manager_verdict_uri": None,
        "manager_summary": None,
    }


def _coordinator_aggregate(leg_summaries: list[dict[str, Any] | None]) -> tuple[str, str]:
    """Aggregate verdicts from leg summaries; delegate to coordinator.aggregate_verdicts."""
    from gcp.image.coordinator import compute_verdicts

    return compute_verdicts(leg_summaries)


def _coordinator_log_dump_url(
    bucket_root: str,
    workspace_root: Path,
    run_id: str,
    leg_summaries: list[dict[str, Any] | None],
) -> str | None:
    """Best-effort: build log dump from GCS snapshot logs for failed legs and return signed URL. Option A (GCS-based)."""
    from gcp.image.coordinator import generate_log_dump

    return generate_log_dump(
        workspace_root=workspace_root,
        bucket=bucket_root.replace("gs://", "").split("/")[0] or "",
        runtime_bucket_root=bucket_root,
        run_id=run_id,
        leg_summaries=leg_summaries,
        latest_run_root_func=None,
    )


def _coordinator_cleanup(bucket_root: str, trigger_uri: str, workflow_run_id: str) -> None:
    """Delete run trigger and trim workflow artifacts."""
    _gcloud_rm(trigger_uri)
    from gcp.image.trigger_cleanup import _cleanup_workflow_artifacts

    _cleanup_workflow_artifacts(
        runtime_bucket_root=bucket_root,
        keep_workflow_ids={workflow_run_id},
    )
