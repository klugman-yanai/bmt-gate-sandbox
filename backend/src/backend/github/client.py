"""Small githubkit helpers shared by backend GitHub integrations."""

from __future__ import annotations

from bmtcontract.constants import GITHUB_API_VERSION
from githubkit import AppAuthStrategy, GitHub, TokenAuthStrategy
from githubkit.exception import GitHubException

from backend.config.constants import HTTP_TIMEOUT


def split_repository(repository: str) -> tuple[str, str]:
    owner, sep, repo = repository.partition("/")
    if not owner or not sep or not repo:
        raise ValueError(f"repository must be in owner/name form: {repository!r}")
    return owner, repo


def github_client(token: str) -> GitHub:
    return GitHub(auth=TokenAuthStrategy(token), timeout=int(HTTP_TIMEOUT))


def github_app_client(app_id: str | int, private_key: str) -> GitHub:
    return GitHub(auth=AppAuthStrategy(app_id, private_key), timeout=int(HTTP_TIMEOUT))


def github_rest(client: GitHub):
    return client.rest(GITHUB_API_VERSION)


__all__ = [
    "GitHubException",
    "github_app_client",
    "github_client",
    "github_rest",
    "split_repository",
]
