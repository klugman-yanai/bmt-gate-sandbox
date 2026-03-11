"""Tests for gcp/code/lib/github_pr_comment.py."""

from __future__ import annotations

import json
from typing import Any

import github_pr_comment  # type: ignore[import-not-found]


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


def _request_body(req: Any) -> dict[str, Any]:
    raw = getattr(req, "data", None)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def test_upsert_pr_comment_by_marker_creates_when_missing(monkeypatch) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def _urlopen(req, timeout=30):
        method = req.get_method()
        url = req.full_url
        calls.append((method, url, _request_body(req)))
        if method == "GET":
            return _Resp(200, "[]")
        if method == "POST":
            return _Resp(201, '{"id": 101, "body": "created"}')
        raise AssertionError(f"unexpected method: {method}")

    monkeypatch.setattr(github_pr_comment.urllib.request, "urlopen", _urlopen)

    ok = github_pr_comment.upsert_pr_comment_by_marker(
        "token",
        "owner/repo",
        42,
        "<!-- bmt-vm-comment-sha:abc -->",
        "comment body",
    )

    assert ok is True
    assert [method for method, _, _ in calls] == ["GET", "POST"]
    assert calls[-1][2] == {"body": "comment body"}


def test_upsert_pr_comment_by_marker_updates_existing(monkeypatch) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def _urlopen(req, timeout=30):
        method = req.get_method()
        url = req.full_url
        calls.append((method, url, _request_body(req)))
        if method == "GET":
            return _Resp(
                200,
                '[{"id":77,"body":"header\\n<!-- bmt-vm-comment-sha:abc -->\\nold"}]',
            )
        if method == "PATCH":
            return _Resp(200, '{"id": 77, "body": "updated"}')
        raise AssertionError(f"unexpected method: {method}")

    monkeypatch.setattr(github_pr_comment.urllib.request, "urlopen", _urlopen)

    ok = github_pr_comment.upsert_pr_comment_by_marker(
        "token",
        "owner/repo",
        42,
        "<!-- bmt-vm-comment-sha:abc -->",
        "new body",
    )

    assert ok is True
    assert [method for method, _, _ in calls] == ["GET", "PATCH"]
    assert calls[-1][1].endswith("/issues/comments/77")
    assert calls[-1][2] == {"body": "new body"}
