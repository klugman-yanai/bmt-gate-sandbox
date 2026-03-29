from __future__ import annotations

from types import SimpleNamespace

import pytest
from bmtgate.clients import github as github_client

pytestmark = pytest.mark.unit


def test_trigger_workflow_dispatch_returns_latest_api_run_details(monkeypatch) -> None:
    cap: dict[str, object] = {}

    class _FakeActions:
        def create_workflow_dispatch(self, owner: str, repo: str, workflow_id: str, *, data: dict[str, object]):
            cap["owner"] = owner
            cap["repo"] = repo
            cap["workflow_id"] = workflow_id
            cap["data"] = data
            return SimpleNamespace(
                json=lambda: {
                    "workflow_run_id": 123,
                    "run_url": "https://api.github.com/repos/o/r/actions/runs/123",
                    "html_url": "https://github.com/o/r/actions/runs/123",
                }
            )

    class _FakeGitHub:
        def rest(self, version: str):
            cap["version"] = version
            return SimpleNamespace(actions=_FakeActions())

    def _fake_get_github() -> _FakeGitHub:
        return _FakeGitHub()

    monkeypatch.setattr(github_client, "_get_github", _fake_get_github)

    result = github_client.trigger_workflow_dispatch(
        "owner/repo",
        "bmt-handoff.yml",
        "main",
        inputs={"head_sha": "abc"},
    )

    assert cap["version"] == "2026-03-10"
    assert cap["owner"] == "owner"
    assert cap["repo"] == "repo"
    assert cap["workflow_id"] == "bmt-handoff.yml"
    data = cap["data"]
    assert isinstance(data, dict)
    assert data["ref"] == "main"
    assert data["inputs"] == {"head_sha": "abc"}
    assert isinstance(result, dict)
    assert result["workflow_run_id"] == 123
