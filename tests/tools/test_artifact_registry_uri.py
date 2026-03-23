"""Tests for Artifact Registry URI resolution and tag presence checks."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from google.api_core import exceptions as gexc
from google.auth.exceptions import DefaultCredentialsError

from tools.shared.artifact_registry_uri import (
    artifact_registry_tag_status,
    parse_orchestrator_image_base,
    resolve_bmt_orchestrator_image_base,
)


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


def test_parse_orchestrator_image_base() -> None:
    loc, proj, repo, pkg = parse_orchestrator_image_base("europe-west4-docker.pkg.dev/my-p/bmt-images/bmt-orchestrator")
    assert (loc, proj, repo, pkg) == ("europe-west4", "my-p", "bmt-images", "bmt-orchestrator")


def test_artifact_registry_tag_status_present(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.tag_path.return_value = (
        "projects/p/locations/europe-west4/repositories/r/packages/bmt-orchestrator/tags/abc"
    )
    mock_client.get_tag.return_value = MagicMock()

    def _factory(_location: str) -> MagicMock:
        return mock_client

    monkeypatch.setattr(
        "tools.shared.artifact_registry_uri._artifact_registry_client",
        _factory,
    )
    assert (
        artifact_registry_tag_status(
            image_base="europe-west4-docker.pkg.dev/p/r/bmt-orchestrator",
            tag="abc",
        )
        == "present"
    )
    mock_client.get_tag.assert_called_once()


def test_artifact_registry_tag_status_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.tag_path.return_value = "projects/p/.../tags/missing"
    mock_client.get_tag.side_effect = gexc.NotFound("not found")

    monkeypatch.setattr(
        "tools.shared.artifact_registry_uri._artifact_registry_client",
        lambda _loc: mock_client,
    )
    assert (
        artifact_registry_tag_status(
            image_base="europe-west4-docker.pkg.dev/p/r/bmt-orchestrator",
            tag="missing",
        )
        == "absent"
    )


def test_artifact_registry_tag_status_unavailable_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.tag_path.return_value = "x"
    mock_client.get_tag.side_effect = DefaultCredentialsError()

    monkeypatch.setattr(
        "tools.shared.artifact_registry_uri._artifact_registry_client",
        lambda _loc: mock_client,
    )
    assert (
        artifact_registry_tag_status(
            image_base="europe-west4-docker.pkg.dev/p/r/bmt-orchestrator",
            tag="t",
        )
        == "unavailable"
    )


def test_artifact_registry_tag_status_unavailable_bad_base() -> None:
    assert artifact_registry_tag_status(image_base="not-a-valid-base", tag="t") == "unavailable"
