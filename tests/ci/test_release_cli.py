"""Integration tests for the ``bmt release …`` subcommands.

Drives the Typer app via :class:`typer.testing.CliRunner` (same pattern as
the existing ``tests/ci/test_ci_commands.py``) so command wiring, env var
fallbacks, exit codes, and GitHub Actions annotations are all covered.
"""

from __future__ import annotations

import json

import pytest
from kardome_bmt import gcs, release_marker
from kardome_bmt.driver import app as driver_app
from typer.testing import CliRunner

pytestmark = pytest.mark.unit


_BUCKET = "test-bucket"
_HEAD_SHA = "a" * 40


def _fake_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    store: dict[str, bytes] = {}

    def _upload_json(uri: str, payload: dict) -> None:
        store[uri] = (json.dumps(payload, indent=2) + "\n").encode("utf-8")

    def _download_json(uri: str) -> tuple[dict | None, str | None]:
        raw = store.get(uri)
        if raw is None:
            return None, "not_found"
        return json.loads(raw.decode("utf-8")), None

    def _object_exists(uri: str) -> bool:
        return uri in store

    monkeypatch.setattr(gcs, "upload_json", _upload_json)
    monkeypatch.setattr(gcs, "download_json", _download_json)
    monkeypatch.setattr(gcs, "object_exists", _object_exists)
    return store


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCS_BUCKET", _BUCKET)
    monkeypatch.setenv("GITHUB_SHA", _HEAD_SHA)
    for v in (
        "RELEASE_IMAGE_DIGEST",
        "RELEASE_PLUGINS_SHA",
        "RELEASE_PEX_TAG",
        "RELEASE_PULUMI_STACK_SHA",
    ):
        monkeypatch.delenv(v, raising=False)


def test_mark_writes_marker_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    store = _fake_storage(monkeypatch)
    monkeypatch.setenv("RELEASE_IMAGE_DIGEST", "sha256:deadbeef")
    monkeypatch.setenv("RELEASE_PLUGINS_SHA", "cafef00d")
    monkeypatch.setenv("RELEASE_PEX_TAG", "bmt-v0.3.3")

    runner = CliRunner()
    result = runner.invoke(driver_app, ["release", "mark"])

    assert result.exit_code == 0, result.output
    assert "wrote gs://test-bucket/_state/release.json" in result.output
    assert _HEAD_SHA[:12] in result.output

    payload = json.loads(store["gs://test-bucket/_state/release.json"])
    assert payload["git_sha"] == _HEAD_SHA
    assert payload["image_digest"] == "sha256:deadbeef"
    assert payload["plugins_sha"] == "cafef00d"
    assert payload["pex_tag"] == "bmt-v0.3.3"
    assert payload["pulumi_stack_sha"] is None
    assert payload["built_at"].endswith("Z")


def test_mark_flags_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    store = _fake_storage(monkeypatch)
    monkeypatch.setenv("RELEASE_IMAGE_DIGEST", "sha256:from_env")

    runner = CliRunner()
    result = runner.invoke(
        driver_app,
        [
            "release",
            "mark",
            "--bucket",
            "override-bucket",
            "--image-digest",
            "sha256:from_flag",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(store["gs://override-bucket/_state/release.json"])
    assert payload["image_digest"] == "sha256:from_flag"


def test_mark_fails_without_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    _fake_storage(monkeypatch)
    monkeypatch.delenv("GCS_BUCKET", raising=False)

    runner = CliRunner()
    result = runner.invoke(driver_app, ["release", "mark"])

    assert result.exit_code != 0
    assert "GCS_BUCKET" in result.output


def test_verify_passes_when_marker_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    _fake_storage(monkeypatch)
    release_marker.write(
        _BUCKET,
        release_marker.ReleaseMarker(
            git_sha=_HEAD_SHA,
            image_digest=None,
            plugins_sha=None,
            pex_tag=None,
            pulumi_stack_sha=None,
            built_at="2026-04-18T12:00:00Z",
        ),
    )

    runner = CliRunner()
    result = runner.invoke(driver_app, ["release", "verify"])

    assert result.exit_code == 0, result.output
    assert "release marker OK" in result.output
    assert _HEAD_SHA[:12] in result.output


def test_verify_exits_nonzero_on_missing_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    _fake_storage(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(driver_app, ["release", "verify"])

    assert result.exit_code == 2
    combined = (result.output or "") + (result.stderr if result.stderr_bytes else "")
    assert "::error::" in combined
    assert "release marker is missing" in combined


def test_verify_exits_nonzero_on_sha_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    _fake_storage(monkeypatch)
    release_marker.write(
        _BUCKET,
        release_marker.ReleaseMarker(
            git_sha="0" * 40,
            image_digest=None,
            plugins_sha=None,
            pex_tag=None,
            pulumi_stack_sha=None,
            built_at="2026-04-18T12:00:00Z",
        ),
    )

    runner = CliRunner()
    result = runner.invoke(driver_app, ["release", "verify"])

    assert result.exit_code == 2
    combined = (result.output or "") + (result.stderr if result.stderr_bytes else "")
    assert "::error::" in combined
    assert "mismatch" in combined.lower()
    assert _HEAD_SHA[:12] in combined
    assert "000000000000" in combined


def test_verify_flag_overrides_env_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    _fake_storage(monkeypatch)
    alt_sha = "b" * 40
    release_marker.write(
        _BUCKET,
        release_marker.ReleaseMarker(
            git_sha=alt_sha,
            image_digest=None,
            plugins_sha=None,
            pex_tag=None,
            pulumi_stack_sha=None,
            built_at="2026-04-18T12:00:00Z",
        ),
    )

    runner = CliRunner()
    result = runner.invoke(driver_app, ["release", "verify", "--sha", alt_sha])

    assert result.exit_code == 0, result.output


def test_release_appears_in_help() -> None:
    """Regression guard: the subcommand group must be registered on the root ``bmt`` CLI."""
    runner = CliRunner()
    result = runner.invoke(driver_app, ["--help"])
    assert result.exit_code == 0
    assert "release" in result.output
