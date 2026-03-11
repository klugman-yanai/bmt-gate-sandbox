"""BMT workflow step commands (replace bmt_workflow.sh)."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

from cli import gcs, github_api, shared
from cli.gh_output import gh_endgroup, gh_group, gh_notice, gh_warning
from cli.shared import _workflow_run_id, _workflow_runtime_root, get_config
from cli.shared.defaults import DEFAULT_HANDSHAKE_TIMEOUT_SEC


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


# ---- Context (bmt-prepare) ----
# emit-bmt-context, validate-required-vars, guard-no-legacy-prefix are now inlined as shell in bmt-prepare/action.yml.


def run_resolve_failure_context() -> None:
    path = _github_output()
    mode = "no_context" if os.environ.get("PREPARE_RESULT") == "failure" else "context"
    head_sha = (
        os.environ.get("PREPARE_HEAD_SHA")
        or os.environ.get("DISPATCH_HEAD_SHA")
        or os.environ.get("GITHUB_SHA", "")
    )
    pr_number = os.environ.get("PREPARE_PR_NUMBER") or os.environ.get("DISPATCH_PR_NUMBER") or ""
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
    runner_matrix_raw = os.environ.get("RUNNER_MATRIX")
    head_sha = os.environ.get("HEAD_SHA")
    if not runner_matrix_raw or not head_sha:
        raise RuntimeError("RUNNER_MATRIX and HEAD_SHA are required")
    matrix = json.loads(runner_matrix_raw)
    include = matrix.get("include", [])
    if not isinstance(include, list):
        raise TypeError("RUNNER_MATRIX.include must be a JSON array")

    preseeded = os.environ.get("BMT_RUNNERS_PRESEEDED_IN_GCS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    available_artifacts_raw = os.environ.get("AVAILABLE_ARTIFACTS", "[]")
    try:
        available_artifacts = json.loads(available_artifacts_raw)
    except json.JSONDecodeError:
        available_artifacts = []
    if not isinstance(available_artifacts, list):
        available_artifacts = []
    artifact_set = {str(a).strip() for a in available_artifacts if str(a).strip()}

    root = _workflow_runtime_root()
    run_id = os.environ.get("GITHUB_RUN_ID") or _workflow_run_id()
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
                    with contextlib.suppress(gcs.GcsError):
                        gcs.write_object(marker_uri, "{}")
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
                    with contextlib.suppress(gcs.GcsError):
                        gcs.write_object(marker_uri, "{}")
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
    run_id = _workflow_run_id()
    root = _workflow_runtime_root()
    prefix = f"{root}/_workflow/uploaded/{run_id}/"
    uris = gcs.list_prefix(prefix)
    uploaded_projects = {
        u.split("/")[-1].replace(".json", "").strip() for u in uris if u.endswith(".json")
    }

    # In sandbox/test flows, runner upload jobs can be intentionally skipped when
    # the runner is already present in the bucket. Accept projects that already
    # have runner metadata for the requested preset(s).
    runner_matrix_raw = os.environ.get("RUNNER_MATRIX", "").strip()
    if runner_matrix_raw:
        with contextlib.suppress(json.JSONDecodeError):
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

    names = sorted(uploaded_projects)
    accepted = json.dumps(names)
    Path("accepted.txt").write_text(accepted)
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with Path(path).open("a", encoding="utf-8") as f:
            f.write(f"accepted_projects={accepted}\n")
    gh_notice(f"Runners uploaded for projects: {accepted}")


def run_summarize_matrix_handshake() -> None:
    runner_matrix_raw = os.environ.get("RUNNER_MATRIX", "{}")
    accepted_raw = os.environ.get("ACCEPTED", "[]")
    filtered_raw = os.environ.get("FILTERED_MATRIX", "{}")
    if not runner_matrix_raw or not filtered_raw:
        raise RuntimeError("RUNNER_MATRIX and FILTERED_MATRIX are required")
    runner_matrix = json.loads(runner_matrix_raw)
    accepted = json.loads(accepted_raw)
    filtered_matrix = json.loads(filtered_raw)
    requested = sorted(
        {str(e.get("project", "")).strip() for e in runner_matrix.get("include", []) if e}
    )
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
    stale_count = int(os.environ.get("STALE_CLEANUP_COUNT", "0"))
    print(f"Stale trigger cleanup removed {stale_count} file(s); forcing clean VM restart.")
    try:
        payload = shared.vm_describe(cfg.gcp_project, cfg.gcp_zone, cfg.bmt_vm_name)
        status_before = str(payload.get("status", "UNKNOWN"))
    except shared.GcloudError:
        status_before = "UNKNOWN"
    print(f"VM status before restart action: {status_before}")
    if status_before != "TERMINATED":
        shared.run_capture(
            [
                "gcloud",
                "compute",
                "instances",
                "stop",
                cfg.bmt_vm_name,
                "--zone",
                cfg.gcp_zone,
                "--project",
                cfg.gcp_project,
            ]
        )
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

    base_timeout = int(
        os.environ.get("BMT_HANDSHAKE_TIMEOUT_SEC", str(DEFAULT_HANDSHAKE_TIMEOUT_SEC))
    )
    restart_vm = os.environ.get("RESTART_VM", "false").lower() in ("true", "1", "yes")
    vm_reused_running = os.environ.get("VM_REUSED_RUNNING", "false").lower() in ("true", "1", "yes")
    stale_count = os.environ.get("STALE_CLEANUP_COUNT", "0")

    if vm_reused_running:
        timeout = 600
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
    run_id = _workflow_run_id()
    root = _workflow_runtime_root()
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
    Reads REPOSITORY/GITHUB_REPOSITORY, HEAD_SHA, GITHUB_TOKEN, BMT_STATUS_CONTEXT,
    BMT_PROGRESS_DESCRIPTION, and optional TARGET_URL from env."""
    repository = os.environ.get("REPOSITORY") or os.environ.get("GITHUB_REPOSITORY", "")
    head_sha = os.environ.get("HEAD_SHA", "")
    context = os.environ.get("BMT_STATUS_CONTEXT", "BMT Gate")
    description = os.environ.get("BMT_PROGRESS_DESCRIPTION", "BMT in progress…")
    target_url = os.environ.get("TARGET_URL") or None
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
    repository = os.environ.get("REPOSITORY") or os.environ.get("GITHUB_REPOSITORY", "")
    head_sha = os.environ.get("HEAD_SHA", "")
    context = os.environ.get("BMT_STATUS_CONTEXT", "BMT Gate")
    description = os.environ.get(
        "BMT_FAILURE_STATUS_DESCRIPTION",
        "BMT cancelled: VM handshake timeout before pickup.",
    )
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
    run_id = _workflow_run_id()
    root = _workflow_runtime_root()

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
    mode = os.environ.get("MODE", "")
    repository = os.environ.get("REPOSITORY") or os.environ.get("GITHUB_REPOSITORY", "")
    head_sha = os.environ.get("HEAD_SHA", "")
    head_branch = os.environ.get("HEAD_BRANCH", "")
    pr_number = os.environ.get("PR_NUMBER", "")
    filtered_matrix_raw = os.environ.get("FILTERED_MATRIX", '{"include":[]}')
    trigger_written = os.environ.get("TRIGGER_WRITTEN", "false")
    vm_started = os.environ.get("VM_STARTED", "false")
    handshake_ok = os.environ.get("HANDSHAKE_OK", "false")
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

    lines = [
        "## BMT Handoff",
        "",
        links_line,
        "",
        "| | |",
        "|---|---|",
        f"| Trigger written | {trigger_icon} |",
        f"| VM started | {vm_icon} |",
        f"| VM confirmed | {handshake_icon} |",
        f"| Test runs | **{legs_planned}** |",
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
