"""Handoff: write context, resolve failure context, status posts, cleanup, write summary."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
from pathlib import Path

from ci import config, core, gcs, github
from ci.actions import gh_endgroup, gh_group, gh_notice, gh_warning
from ci.core import (
    TRIGGER_ACKS_SUBDIR,
    TRIGGER_RUNS_SUBDIR,
    TRIGGER_STATUS_SUBDIR,
)


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


def _w_attr(w: object, name: str, default: str = "") -> str:
    """Return a stripped string attribute from a workflow context object."""
    return (getattr(w, name, None) or default).strip()


@dataclasses.dataclass(frozen=True)
class _HandoffEnv:
    """Normalised view of handoff values from either ctx.workflow or os.environ.

    Populated once per HandoffManager method call so that resolve_failure_context
    and write_summary don't each need their own if/else branches for every field.
    """

    prepare_result: str
    mode: str
    head_sha: str
    pr_number: str
    vm_handshake_ok: bool
    orch_has_legs: bool
    trigger_written: bool
    repository: str
    head_branch: str
    filtered_matrix_raw: str
    accepted_projects_raw: str
    dispatch_confirmed: bool
    failure_reason: str
    server: str
    run_id: str

    @classmethod
    def resolve(cls, ctx: object | None) -> _HandoffEnv:
        w = getattr(ctx, "workflow", None) if ctx is not None else None
        if w is not None:
            return cls(
                prepare_result=_w_attr(w, "prepare_result"),
                mode=_w_attr(w, "mode"),
                head_sha=(
                    _w_attr(w, "prepare_head_sha")
                    or _w_attr(w, "dispatch_head_sha")
                    or _w_attr(w, "head_sha")
                    or os.environ.get("GITHUB_SHA", "")
                ),
                pr_number=(_w_attr(w, "prepare_pr_number") or _w_attr(w, "dispatch_pr_number")),
                vm_handshake_ok=_w_attr(w, "orch_handshake_ok") == "true",
                orch_has_legs=_w_attr(w, "orch_has_legs") == "true",
                trigger_written=_w_attr(w, "orch_trigger_written") == "true",
                repository=_w_attr(w, "repository") or _w_attr(w, "github_repository"),
                head_branch=_w_attr(w, "head_branch"),
                filtered_matrix_raw=_w_attr(w, "filtered_matrix") or '{"include":[]}',
                accepted_projects_raw=_w_attr(w, "accepted_projects") or "[]",
                dispatch_confirmed=_w_attr(w, "handshake_ok") == "true",
                failure_reason=_w_attr(w, "failure_reason"),
                server=_w_attr(w, "github_server_url") or "https://github.com",
                run_id=_w_attr(w, "github_run_id"),
            )
        return cls(
            prepare_result=(os.environ.get("PREPARE_RESULT") or "").strip(),
            mode=(os.environ.get("MODE") or "").strip(),
            head_sha=(
                os.environ.get("PREPARE_HEAD_SHA")
                or os.environ.get("DISPATCH_HEAD_SHA")
                or os.environ.get("GITHUB_SHA", "")
            ),
            pr_number=(
                os.environ.get("PREPARE_PR_NUMBER") or os.environ.get("DISPATCH_PR_NUMBER") or ""
            ),
            vm_handshake_ok=os.environ.get("ORCH_HANDSHAKE_OK") == "true",
            orch_has_legs=os.environ.get("ORCH_HAS_LEGS") == "true",
            trigger_written=os.environ.get("ORCH_TRIGGER_WRITTEN") == "true",
            repository=(os.environ.get("REPOSITORY") or os.environ.get("GITHUB_REPOSITORY", "")),
            head_branch=(os.environ.get("HEAD_BRANCH") or "").strip(),
            filtered_matrix_raw=os.environ.get("FILTERED_MATRIX") or '{"include":[]}',
            accepted_projects_raw=os.environ.get("ACCEPTED_PROJECTS") or "[]",
            dispatch_confirmed=os.environ.get("HANDSHAKE_OK") == "true",
            failure_reason=(os.environ.get("FAILURE_REASON") or "").strip(),
            server=os.environ.get("GITHUB_SERVER_URL") or "https://github.com",
            run_id=(os.environ.get("GITHUB_RUN_ID") or "").strip(),
        )


class HandoffManager:
    def __init__(self, cfg: object, ctx: object | None) -> None:
        self._cfg = cfg
        self._ctx = ctx

    @classmethod
    def from_env(cls) -> HandoffManager:
        return cls(config.get_config(), config.get_context())

    def write_context(self) -> None:
        ctx = config.context_from_env(runtime=os.environ)
        path = config.get_context_path(runtime=os.environ)
        config.write_context_to_file(path, ctx)
        gh_notice(f"Wrote context to {path}")

    def resolve_failure_context(self) -> None:
        path_str = os.environ.get("GITHUB_OUTPUT")
        if not path_str:
            raise RuntimeError("GITHUB_OUTPUT is not set")
        env = _HandoffEnv.resolve(self._ctx)
        mode = "no_context" if env.prepare_result == "failure" else "context"
        vm_handshake_result = (
            "failure" if env.orch_has_legs and not env.vm_handshake_ok else "success"
        )
        trigger_written = "true" if env.trigger_written else "false"
        with Path(path_str).open("a", encoding="utf-8") as f:
            f.write(f"mode={mode}\n")
            f.write(f"head_sha={env.head_sha}\n")
            f.write(f"pr_number={env.pr_number}\n")
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

    def validate_dataset_inputs(self) -> None:
        """Fail early if any enabled BMT has no .wav files in its GCS inputs prefix."""
        bucket = getattr(self._cfg, "gcs_bucket", "") or os.environ.get("GCS_BUCKET", "")
        if not bucket:
            raise RuntimeError("GCS_BUCKET is not set; cannot validate dataset inputs")
        accepted_raw = (os.environ.get("ACCEPTED_PROJECTS") or "[]").strip()
        accepted_projects: list[str] = json.loads(accepted_raw)
        if not isinstance(accepted_projects, list) or not accepted_projects:
            gh_notice("No accepted projects to validate.")
            return

        stage_root = Path("gcp/stage")
        errors: list[str] = []
        for project in accepted_projects:
            bmts_dir = stage_root / "projects" / project / "bmts"
            if not bmts_dir.is_dir():
                gh_warning(f"No bmts dir for project {project!r} at {bmts_dir}")
                continue
            for bmt_json_path in sorted(bmts_dir.glob("*/bmt.json")):
                bmt_slug = bmt_json_path.parent.name
                payload = json.loads(bmt_json_path.read_text(encoding="utf-8"))
                if not payload.get("enabled", True):
                    continue
                inputs_prefix = str(payload.get("inputs_prefix", "")).strip()
                if not inputs_prefix:
                    errors.append(f"{project}/{bmt_slug}: bmt.json missing inputs_prefix")
                    continue
                prefix_uri = f"gs://{bucket}/{inputs_prefix}/"
                blobs = gcs.list_prefix(prefix_uri)
                wav_count = sum(1 for b in blobs if b.lower().endswith(".wav"))
                manifest_uri = f"gs://{bucket}/{inputs_prefix}/dataset_manifest.json"
                manifest_payload, _ = gcs.download_json(manifest_uri)
                if manifest_payload:
                    expected_count = len(manifest_payload.get("files", []))
                    if wav_count != expected_count:
                        errors.append(
                            f"{project}/{bmt_slug}: GCS has {wav_count} .wav files "
                            f"but manifest expects {expected_count}"
                        )
                    else:
                        gh_notice(
                            f"{project}/{bmt_slug}: {wav_count} .wav file(s) match manifest ✓"
                        )
                else:
                    if wav_count == 0:
                        errors.append(f"{project}/{bmt_slug}: no .wav files found at {prefix_uri}")
                    else:
                        gh_notice(f"{project}/{bmt_slug}: {wav_count} .wav file(s) at {prefix_uri}")

        if errors:
            for e in errors:
                print(f"::error::{e}")
            raise RuntimeError(
                f"Dataset validation failed: {len(errors)} BMT(s) have empty input datasets.\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    def cleanup_failed_trigger_artifacts(self) -> None:
        run_id = core.workflow_run_id()
        root = core.workflow_runtime_root()
        for uri in (
            core.run_trigger_uri(root, run_id),
            core.run_handshake_uri(root, run_id),
            core.run_status_uri(root, run_id),
        ):
            with contextlib.suppress(gcs.GcsError):
                gcs.delete_object(uri)
        gh_group("Trigger family counts after cleanup")
        for name in (TRIGGER_RUNS_SUBDIR, TRIGGER_ACKS_SUBDIR, TRIGGER_STATUS_SUBDIR):
            prefix = f"{root}/triggers/{name}/"
            uris = gcs.list_prefix(prefix)
            count = len([u for u in uris if u.endswith(".json")])
            print(f"{prefix} {count}")
        gh_endgroup()

    def write_summary(self) -> None:
        env = _HandoffEnv.resolve(self._ctx)
        repo_slug = os.environ.get("GITHUB_REPOSITORY", env.repository)
        run_url = f"{env.server}/{repo_slug}/actions/runs/{env.run_id}" if env.run_id else ""
        repo_url = f"{env.server}/{env.repository}"
        pr_url = f"{repo_url}/pull/{env.pr_number}" if env.pr_number else ""

        _matrix = json.loads(env.filtered_matrix_raw)
        if isinstance(_matrix, str):
            _matrix = json.loads(_matrix)
        matrix_include = (_matrix if isinstance(_matrix, dict) else {}).get("include", [])

        _accepted = json.loads(env.accepted_projects_raw)
        if isinstance(_accepted, str):
            _accepted = json.loads(_accepted)
        subtask_projects = [
            str(p).strip()
            for p in (_accepted if isinstance(_accepted, list) else [])
            if str(p).strip()
        ]
        if not subtask_projects and isinstance(matrix_include, list):
            seen: set[str] = set()
            for row in matrix_include:
                if isinstance(row, dict) and "project" in row:
                    p = str(row.get("project", "")).strip()
                    if p and p not in seen:
                        seen.add(p)
                        subtask_projects.append(p)

        link_parts = []
        if pr_url:
            link_parts.append(f"PR [#{env.pr_number}]({pr_url})")
        if run_url:
            link_parts.append(f"[Workflow run]({run_url})")
        link_parts.append(f"`{env.head_sha[:7]}` on `{env.head_branch}`")
        links_line = " · ".join(link_parts)

        subtasks_display = ", ".join(subtask_projects) if subtask_projects else "—"
        ok = env.trigger_written and env.dispatch_confirmed
        status_line = (
            f"**Cloud job:** ✅ Confirmed · **Subtasks:** {subtasks_display}"
            if ok
            else f"**Cloud job:** ❌ Not confirmed · **Subtasks:** {subtasks_display}"
        )
        lines = [
            "## BMT Handoff",
            "",
            links_line,
            "",
            status_line,
            "",
        ]
        if env.failure_reason:
            lines.append(f"> {env.failure_reason}")
            lines.append("")
        if env.mode != "failure":
            lines.append("_BMT result will appear in the PR **Checks** tab and commit status._")
        else:
            lines.append("_Inspect the trigger and dispatch steps above for details._")
        _append_step_summary("\n".join(lines) + "\n")
