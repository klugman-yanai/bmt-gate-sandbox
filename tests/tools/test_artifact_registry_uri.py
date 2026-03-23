"""Tests for Artifact Registry URI resolution and tag probes (google-cloud-artifact-registry)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import google.auth.exceptions
import pytest
from google.api_core import exceptions as gexc
from google.cloud import artifactregistry_v1

from tools.shared.artifact_registry_uri import (
    artifact_registry_tag_status,
    resolve_bmt_orchestrator_image_base,
)

_IMAGE_BASE = "europe-west4-docker.pkg.dev/proj-x/my-repo/bmt-orchestrator"
_FULL_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


def test_resolve_bmt_orchestrator_image_base_defaults(tmp_path: Path) -> None:
    """Without tfvars, match Justfile fallbacks."""
    (tmp_path / "infra" / "pulumi").mkdir(parents=True)
    assert (
        resolve_bmt_orchestrator_image_base(tmp_path)
        == "europe-west4-docker.pkg.dev/train-kws-202311/bmt-images/bmt-orchestrator"
    )


def test_resolve_bmt_orchestrator_image_base_from_tfvars(tmp_path: Path) -> None:
    pulumi_dir = tmp_path / "infra" / "pulumi"
    pulumi_dir.mkdir(parents=True)
    (pulumi_dir / "bmt.tfvars.json").write_text(
        json.dumps(
            {
                "gcp_project": "proj-x",
                "cloud_run_region": "us-central1",
                "artifact_registry_repo": "my-repo",
            }
        ),
        encoding="utf-8",
    )
    assert resolve_bmt_orchestrator_image_base(tmp_path) == "us-central1-docker.pkg.dev/proj-x/my-repo/bmt-orchestrator"


def test_artifact_registry_tag_status_invalid_tag() -> None:
    assert artifact_registry_tag_status(image_base=_IMAGE_BASE, tag="not-a-sha") == "unavailable"


def test_artifact_registry_tag_status_no_adc(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_creds(**_: object) -> None:
        raise google.auth.exceptions.DefaultCredentialsError()

    monkeypatch.setattr("tools.shared.artifact_registry_uri.google.auth.default", _no_creds)
    assert artifact_registry_tag_status(image_base=_IMAGE_BASE, tag=_FULL_SHA) == "unavailable"


def test_artifact_registry_tag_status_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    creds = MagicMock()
    monkeypatch.setattr(
        "tools.shared.artifact_registry_uri.google.auth.default",
        lambda **_: (creds, "proj-x"),
    )

    def _get_tag(self: object, name: str | None = None, **_: object) -> None:
        assert name is not None
        assert f"tags/{_FULL_SHA}" in name
        raise gexc.NotFound("no such tag")

    monkeypatch.setattr(artifactregistry_v1.ArtifactRegistryClient, "get_tag", _get_tag)
    assert artifact_registry_tag_status(image_base=_IMAGE_BASE, tag=_FULL_SHA) == "absent"


def test_artifact_registry_tag_status_present(monkeypatch: pytest.MonkeyPatch) -> None:
    creds = MagicMock()
    monkeypatch.setattr(
        "tools.shared.artifact_registry_uri.google.auth.default",
        lambda **_: (creds, "proj-x"),
    )

    def _get_tag(self: object, name: str | None = None, **_: object) -> object:
        assert name is not None
        assert f"tags/{_FULL_SHA}" in name
        return object()

    monkeypatch.setattr(artifactregistry_v1.ArtifactRegistryClient, "get_tag", _get_tag)
    assert artifact_registry_tag_status(image_base=_IMAGE_BASE, tag=_FULL_SHA) == "present"


def test_artifact_registry_tag_status_permission_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    creds = MagicMock()
    monkeypatch.setattr(
        "tools.shared.artifact_registry_uri.google.auth.default",
        lambda **_: (creds, "proj-x"),
    )

    def _get_tag(self: object, name: str | None = None, **_: object) -> None:
        raise gexc.PermissionDenied("denied")

    monkeypatch.setattr(artifactregistry_v1.ArtifactRegistryClient, "get_tag", _get_tag)
    assert artifact_registry_tag_status(image_base=_IMAGE_BASE, tag=_FULL_SHA) == "permission_denied"


def test_artifact_registry_tag_status_transient_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    creds = MagicMock()
    monkeypatch.setattr(
        "tools.shared.artifact_registry_uri.google.auth.default",
        lambda **_: (creds, "proj-x"),
    )

    def _get_tag(self: object, name: str | None = None, **_: object) -> None:
        raise gexc.InternalServerError("boom")

    monkeypatch.setattr(artifactregistry_v1.ArtifactRegistryClient, "get_tag", _get_tag)
    assert artifact_registry_tag_status(image_base=_IMAGE_BASE, tag=_FULL_SHA) == "unavailable"
