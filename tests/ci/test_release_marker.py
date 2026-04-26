"""Tests for the release marker module.

The release marker is the single source of truth tying together the four BMT
surfaces (Cloud Run image, GCS plugins, PEX, Pulumi stack) that a given git
commit produced. It lives at ``gs://$BUCKET/_state/release.json``.

The ``Handoff / Plan`` job asserts that the marker's ``git_sha`` matches the
workflow's ``github.sha`` before dispatching the cloud workflow; a mismatch
means the ``release.yml`` workflow did not complete for this commit and the
cloud pipeline would otherwise be running against stale artifacts.
"""

from __future__ import annotations

import json

import pytest
from kardome_bmt import gcs, release_marker
from kardome_bmt.release_marker import ReleaseMarker, ReleaseMarkerMismatchError

pytestmark = pytest.mark.unit


_BUCKET = "test-bucket"
_HEAD_SHA = "f" * 40


def _fake_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Replace gcs.{upload_json,download_json,object_exists} with an in-memory map.

    The marker module MUST route all GCS traffic through ``kardome_bmt.gcs`` so
    tests can substitute this fake without touching the network.
    """
    store: dict[str, bytes] = {}

    def _upload_json(uri: str, payload: dict) -> None:
        store[uri] = (json.dumps(payload, indent=2) + "\n").encode("utf-8")

    def _download_json(uri: str) -> tuple[dict | None, str | None]:
        raw = store.get(uri)
        if raw is None:
            return None, "not_found"
        try:
            return json.loads(raw.decode("utf-8")), None
        except json.JSONDecodeError as exc:
            return None, str(exc)

    def _object_exists(uri: str) -> bool:
        return uri in store

    monkeypatch.setattr(gcs, "upload_json", _upload_json)
    monkeypatch.setattr(gcs, "download_json", _download_json)
    monkeypatch.setattr(gcs, "object_exists", _object_exists)
    return store


def test_write_then_read_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_storage(monkeypatch)
    marker = ReleaseMarker(
        git_sha=_HEAD_SHA,
        image_digest="sha256:331fed530ad468461e6ad41802efa75078f058a6095937943eabae28151451b4",
        plugins_sha="8a1f2c3d",
        pex_tag="bmt-v0.3.3",
        pulumi_stack_sha="f7c2aa11",
        built_at="2026-04-18T12:00:00Z",
    )
    release_marker.write(_BUCKET, marker)

    loaded = release_marker.read(_BUCKET)
    assert loaded == marker


def test_read_missing_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_storage(monkeypatch)
    assert release_marker.read(_BUCKET) is None


def test_assert_matches_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_storage(monkeypatch)
    marker = ReleaseMarker(
        git_sha=_HEAD_SHA,
        image_digest="sha256:aaa",
        plugins_sha="bbb",
        pex_tag="bmt-v0.3.3",
        pulumi_stack_sha=None,
        built_at="2026-04-18T12:00:00Z",
    )
    release_marker.write(_BUCKET, marker)
    release_marker.assert_matches(_BUCKET, _HEAD_SHA)


def test_assert_matches_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_storage(monkeypatch)
    marker = ReleaseMarker(
        git_sha="0" * 40,
        image_digest=None,
        plugins_sha=None,
        pex_tag=None,
        pulumi_stack_sha=None,
        built_at="2026-04-18T12:00:00Z",
    )
    release_marker.write(_BUCKET, marker)

    with pytest.raises(ReleaseMarkerMismatchError) as excinfo:
        release_marker.assert_matches(_BUCKET, _HEAD_SHA)

    msg = str(excinfo.value)
    assert _HEAD_SHA[:12] in msg
    assert "0" * 12 in msg
    assert "release.yml" in msg.lower() or "release workflow" in msg.lower()


def test_assert_matches_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_storage(monkeypatch)
    with pytest.raises(ReleaseMarkerMismatchError) as excinfo:
        release_marker.assert_matches(_BUCKET, _HEAD_SHA)

    msg = str(excinfo.value)
    assert "missing" in msg.lower() or "not found" in msg.lower()
    assert "release.yml" in msg.lower() or "release workflow" in msg.lower()


def test_marker_serialization_is_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard: the JSON on disk is deterministic so drifting schemas are caught by diff review."""
    store = _fake_storage(monkeypatch)
    marker = ReleaseMarker(
        git_sha=_HEAD_SHA,
        image_digest="sha256:abc",
        plugins_sha="deadbeef",
        pex_tag="bmt-v0.3.3",
        pulumi_stack_sha="f7c2aa11",
        built_at="2026-04-18T12:00:00Z",
    )
    release_marker.write(_BUCKET, marker)

    raw = store["gs://test-bucket/_state/release.json"].decode("utf-8")
    payload = json.loads(raw)
    assert set(payload.keys()) == {
        "git_sha",
        "image_digest",
        "plugins_sha",
        "pex_tag",
        "pulumi_stack_sha",
        "built_at",
    }
    assert payload["git_sha"] == _HEAD_SHA


def test_read_rejects_invalid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """A corrupted marker file must NOT be silently treated as 'missing'."""
    store = _fake_storage(monkeypatch)
    store["gs://test-bucket/_state/release.json"] = b'{"git_sha": 123}'

    with pytest.raises(ReleaseMarkerMismatchError) as excinfo:
        release_marker.assert_matches(_BUCKET, _HEAD_SHA)

    assert "invalid" in str(excinfo.value).lower() or "malformed" in str(excinfo.value).lower()
