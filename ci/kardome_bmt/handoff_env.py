"""Normalised handoff view from WorkflowContext or raw environment."""

from __future__ import annotations

import dataclasses
import os

from kardome_bmt.actions import gh_warning
from kardome_bmt.config import BmtContext, WorkflowContext


def _w_attr(w: object, name: str, default: str = "") -> str:
    return (getattr(w, name, None) or default).strip()


@dataclasses.dataclass(frozen=True)
class HandoffEnv:
    """Values for summary and failure resolution from ctx.workflow or os.environ."""

    prepare_result: str
    mode: str
    head_sha: str
    pr_number: str
    orch_has_legs: bool
    repository: str
    head_branch: str
    filtered_matrix_raw: str
    accepted_projects_raw: str
    dispatch_confirmed: bool
    failure_reason: str
    server: str
    run_id: str

    @classmethod
    def resolve(cls, ctx: BmtContext | None) -> HandoffEnv:
        w = ctx.workflow if ctx is not None else None
        if w is not None:
            return _handoff_env_from_workflow(w)
        return cls(
            prepare_result=(os.environ.get("PREPARE_RESULT") or "").strip(),
            mode=(os.environ.get("MODE") or "").strip(),
            head_sha=(
                os.environ.get("PREPARE_HEAD_SHA")
                or os.environ.get("DISPATCH_HEAD_SHA")
                or os.environ.get("GITHUB_SHA", "")
            ),
            pr_number=(os.environ.get("PREPARE_PR_NUMBER") or os.environ.get("DISPATCH_PR_NUMBER") or ""),
            orch_has_legs=os.environ.get("ORCH_HAS_LEGS") == "true",
            repository=(os.environ.get("REPOSITORY") or os.environ.get("GITHUB_REPOSITORY", "")),
            head_branch=(os.environ.get("HEAD_BRANCH") or "").strip(),
            filtered_matrix_raw=os.environ.get("FILTERED_MATRIX") or '{"include":[]}',
            accepted_projects_raw=os.environ.get("ACCEPTED_PROJECTS") or "[]",
            dispatch_confirmed=os.environ.get("HANDSHAKE_OK") == "true",
            failure_reason=(os.environ.get("FAILURE_REASON") or "").strip(),
            server=os.environ.get("GITHUB_SERVER_URL") or "https://github.com",
            run_id=(os.environ.get("GITHUB_RUN_ID") or "").strip(),
        )


def _handoff_env_from_workflow(w: WorkflowContext) -> HandoffEnv:
    return HandoffEnv(
        prepare_result=(w.prepare_result or "").strip(),
        mode=(w.mode or "").strip(),
        head_sha=(
            (w.prepare_head_sha or "").strip()
            or (w.dispatch_head_sha or "").strip()
            or (w.head_sha or "").strip()
            or os.environ.get("GITHUB_SHA", "")
        ),
        pr_number=(w.prepare_pr_number or "").strip() or (w.dispatch_pr_number or "").strip(),
        orch_has_legs=(w.orch_has_legs or "").strip() == "true",
        repository=(w.repository or "").strip() or (w.github_repository or "").strip(),
        head_branch=(w.head_branch or "").strip(),
        filtered_matrix_raw=(w.filtered_matrix or "").strip() or '{"include":[]}',
        accepted_projects_raw=(w.accepted_projects or "").strip() or "[]",
        dispatch_confirmed=(w.handshake_ok or "").strip() == "true",
        failure_reason=(w.failure_reason or "").strip(),
        server=(w.github_server_url or "").strip() or "https://github.com",
        run_id=(w.github_run_id or "").strip(),
    )


def resolve_repository_and_sha(ctx: BmtContext | None) -> tuple[str, str]:
    w = ctx.workflow if ctx is not None else None
    if w is not None:
        repository = (w.repository or "").strip() or (w.github_repository or "").strip() or ""
        head_sha = (w.head_sha or "").strip()
    else:
        repository = os.environ.get("REPOSITORY") or os.environ.get("GITHUB_REPOSITORY", "")
        head_sha = os.environ.get("HEAD_SHA", "")
    return repository, head_sha


def canonical_repo_slug_for_github_links(env: HandoffEnv) -> str:
    gh = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    ctx = (env.repository or "").strip()
    if gh and ctx and gh != ctx:
        gh_warning(
            "GITHUB_REPOSITORY disagrees with workflow repository context "
            f"({gh!r} vs {ctx!r}); using GITHUB_REPOSITORY for links."
        )
    return gh or ctx
