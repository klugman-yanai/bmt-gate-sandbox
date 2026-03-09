"""Tests for deploy/code/lib/github_pull_request.py."""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "deploy" / "code" / "lib") not in sys.path:
    sys.path.insert(0, str(_ROOT / "deploy" / "code" / "lib"))

import github_pull_request  # type: ignore[import-not-found]  # noqa: E402


class _Resp:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body.encode("utf-8")

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_get_pr_state_open(monkeypatch) -> None:
    monkeypatch.setattr(
        github_pull_request.urllib.request,
        "urlopen",
        lambda _req, **_kwargs: _Resp(200, '{"state":"open","merged":false,"head":{"sha":"abc123def456"}}'),
    )

    result = github_pull_request.get_pr_state("token", "owner/repo", 12)

    assert result["state"] == "open"
    assert result["merged"] is False
    assert result["head_sha"] == "abc123def456"
    assert result["error"] is None


def test_get_pr_state_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        github_pull_request.urllib.request,
        "urlopen",
        lambda _req, **_kwargs: _Resp(200, '{"state":"closed","merged":true,"head":{"sha":"fedcba987654"}}'),
    )

    result = github_pull_request.get_pr_state("token", "owner/repo", 12)

    assert result["state"] == "closed"
    assert result["merged"] is True
    assert result["head_sha"] == "fedcba987654"
    assert result["error"] is None


def test_get_pr_state_unknown_after_retries(monkeypatch) -> None:
    calls = {"n": 0}

    def _fail(_req, timeout=10):
        calls["n"] += 1
        raise urllib.error.URLError("timeout")

    monkeypatch.setattr(github_pull_request.urllib.request, "urlopen", _fail)

    result = github_pull_request.get_pr_state("token", "owner/repo", 12, attempts=3)

    assert calls["n"] == 3
    assert result["state"] == "unknown"
    assert result["merged"] is None
    assert result["head_sha"] is None
    assert isinstance(result["error"], str)
    assert "network_error" in str(result["error"])
