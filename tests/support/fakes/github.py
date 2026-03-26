from __future__ import annotations

from dataclasses import dataclass, field

type JSONValue = str | int | float | bool | None | dict[str, "JSONValue"] | list["JSONValue"]


@dataclass
class FakeGithubBackend:
    """Minimal deterministic GitHub status/check/comment backend for contract tests."""

    statuses: list[dict[str, str]] = field(default_factory=list)
    comments: list[dict[str, str | int]] = field(default_factory=list)
    checks: list[dict[str, JSONValue]] = field(default_factory=list)

    def post_status(self, repository: str, sha: str, state: str, context: str) -> None:
        self.statuses.append({"repository": repository, "sha": sha, "state": state, "context": context})
