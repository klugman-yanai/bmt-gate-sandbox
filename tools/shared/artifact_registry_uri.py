"""Resolve BMT orchestrator Artifact Registry image URI (matches Justfile ``docker-push``)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Literal

import google.auth
import google.auth.exceptions
from google.api_core import exceptions as gexc
from google.cloud import artifactregistry_v1

ArtifactRegistryTagStatus = Literal["present", "absent", "unavailable"]

# Full git SHA (40 hex) or short; AR tag names must match what docker push uses.
_GIT_SHA_TAG_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


def _pulumi_stack_output(pulumi_dir: Path, key: str) -> str | None:
    if not pulumi_dir.is_dir():
        return None
    p = subprocess.run(
        ["pulumi", "stack", "output", key],
        cwd=pulumi_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if p.returncode == 0 and (v := p.stdout.strip()):
        return v
    return None


def _tfvars_str(pulumi_dir: Path, key: str) -> str | None:
    path = pulumi_dir / "bmt.tfvars.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get(key)
    return str(raw).strip() if isinstance(raw, str) and raw.strip() else None


def resolve_bmt_orchestrator_image_base(repo_root: Path) -> str:
    """Return ``REGION-docker.pkg.dev/PROJECT/REPO/bmt-orchestrator`` (no tag).

    Resolution order matches ``docker-push`` in the Justfile: Pulumi output, env, tfvars, defaults.
    """
    pulumi_dir = repo_root / "infra" / "pulumi"
    project = (
        _pulumi_stack_output(pulumi_dir, "gcp_project")
        or os.environ.get("GCP_PROJECT", "").strip()
        or _tfvars_str(pulumi_dir, "gcp_project")
        or "train-kws-202311"
    )
    region = (
        os.environ.get("CLOUD_RUN_REGION", "").strip() or _tfvars_str(pulumi_dir, "cloud_run_region") or "europe-west4"
    )
    repo = (
        os.environ.get("ARTIFACT_REGISTRY_REPO", "").strip()
        or _tfvars_str(pulumi_dir, "artifact_registry_repo")
        or "bmt-images"
    )
    return f"{region}-docker.pkg.dev/{project}/{repo}/bmt-orchestrator"


def _parse_docker_image_base(image_base: str) -> tuple[str, str, str, str]:
    """Parse ``LOCATION-docker.pkg.dev/PROJECT/REPOSITORY/IMAGE`` into API components."""
    marker = "-docker.pkg.dev/"
    if marker not in image_base:
        raise ValueError(f"expected *-docker.pkg.dev/ host, got {image_base!r}")
    location, tail = image_base.split(marker, 1)
    parts = tail.split("/")
    if len(parts) != 3:
        raise ValueError(f"expected project/repository/image, got {image_base!r}")
    project, repository, image_name = parts
    if not location or not project or not repository or not image_name:
        raise ValueError(f"empty path segment in {image_base!r}")
    return project, location, repository, image_name


def artifact_registry_tag_status(*, image_base: str, tag: str) -> ArtifactRegistryTagStatus:
    """Whether Artifact Registry has a Docker tag for this image (via ``google-cloud-artifact-registry``).

    Uses Application Default Credentials (``google.auth.default()``), not the gcloud CLI.

    Returns:
        ``present`` — ``get_tag`` succeeded for ``bmt-orchestrator:<tag>``.
        ``absent`` — tag not found (safe to build/push).
        ``unavailable`` — could not run the check (invalid URI, no ADC, or API error).
    """
    tag = tag.strip()
    if not _GIT_SHA_TAG_RE.match(tag):
        return "unavailable"
    try:
        project, location, repository, package = _parse_docker_image_base(image_base)
    except ValueError:
        return "unavailable"
    try:
        google.auth.default()
    except google.auth.exceptions.DefaultCredentialsError:
        return "unavailable"

    name = artifactregistry_v1.ArtifactRegistryClient.tag_path(project, location, repository, package, tag)
    client = artifactregistry_v1.ArtifactRegistryClient()
    try:
        client.get_tag(name=name)
    except gexc.NotFound:
        return "absent"
    except gexc.GoogleAPICallError:
        return "unavailable"
    return "present"
