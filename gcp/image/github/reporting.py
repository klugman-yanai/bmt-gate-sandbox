from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from gcp.image.config.bmt_domain_status import BmtProgressStatus
from gcp.image.config.constants import HTTP_TIMEOUT, STATUS_CONTEXT
from gcp.image.config.status import CheckConclusion, CheckStatus, CommitStatus
from gcp.image.github import github_checks
from gcp.image.github.github_auth import github_api_headers
from gcp.image.github.presentation import (
    CheckFinalView,
    CheckProgressView,
    FinalCommentView,
    ProgressBmtRow,
    StartedCommentView,
    comment_marker,
    render_final_check_output,
    render_final_pr_comment,
    render_progress_check_output,
    render_started_pr_comment,
)


def workflow_execution_console_url(*, project: str, region: str, workflow_name: str, execution_name: str) -> str:
    execution_id = execution_name.rsplit("/", 1)[-1].strip()
    return (
        "https://console.cloud.google.com/workflows/workflow/"
        f"{region}/{workflow_name}/execution/{execution_id}?project={project}"
    )


@dataclass(frozen=True, slots=True)
class GitHubReporter:
    repository: str
    sha: str
    token: str
    status_context: str = STATUS_CONTEXT

    def post_pending_status(self, *, details_url: str | None = None) -> bool:
        return self._post_commit_status(
            state=CommitStatus.PENDING.value,
            description="Dispatching Cloud Run BMT pipeline...",
            details_url=details_url,
        )

    def post_final_status(self, *, state: str, description: str, details_url: str | None = None) -> bool:
        return self._post_commit_status(state=state, description=description, details_url=details_url)

    def create_started_check_run(
        self,
        view: StartedCommentView,
        *,
        details_url: str,
        external_id: str | None = None,
        pending_legs: list[tuple[str, str]] | None = None,
    ) -> int:
        legs = [
            ProgressBmtRow(project=p, bmt=b, status=BmtProgressStatus.PENDING.value)
            for p, b in (pending_legs or [])
        ]
        output = render_progress_check_output(
            CheckProgressView(
                completed_count=0,
                total_count=len(legs),
                elapsed_sec=None,
                eta_sec=None,
                links=view.links,
                bmts=legs,
            )
        )
        return github_checks.create_check_run(
            self.token,
            self.repository,
            self.sha,
            name=self.status_context,
            status=CheckStatus.IN_PROGRESS.value,
            output=output,
            details_url=details_url,
            external_id=external_id,
        )

    def update_progress_check_run(self, *, check_run_id: int, view: CheckProgressView, details_url: str) -> None:
        github_checks.update_check_run(
            self.token,
            self.repository,
            check_run_id,
            status=CheckStatus.IN_PROGRESS.value,
            output=render_progress_check_output(view),
            details_url=details_url,
        )

    def finalize_check_run(
        self,
        *,
        check_run_id: int | None,
        view: CheckFinalView,
        details_url: str,
    ) -> tuple[int | None, bool]:
        output = render_final_check_output(view)
        conclusion = (
            CheckConclusion.SUCCESS.value
            if view.state == CheckConclusion.SUCCESS.value
            else CheckConclusion.FAILURE.value
        )
        if check_run_id is None:
            try:
                check_run_id = github_checks.create_check_run(
                    self.token,
                    self.repository,
                    self.sha,
                    name=self.status_context,
                    status=CheckStatus.IN_PROGRESS.value,
                    output={"title": "BMT Finalizing", "summary": "Publishing final results…"},
                    details_url=details_url,
                )
            except httpx.HTTPError:
                return None, False
        try:
            github_checks.update_check_run(
                self.token,
                self.repository,
                check_run_id,
                status=CheckStatus.COMPLETED.value,
                conclusion=conclusion,
                output=output,
                details_url=details_url,
            )
        except httpx.HTTPError:
            return check_run_id, False
        return check_run_id, True

    def upsert_started_pr_comment(self, *, pr_number: int, view: StartedCommentView) -> None:
        self._upsert_issue_comment(pr_number=pr_number, body=render_started_pr_comment(view))

    def upsert_final_pr_comment(self, *, pr_number: int, view: FinalCommentView) -> None:
        self._upsert_issue_comment(pr_number=pr_number, body=render_final_pr_comment(view))

    def _post_commit_status(self, *, state: str, description: str, details_url: str | None = None) -> bool:
        owner, _, repo = self.repository.partition("/")
        if not owner or not repo or not self.sha or not self.token:
            return False
        url = f"https://api.github.com/repos/{owner}/{repo}/statuses/{self.sha}"
        payload: dict[str, Any] = {
            "state": state,
            "context": self.status_context,
            "description": description[:140],
        }
        if details_url:
            payload["target_url"] = details_url
        response = httpx.post(url, json=payload, headers=github_api_headers(self.token), timeout=HTTP_TIMEOUT)
        return bool(response.is_success)

    def _upsert_issue_comment(self, *, pr_number: int, body: str) -> None:
        comment_id = self._find_existing_comment(pr_number=pr_number)
        if comment_id is None:
            self._create_issue_comment(pr_number=pr_number, body=body)
            return
        self._update_issue_comment(comment_id=comment_id, body=body)

    def _find_existing_comment(self, *, pr_number: int) -> int | None:
        owner, _, repo = self.repository.partition("/")
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
        response = httpx.get(
            url, headers=github_api_headers(self.token), params={"per_page": 100}, timeout=HTTP_TIMEOUT
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            return None
        for comment in payload:
            if not isinstance(comment, dict):
                continue
            body = str(comment.get("body") or "")
            if comment_marker() in body:
                comment_id = comment.get("id")
                if isinstance(comment_id, int):
                    return comment_id
        return None

    def _create_issue_comment(self, *, pr_number: int, body: str) -> None:
        owner, _, repo = self.repository.partition("/")
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
        response = httpx.post(url, headers=github_api_headers(self.token), json={"body": body}, timeout=HTTP_TIMEOUT)
        response.raise_for_status()

    def _update_issue_comment(self, *, comment_id: int, body: str) -> None:
        owner, _, repo = self.repository.partition("/")
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/comments/{comment_id}"
        response = httpx.patch(url, headers=github_api_headers(self.token), json={"body": body}, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
