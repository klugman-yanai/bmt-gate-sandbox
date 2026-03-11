"""BMT workflow step commands (replace bmt_workflow.sh)."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from cli import gcs, github_api, shared
from cli.gh_output import gh_endgroup, gh_group, gh_notice, gh_warning
from cli.shared import (
    get_config,
    get_context,
    workflow_run_id,
    workflow_runtime_root,
    write_github_output,
)

if TYPE_CHECKING:
    from gcp.code.config.bmt_config import BmtContext


def _github_output() -> Path:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        raise RuntimeError("GITHUB_OUTPUT is not set")
    return Path(out)


def _append_step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        raise RuntimeError("GITHUB_STEP_SUMMARY is not set")
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(text)


def _ctx_str(w: object | None, attr: str, env_var: str, default: str = "") -> str:
    """Return attribute from workflow context w, or env var, stripped. Falls back to default."""
    if w is not None:
        return (getattr(w, attr, None) or default).strip()
    return (os.environ.get(env_var) or default).strip()


def _resolve_repository_and_sha(ctx: BmtContext | None) -> tuple[str, str]:
    """Return (repository, head_sha) from context or environment."""
    w = ctx.workflow if ctx is not None else None
    if w is not None:
        repository = (w.repository or w.github_repository or "").strip()
        head_sha = (w.head_sha or "").strip()
    else:
        repository = os.environ.get("REPOSITORY") or os.environ.get("GITHUB_REPOSITORY", "")
        head_sha = os.environ.get("HEAD_SHA", "")
    return repository, head_sha


# ---- Context (bmt-prepare) ----
# emit-bmt-context, validate-required-vars, guard-no-legacy-prefix are now inlined as shell in bmt-prepare/action.yml.


def run_write_context() -> None:
    """Write .bmt/context.json from current env so subsequent bmt commands read from file instead of env."""
    from gcp.code.config.bmt_config import context_from_env, get_context_path, write_context_to_file

    ctx = context_from_env(runtime=os.environ)
    path = get_context_path(runtime=os.environ)
    write_context_to_file(path, ctx)
    gh_notice(f"Wrote context to {path}")


def run_resolve_failure_context() -> None:
    path = _github_output()
    ctx = get_context()
    if ctx and ctx.workflow:
        w = ctx.workflow
        mode = "no_context" if (w.prepare_result or "").strip() == "failure" else "context"
        head_sha = (
            (w.prepare_head_sha or "").strip()
            or (w.dispatch_head_sha or "").strip()
            or (w.head_sha or "").strip()
            or os.environ.get("GITHUB_SHA", "")
        )
        pr_number = (w.prepare_pr_number or w.dispatch_pr_number or "").strip()
        vm_handshake_result = (
            "failure"
            if (
                (w.orch_has_legs or "").strip() == "true"
                and (w.orch_handshake_ok or "").strip() != "true"
            )
            else "success"
        )
        trigger_written = "true" if (w.orch_trigger_written or "").strip() == "true" else "false"
    else:
        mode = "no_context" if os.environ.get("PREPARE_RESULT") == "failure" else "context"
        head_sha = (
            os.environ.get("PREPARE_HEAD_SHA")
            or os.environ.get("DISPATCH_HEAD_SHA")
            or os.environ.get("GITHUB_SHA", "")
        )
        pr_number = (
            os.environ.get("PREPARE_PR_NUMBER") or os.environ.get("DISPATCH_PR_NUMBER") or ""
        )
        vm_handshake_result = (
            "failure"
            if (
                os.environ.get("ORCH_HAS_LEGS") == "true"
                and os.environ.get("ORCH_HANDSHAKE_OK") != "true"
            )
            else "success"
        )
        trigger_written = "true" if os.environ.get("ORCH_TRIGGER_WRITTEN") == "true" else "false"
    with path.open("a", encoding="utf-8") as f:
        f.write(f"mode={mode}\n")
        f.write(f"head_sha={head_sha}\n")
        f.write(f"pr_number={pr_number}\n")
        f.write(f"vm_handshake_result={vm_handshake_result}\n")
        f.write(f"trigger_written={trigger_written}\n")


# ---- Upload ----


def run_filter_upload_matrix() -> None:
    ctx = get_context()
    w = ctx.workflow if ctx is not None else None
    runner_matrix_raw = _ctx_str(w, "runner_matrix", "RUNNER_MATRIX")
    head_sha = _ctx_str(w, "head_sha", "HEAD_SHA")
    preseeded = _ctx_str(
        w, "bmt_runners_preseeded_in_gcs", "BMT_RUNNERS_PRESEEDED_IN_GCS"
    ).lower() in ("1", "true", "yes")
    available_artifacts_raw = _ctx_str(w, "available_artifacts", "AVAILABLE_ARTIFACTS", "[]")
    github_run_id = _ctx_str(w, "github_run_id", "GITHUB_RUN_ID") or workflow_run_id()

    if not runner_matrix_raw or not head_sha:
        raise RuntimeError("RUNNER_MATRIX and HEAD_SHA are required")
    matrix = json.loads(runner_matrix_raw)
    include = matrix.get("include", [])
    if not isinstance(include, list):
        raise TypeError("RUNNER_MATRIX.include must be a JSON array")
    try:
        available_artifacts = json.loads(available_artifacts_raw)
    except json.JSONDecodeError:
        available_artifacts = []
    if not isinstance(available_artifacts, list):
        available_artifacts = []
    artifact_set = {str(a).strip() for a in available_artifacts if str(a).strip()}

    root = workflow_runtime_root()
    run_id = github_run_id
    need_include: list[dict[str, str]] = []
    projects_written: set[str] = set()

    for entry in include:
        if not isinstance(entry, dict):
            continue
        project = str(entry.get("project", "")).strip()
        preset = str(entry.get("preset", "")).strip()
        if not project or not preset:
            continue
        meta_uri = f"{root}/{project}/runners/{preset}/runner_meta.json"
        payload, _ = gcs.download_json(meta_uri)
        if payload is not None:
            if preseeded:
                # Sandbox: runners already in GCS; treat as sufficient and write marker.
                if project not in projects_written:
                    marker_uri = f"{root}/_workflow/uploaded/{run_id}/{project}.json"
                    try:
                        gcs.write_object(marker_uri, "{}")
                    except gcs.GcsError as _marker_err:
                        gh_warning(f"Could not write uploaded marker {marker_uri}: {_marker_err}")
                    projects_written.add(project)
                print(
                    f"::notice::Preseeded GCS runner for {project}/{preset}: verified in GCS (will show as Skipped)."
                )
                continue
            if str(payload.get("source_ref", "")).strip() == head_sha:
                print(
                    f"::notice::Skip upload for {project}/{preset}: already on GCS for ref {head_sha[:7]} (will show as Skipped)."
                )
                if project not in projects_written:
                    marker_uri = f"{root}/_workflow/uploaded/{run_id}/{project}.json"
                    try:
                        gcs.write_object(marker_uri, "{}")
                    except gcs.GcsError as _marker_err:
                        gh_warning(f"Could not write uploaded marker {marker_uri}: {_marker_err}")
                    projects_written.add(project)
                continue
        if artifact_set and f"runner-{preset}" not in artifact_set:
            print(
                f"::notice::Skip upload for {project}/{preset}: artifact not in available list (will show as Skipped)."
            )
            continue
        need_include.append(entry)
    out = {"include": need_include}
    out_json = json.dumps(out, separators=(",", ":"))
    path = _github_output()
    keys = [f"{e['project']}|{e['preset']}" for e in need_include]
    with path.open("a", encoding="utf-8") as f:
        f.write(f"matrix_need_upload<<FILTER_EOF\n{out_json}\nFILTER_EOF\n")
        f.write(f"matrix_need_upload_keys={json.dumps(keys)}\n")
    need_count = len(need_include)
    total = len(include)
    print(
        f"::notice::Filter upload matrix: {need_count} job(s) need upload; "
        f"{total - need_count} already on GCS or no artifact (will show as Skipped)."
    )


# warn-artifact-missing is now inlined as shell in bmt.yml.


def run_upload_runner_to_gcs() -> None:
    from cli.commands import upload_runner

    runner_dir = Path("artifact/Runners")
    if (runner_dir / "kardome_runner").is_file():
        with contextlib.suppress(OSError):
            (runner_dir / "kardome_runner").chmod(0o755)
    upload_runner.run()


# warn-upload-failed and record-uploaded-project-marker are now inlined as shell in bmt.yml.


def run_resolve_uploaded_projects() -> None:
    run_id = workflow_run_id()
    root = workflow_runtime_root()
    prefix = f"{root}/_workflow/uploaded/{run_id}/"
    uris = gcs.list_prefix(prefix)
    uploaded_projects = {
        u.split("/")[-1].replace(".json", "").strip() for u in uris if u.endswith(".json")
    }

    # In sandbox/test flows, runner upload jobs can be intentionally skipped when
    # the runner is already present in the bucket. Accept projects that already
    # have runner metadata for the requested preset(s).
    ctx = get_context()
    w = ctx.workflow if ctx is not None else None
    runner_matrix_raw = _ctx_str(w, "runner_matrix", "RUNNER_MATRIX")
    if runner_matrix_raw:
        try:
            runner_matrix = json.loads(runner_matrix_raw)
            include = runner_matrix.get("include", []) if isinstance(runner_matrix, dict) else []
            if isinstance(include, list):
                for entry in include:
                    if not isinstance(entry, dict):
                        continue
                    project = str(entry.get("project", "")).strip()
                    preset = str(entry.get("preset", "")).strip()
                    if not project or not preset:
                        continue
                    meta_uri = f"{root}/{project}/runners/{preset}/runner_meta.json"
                    payload, _ = gcs.download_json(meta_uri)
                    if isinstance(payload, dict):
                        uploaded_projects.add(project)
        except json.JSONDecodeError as exc:
            gh_warning(f"Invalid RUNNER_MATRIX JSON; skipping GCS runner pre-scan: {exc}")

    names = sorted(uploaded_projects)
    accepted = json.dumps(names)
    Path("accepted.txt").write_text(accepted)
    write_github_output(os.environ.get("GITHUB_OUTPUT"), "accepted_projects", accepted)
    gh_notice(f"Runners uploaded for projects: {accepted}")


def run_summarize_matrix_handshake() -> None:
    ctx = get_context()
    w = ctx.workflow if ctx is not None else None
    runner_matrix_raw = _ctx_str(w, "runner_matrix", "RUNNER_MATRIX", "{}")
    accepted_raw = _ctx_str(w, "accepted", "ACCEPTED", "[]")
    filtered_raw = _ctx_str(w, "filtered_matrix", "FILTERED_MATRIX", "{}")
    if not runner_matrix_raw or not filtered_raw:
        raise RuntimeError("RUNNER_MATRIX and FILTERED_MATRIX are required")
    json.loads(runner_matrix_raw)  # validate RUNNER_MATRIX is valid JSON
    accepted = json.loads(accepted_raw)
    filtered_matrix = json.loads(filtered_raw)
    bmt_jobs = sorted(
        {str(e.get("project", "")).strip() for e in filtered_matrix.get("include", []) if e}
    )
    print(f"::notice::Matrix handshake: uploaded={len(accepted)} legs={len(bmt_jobs)}")


# ---- Trigger / handshake ----


# preflight-trigger-queue and write-run-trigger wrappers removed; registered directly in driver.py.


def run_force_clean_vm_restart() -> None:
    import time

    cfg = get_config()
    cfg.require_gcp()
    ctx = get_context()
    if ctx and ctx.workflow and ctx.workflow.stale_cleanup_count is not None:
        stale_count = ctx.workflow.stale_cleanup_count
    else:
        stale_count = os.environ.get("STALE_CLEANUP_COUNT", "0")
    print(f"Stale trigger cleanup removed {stale_count} file(s); forcing clean VM restart.")
    try:
        payload = shared.vm_describe(cfg.gcp_project, cfg.gcp_zone, cfg.bmt_vm_name)
        status_before = str(payload.get("status", "UNKNOWN"))
    except shared.GcloudError:
        status_before = "UNKNOWN"
    print(f"VM status before restart action: {status_before}")
    if status_before != "TERMINATED":
        try:
            shared.vm_stop(cfg.gcp_project, cfg.gcp_zone, cfg.bmt_vm_name)
        except shared.GcloudError as exc:
            gh_warning(f"VM stop command failed: {exc}; will continue polling for TERMINATED.")
    for _ in range(24):
        try:
            payload = shared.vm_describe(cfg.gcp_project, cfg.gcp_zone, cfg.bmt_vm_name)
            status_now = str(payload.get("status", "UNKNOWN"))
        except shared.GcloudError:
            status_now = "UNKNOWN"
        if status_now == "TERMINATED":
            print("VM reached TERMINATED; proceeding with normal start step.")
            return
        time.sleep(5)
    raise RuntimeError("VM did not reach TERMINATED before restart sequence.")


def run_wait_handshake() -> None:
    from cli.commands import vm

    cfg = get_config()
    base_timeout = cfg.bmt_handshake_timeout_sec
    ctx = get_context()
    w = ctx.workflow if ctx is not None else None
    restart_vm = _ctx_str(w, "restart_vm", "RESTART_VM", "false").lower() in ("true", "1", "yes")
    vm_reused_running = _ctx_str(w, "vm_reused_running", "VM_REUSED_RUNNING", "false").lower() in (
        "true",
        "1",
        "yes",
    )
    stale_count = _ctx_str(w, "stale_cleanup_count", "STALE_CLEANUP_COUNT", "0")

    if vm_reused_running:
        timeout = cfg.bmt_handshake_timeout_sec_reuse_running
        gh_notice(f"Handshake branch=reuse-running timeout={timeout}s")
    elif restart_vm:
        timeout = base_timeout + 60
        print(
            f"::notice::Handshake branch=post-cleanup-restart stale_cleanup_count={stale_count} timeout={timeout}s"
        )
    else:
        timeout = base_timeout
        gh_notice(f"Handshake branch=standard timeout={timeout}s")

    vm.run_wait_handshake(timeout_sec=timeout)


def run_handshake_timeout_diagnostics() -> None:
    run_id = workflow_run_id()
    root = workflow_runtime_root()
    trigger_uri = f"{root}/triggers/runs/{run_id}.json"
    ack_uri = f"{root}/triggers/acks/{run_id}.json"
    cfg = get_config()
    gh_group("GCS trigger/ack diagnostics")
    print(f"Trigger URI: {trigger_uri}")
    print(f"Ack URI: {ack_uri}")

    for uri in (trigger_uri, ack_uri):
        with contextlib.suppress(gcs.GcsError):
            raw = gcs.read_object(uri)
            text = raw.decode("utf-8", errors="replace")
            for line in text.splitlines()[:120]:
                print(line)
    gh_endgroup()
    gh_group("VM instance diagnostics")
    with contextlib.suppress(shared.GcloudError):
        payload = shared.vm_describe(cfg.gcp_project, cfg.gcp_zone, cfg.bmt_vm_name)
        for k in ("name", "status", "lastStartTimestamp", "lastStopTimestamp"):
            print(f"{k}: {payload.get(k)}")
        items = (payload.get("metadata") or {}).get("items") or []
        for item in items:
            if isinstance(item, dict):
                print(f"  {item.get('key')}: {item.get('value')}")
    gh_endgroup()
    gh_group("VM serial output tail")
    with contextlib.suppress(shared.GcloudError):
        serial = shared.vm_serial_output(cfg.gcp_project, cfg.gcp_zone, cfg.bmt_vm_name)
        for line in serial.splitlines()[-200:]:
            print(line)
    gh_endgroup()


# ---- Status updates ----


def run_post_pending_status() -> None:
    """Post a pending commit status to show BMT progress in PR checks.
    Uses config for context/description; repository/head_sha/target_url from context or workflow inputs."""
    cfg = get_config()
    ctx = get_context()
    repository, head_sha = _resolve_repository_and_sha(ctx)
    w = ctx.workflow if (ctx and ctx.workflow) else None
    target_url = (
        (w.target_url or "").strip() if w else os.environ.get("TARGET_URL") or None
    ) or None
    context = cfg.bmt_status_context
    description = cfg.bmt_progress_description
    if not repository or not head_sha:
        gh_warning("Skipping pending status post (missing repository or head_sha).")
        return
    try:
        github_api.post_commit_status(
            repository, head_sha, "pending", context, description, target_url=target_url
        )
        gh_notice(f"Posted pending status '{context}': {description}")
    except github_api.GitHubApiError as e:
        gh_warning(f"Failed to post pending status for {head_sha}: {e}")


# ---- Failure / summary ----


def run_post_handoff_timeout_status() -> None:
    cfg = get_config()
    ctx = get_context()
    repository, head_sha = _resolve_repository_and_sha(ctx)
    context = cfg.bmt_status_context
    description = cfg.bmt_failure_status_description
    if not repository or not head_sha:
        gh_warning("Skipping fallback status post (missing repository/head_sha/token).")
        return
    try:
        if not github_api.should_post_failure_status(repository, head_sha, context):
            print(
                f"::notice::Fallback status skipped: '{context}' is already terminal for {head_sha}."
            )
            return
        github_api.post_commit_status(repository, head_sha, "error", context, description)
        gh_notice(f"Posted fallback terminal status '{context}=error' for {head_sha}.")
    except github_api.GitHubApiError as e:
        gh_warning(f"Failed to post fallback terminal status for {head_sha}: {e}")


def run_cleanup_failed_trigger_artifacts() -> None:
    run_id = workflow_run_id()
    root = workflow_runtime_root()

    for name in ("runs", "acks", "status"):
        uri = f"{root}/triggers/{name}/{run_id}.json"
        with contextlib.suppress(gcs.GcsError):
            gcs.delete_object(uri)
    gh_group("Trigger family counts after cleanup")
    for name in ("runs", "acks", "status"):
        prefix = f"{root}/triggers/{name}/"
        uris = gcs.list_prefix(prefix)
        count = len([u for u in uris if u.endswith(".json")])
        print(f"{prefix} {count}")
    gh_endgroup()


# stop-vm-best-effort is now inlined as shell in bmt-failure-fallback/action.yml.


def run_write_handoff_summary() -> None:
    ctx = get_context()
    if ctx and ctx.workflow:
        w = ctx.workflow
        mode = w.mode or ""
        repository = (w.repository or w.github_repository or "").strip()
        head_sha = (w.head_sha or "").strip()
        head_branch = (w.head_branch or "").strip()
        pr_number = (w.pr_number or "").strip()
        filtered_matrix_raw = w.filtered_matrix or '{"include":[]}'
        trigger_written = (w.trigger_written or "false").strip()
        vm_started = (w.vm_started or "false").strip()
        handshake_ok = (w.handshake_ok or "false").strip()
        handshake_elapsed_sec = (w.handshake_elapsed_sec or "").strip()
        handoff_state_line = (w.handoff_state_line or "").strip()
        failure_reason = (w.failure_reason or "").strip()
        server = (w.github_server_url or "https://github.com").strip()
        run_id = (w.github_run_id or "").strip()
    else:
        mode = os.environ.get("MODE", "")
        repository = os.environ.get("REPOSITORY") or os.environ.get("GITHUB_REPOSITORY", "")
        head_sha = os.environ.get("HEAD_SHA", "")
        head_branch = os.environ.get("HEAD_BRANCH", "")
        pr_number = os.environ.get("PR_NUMBER", "")
        filtered_matrix_raw = os.environ.get("FILTERED_MATRIX", '{"include":[]}')
        trigger_written = os.environ.get("TRIGGER_WRITTEN", "false")
        vm_started = os.environ.get("VM_STARTED", "false")
        handshake_ok = os.environ.get("HANDSHAKE_OK", "false")
        handshake_elapsed_sec = os.environ.get("HANDSHAKE_ELAPSED_SEC", "").strip()
        handoff_state_line = os.environ.get("HANDOFF_STATE_LINE", "")
        failure_reason = os.environ.get("FAILURE_REASON", "")
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        run_id = os.environ.get("GITHUB_RUN_ID", "")
    repo_slug = os.environ.get("GITHUB_REPOSITORY", repository)
    run_url = f"{server}/{repo_slug}/actions/runs/{run_id}" if run_id else ""
    repo_url = f"{server}/{repository}"
    pr_url = f"{repo_url}/pull/{pr_number}" if pr_number else ""
    legs_planned = len(json.loads(filtered_matrix_raw).get("include", []))
    if not handoff_state_line:
        handoff_state_line = {
            "run_success": "Handoff complete: VM confirmed trigger.",
            "skip": "Handoff complete: no supported test runs to hand off.",
            "failure": "Handoff failed: VM did not confirm trigger.",
        }.get(mode, "Handoff state unavailable. Check this workflow run.")

    # Links line: PR · Workflow run · SHA on branch
    link_parts = []
    if pr_url:
        link_parts.append(f"PR [#{pr_number}]({pr_url})")
    if run_url:
        link_parts.append(f"[Workflow run]({run_url})")
    link_parts.append(f"`{head_sha[:7]}` on `{head_branch}`")
    links_line = " · ".join(link_parts)

    trigger_icon = "✅" if trigger_written == "true" else "❌"
    vm_icon = "✅" if vm_started == "true" else "❌"
    handshake_icon = "✅" if handshake_ok == "true" else "❌"

    table_rows = [
        "| | |",
        "|---|---|",
        f"| Trigger written | {trigger_icon} |",
        f"| VM started | {vm_icon} |",
        f"| VM confirmed | {handshake_icon} |",
    ]
    if handshake_elapsed_sec and handshake_ok == "true":
        table_rows.append(f"| Handshake time | **{handshake_elapsed_sec}s** |")
    table_rows.append(f"| Test runs | **{legs_planned}** |")

    lines = [
        "## BMT Handoff",
        "",
        links_line,
        "",
        *table_rows,
        "",
        handoff_state_line,
    ]
    if failure_reason:
        lines.extend(["", f"> ⚠️ {failure_reason}"])
    lines.extend(
        [
            "",
            "_BMT result will appear in the PR **Checks** tab and **Comments** — not here._",
        ]
    )
    if mode == "failure":
        lines.extend(
            ["", "_Handoff failed — inspect the trigger and handshake steps above for details._"]
        )
    _append_step_summary("\n".join(lines) + "\n")
