"""Handoff: write context, resolve failure context, status posts, write summary."""

from __future__ import annotations

import os

from ci import config, github, handoff_dataset
from ci.actions import gh_notice, gh_warning, write_github_output
from ci.config import BmtConfig, BmtContext
from ci.handoff_env import HandoffEnv, resolve_repository_and_sha
from ci.handoff_summary import write_handoff_step_summary


class HandoffManager:
    def __init__(self, cfg: BmtConfig, ctx: BmtContext | None) -> None:
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
        env = HandoffEnv.resolve(self._ctx)
        mode = "no_context" if env.prepare_result == "failure" else "context"
        write_github_output(path_str, "mode", mode)
        write_github_output(path_str, "head_sha", env.head_sha)
        write_github_output(path_str, "pr_number", env.pr_number)

    def post_pending_status(self) -> None:
        repository, head_sha = resolve_repository_and_sha(self._ctx)
        w = self._ctx.workflow if self._ctx else None
        target_url = (
            (w.target_url or "").strip()
            if w is not None
            else (os.environ.get("TARGET_URL") or None)
        )
        target_url = target_url or None
        context = self._cfg.bmt_status_context
        description = self._cfg.bmt_progress_description
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
        repository, head_sha = resolve_repository_and_sha(self._ctx)
        context = self._cfg.bmt_status_context
        description = self._cfg.bmt_failure_status_description
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
        handoff_dataset.validate_dataset_inputs(self._cfg)

    def write_summary(self) -> None:
        env = HandoffEnv.resolve(self._ctx)
        write_handoff_step_summary(self._cfg, env)
