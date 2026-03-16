"""Handoff: write context, resolve failure context, status posts, cleanup, write summary."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

from ci import config, core, gcs, github
from ci.actions import gh_endgroup, gh_group, gh_notice, gh_warning


def _resolve_repository_and_sha(ctx: object | None) -> tuple[str, str]:
    w = getattr(ctx, "workflow", None) if ctx is not None else None
    if w is not None:
        repository = (
            getattr(w, "repository", None) or getattr(w, "github_repository", None) or ""
        ).strip()
        head_sha = (getattr(w, "head_sha", None) or "").strip()
    else:
        repository = os.environ.get("REPOSITORY") or os.environ.get("GITHUB_REPOSITORY", "")
        head_sha = os.environ.get("HEAD_SHA", "")
    return repository, head_sha


def _append_step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        raise RuntimeError("GITHUB_STEP_SUMMARY is not set")
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(text)


class HandoffManager:
    def __init__(self, cfg: object, ctx: object | None) -> None:
        self._cfg = cfg
        self._ctx = ctx

    @classmethod
    def from_env(cls) -> HandoffManager:
        return cls(config.get_config(), config.get_context())

    def write_context(self) -> None:
        from gcp.image.config.bmt_config import (
            context_from_env,
            get_context_path,
            write_context_to_file,
        )

        ctx = context_from_env(runtime=os.environ)
        path = get_context_path(runtime=os.environ)
        write_context_to_file(path, ctx)
        gh_notice(f"Wrote context to {path}")

    def resolve_failure_context(self) -> None:
        path_str = os.environ.get("GITHUB_OUTPUT")
        if not path_str:
            raise RuntimeError("GITHUB_OUTPUT is not set")
        path = Path(path_str)
        ctx = self._ctx
        w = getattr(ctx, "workflow", None) if ctx else None
        if ctx and w:
            mode = (
                "no_context"
                if (getattr(w, "prepare_result", None) or "").strip() == "failure"
                else "context"
            )
            head_sha = (
                (getattr(w, "prepare_head_sha", None) or "").strip()
                or (getattr(w, "dispatch_head_sha", None) or "").strip()
                or (getattr(w, "head_sha", None) or "").strip()
                or os.environ.get("GITHUB_SHA", "")
            )
            pr_number = (
                getattr(w, "prepare_pr_number", None)
                or getattr(w, "dispatch_pr_number", None)
                or ""
            ).strip()
            vm_handshake_result = (
                "failure"
                if (getattr(w, "orch_has_legs", None) or "").strip() == "true"
                and (getattr(w, "orch_handshake_ok", None) or "").strip() != "true"
                else "success"
            )
            trigger_written = (
                "true"
                if (getattr(w, "orch_trigger_written", None) or "").strip() == "true"
                else "false"
            )
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
                if os.environ.get("ORCH_HAS_LEGS") == "true"
                and os.environ.get("ORCH_HANDSHAKE_OK") != "true"
                else "success"
            )
            trigger_written = (
                "true" if os.environ.get("ORCH_TRIGGER_WRITTEN") == "true" else "false"
            )
        with path.open("a", encoding="utf-8") as f:
            f.write(f"mode={mode}\n")
            f.write(f"head_sha={head_sha}\n")
            f.write(f"pr_number={pr_number}\n")
            f.write(f"vm_handshake_result={vm_handshake_result}\n")
            f.write(f"trigger_written={trigger_written}\n")

    def post_pending_status(self) -> None:
        repository, head_sha = _resolve_repository_and_sha(self._ctx)
        w = getattr(self._ctx, "workflow", None) if self._ctx else None
        target_url = (
            (getattr(w, "target_url", None) or "").strip()
            if w
            else os.environ.get("TARGET_URL") or None
        )
        target_url = target_url or None
        context = getattr(self._cfg, "bmt_status_context", "")
        description = getattr(self._cfg, "bmt_progress_description", "")
        if not repository or not head_sha:
            gh_warning("Skipping pending status post (missing repository or head_sha).")
            return
        try:
            github.post_commit_status(
                repository, head_sha, "pending", context, description, target_url=target_url
            )
            gh_notice(f"Posted pending status '{context}': {description}")
        except github.GitHubApiError as e:
            gh_warning(f"Failed to post pending status for {head_sha}: {e}")

    def post_handoff_timeout_status(self) -> None:
        repository, head_sha = _resolve_repository_and_sha(self._ctx)
        context = getattr(self._cfg, "bmt_status_context", "")
        description = getattr(self._cfg, "bmt_failure_status_description", "")
        if not repository or not head_sha:
            gh_warning("Skipping fallback status post (missing repository/head_sha/token).")
            return
        try:
            if not github.should_post_failure_status(repository, head_sha, context):
                print(
                    f"::notice::Fallback status skipped: '{context}' is already terminal for {head_sha}."
                )
                return
            github.post_commit_status(repository, head_sha, "error", context, description)
            gh_notice(f"Posted fallback terminal status '{context}=error' for {head_sha}.")
        except github.GitHubApiError as e:
            gh_warning(f"Failed to post fallback terminal status for {head_sha}: {e}")

    def cleanup_failed_trigger_artifacts(self) -> None:
        run_id = core.workflow_run_id()
        root = core.workflow_runtime_root()
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

    def write_summary(self) -> None:
        ctx = self._ctx
        w = getattr(ctx, "workflow", None) if ctx else None
        if ctx and w:
            mode = getattr(w, "mode", None) or ""
            repository = (
                getattr(w, "repository", None) or getattr(w, "github_repository", None) or ""
            ).strip()
            head_sha = (getattr(w, "head_sha", None) or "").strip()
            head_branch = (getattr(w, "head_branch", None) or "").strip()
            pr_number = (getattr(w, "pr_number", None) or "").strip()
            filtered_matrix_raw = getattr(w, "filtered_matrix", None) or '{"include":[]}'
            accepted_projects_raw = getattr(w, "accepted_projects", None) or "[]"
            trigger_written = (getattr(w, "trigger_written", None) or "false").strip()
            dispatch_confirmed = (getattr(w, "handshake_ok", None) or "false").strip()
            handoff_state_line = (getattr(w, "handoff_state_line", None) or "").strip()
            failure_reason = (getattr(w, "failure_reason", None) or "").strip()
            server = (getattr(w, "github_server_url", None) or "https://github.com").strip()
            run_id = (getattr(w, "github_run_id", None) or "").strip()
        else:
            mode = os.environ.get("MODE", "")
            repository = os.environ.get("REPOSITORY") or os.environ.get("GITHUB_REPOSITORY", "")
            head_sha = os.environ.get("HEAD_SHA", "")
            head_branch = os.environ.get("HEAD_BRANCH", "")
            pr_number = os.environ.get("PR_NUMBER", "")
            filtered_matrix_raw = os.environ.get("FILTERED_MATRIX", '{"include":[]}')
            accepted_projects_raw = os.environ.get("ACCEPTED_PROJECTS", "[]")
            trigger_written = os.environ.get("TRIGGER_WRITTEN", "false")
            dispatch_confirmed = os.environ.get("HANDSHAKE_OK", "false")
            handoff_state_line = os.environ.get("HANDOFF_STATE_LINE", "")
            failure_reason = os.environ.get("FAILURE_REASON", "")
            server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
            run_id = os.environ.get("GITHUB_RUN_ID", "")
        repo_slug = os.environ.get("GITHUB_REPOSITORY", repository)
        run_url = f"{server}/{repo_slug}/actions/runs/{run_id}" if run_id else ""
        repo_url = f"{server}/{repository}"
        pr_url = f"{repo_url}/pull/{pr_number}" if pr_number else ""
        _matrix = json.loads(filtered_matrix_raw)
        if isinstance(_matrix, str):
            _matrix = json.loads(_matrix)
        legs_planned = len((_matrix if isinstance(_matrix, dict) else {}).get("include", []))
        _accepted = json.loads(accepted_projects_raw)
        if isinstance(_accepted, str):
            _accepted = json.loads(_accepted)
        subtask_projects = [
            str(p).strip() for p in (_accepted if isinstance(_accepted, list) else [])
            if str(p).strip()
        ]
        if not subtask_projects and legs_planned:
            include = (_matrix if isinstance(_matrix, dict) else {}).get("include", [])
            seen = set()
            for row in include if isinstance(include, list) else []:
                if isinstance(row, dict) and "project" in row:
                    p = str(row.get("project", "")).strip()
                    if p and p not in seen:
                        seen.add(p)
                        subtask_projects.append(p)
        if not handoff_state_line:
            handoff_state_line = {
                "run_success": "Handoff complete: trigger written; cloud runtime will process the run.",
                "skip": "Handoff complete: no supported test runs to hand off.",
                "failure": "Handoff failed: dispatch could not be confirmed.",
            }.get(mode, "Handoff state unavailable. Check this workflow run.")
        link_parts = []
        if pr_url:
            link_parts.append(f"PR [#{pr_number}]({pr_url})")
        if run_url:
            link_parts.append(f"[Workflow run]({run_url})")
        link_parts.append(f"`{head_sha[:7]}` on `{head_branch}`")
        links_line = " · ".join(link_parts)
        trigger_icon = "✅" if trigger_written == "true" else "❌"
        dispatch_icon = "✅" if dispatch_confirmed == "true" else "❌"
        table_rows = [
            "| | |",
            "|---|---|",
            f"| Trigger written | {trigger_icon} |",
            f"| Dispatch confirmed | {dispatch_icon} |",
            f"| Test runs | **{legs_planned}** |",
        ]
        subtasks_display = ", ".join(subtask_projects) if subtask_projects else "—"
        cloud_status = f"{dispatch_icon} **Confirmed**" if dispatch_confirmed == "true" else "❌ Not confirmed"
        cloud_job_lines = [
            "### Google Cloud job",
            "",
            "| | |",
            "|---|---|",
            f"| Status | {cloud_status} |",
            f"| Subtasks | **{subtasks_display}** |",
            "",
        ]
        lines = [
            "## BMT Handoff",
            "",
            links_line,
            "",
            *table_rows,
            "",
            *cloud_job_lines,
            handoff_state_line,
        ]
        if failure_reason:
            lines.extend(["", f"> ⚠️ {failure_reason}"])
        lines.extend(
            ["", "_BMT result will appear in the PR **Checks** tab and commit status — not here._"]
        )
        if mode == "failure":
            lines.extend(
                [
                    "",
                    "_Handoff failed — inspect the trigger and dispatch steps above for details._",
                ]
            )
        _append_step_summary("\n".join(lines) + "\n")
