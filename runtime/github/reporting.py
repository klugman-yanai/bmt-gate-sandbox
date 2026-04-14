from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from github import Auth, Github, GithubException
from github.GithubObject import NotSet

from runtime.config.bmt_domain_status import BmtProgressStatus
from runtime.config.constants import HTTP_TIMEOUT, STATUS_CONTEXT
from runtime.config.status import CheckConclusion, CheckStatus, CommitStatus
from runtime.github import github_checks
from runtime.github.presentation import (
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


def _github_repo(token: str, repository: str) -> Any:
    return Github(auth=Auth.Token(token), timeout=int(HTTP_TIMEOUT)).get_repo(repository)


@dataclass(frozen=True, slots=True)
class GitHubReporter:
    repository: str
    sha: str
    token: str
    status_context: str = STATUS_CONTEXT

    def _repo(self) -> Any:
        return _github_repo(self.token, self.repository)

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
            ProgressBmtRow(project=p, bmt=b, status=BmtProgressStatus.PENDING.value) for p, b in (pending_legs or [])
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
            except GithubException:
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
        except GithubException:
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
        try:
            self._repo().get_commit(self.sha).create_status(
                state,
                target_url=details_url or NotSet,
                description=description[:140],
                context=self.status_context,
            )
        except GithubException:
            return False
        return True

    def _upsert_issue_comment(self, *, pr_number: int, body: str) -> None:
        comment_id = self._find_existing_comment(pr_number=pr_number)
        if comment_id is None:
            self._create_issue_comment(pr_number=pr_number, body=body)
            return
        self._update_issue_comment(pr_number=pr_number, comment_id=comment_id, body=body)

    def _find_existing_comment(self, *, pr_number: int) -> int | None:
        owner, _, repo = self.repository.partition("/")
        if not owner or not repo:
            return None
        try:
            issue = self._repo().get_issue(pr_number)
            for n, comment in enumerate(issue.get_comments()):
                if n >= 100:
                    break
                if comment_marker() in (comment.body or ""):
                    cid = comment.id
                    if isinstance(cid, int):
                        return cid
            return None
        except GithubException:
            return None

    def _create_issue_comment(self, *, pr_number: int, body: str) -> None:
        self._repo().get_issue(pr_number).create_comment(body)

    def _update_issue_comment(self, *, pr_number: int, comment_id: int, body: str) -> None:
        self._repo().get_issue(pr_number).get_comment(comment_id).edit(body)
