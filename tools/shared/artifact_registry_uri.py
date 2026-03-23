"""Resolve BMT orchestrator Artifact Registry image URI (matches Justfile ``docker-push``)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Literal

from google.api_core import exceptions as gexc
from google.api_core.client_options import ClientOptions
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import artifactregistry_v1

logger = logging.getLogger(__name__)

ArtifactRegistryTagStatus = Literal["present", "absent", "unavailable"]


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


def parse_orchestrator_image_base(image_base: str) -> tuple[str, str, str, str]:
    """Split ``LOCATION-docker.pkg.dev/PROJECT/REPOSITORY/bmt-orchestrator`` into API parts.

    Returns ``(location, project, repository, package)`` for
    :meth:`google.cloud.artifactregistry_v1.ArtifactRegistryClient.tag_path`.
    """
    parts = image_base.split("/")
    if len(parts) != 4:
        msg = f"expected LOCATION-docker.pkg.dev/PROJECT/REPO/<image>, got {image_base!r}"
        raise ValueError(msg)
    host, project, repository, package = parts
    suffix = "-docker.pkg.dev"
    if not host.endswith(suffix):
        msg = f"expected host ending with {suffix!r}, got {host!r}"
        raise ValueError(msg)
    location = host[: -len(suffix)]
    return location, project, repository, package


def _artifact_registry_client(location: str) -> artifactregistry_v1.ArtifactRegistryClient:
    endpoint = f"{location}-artifactregistry.googleapis.com"
    return artifactregistry_v1.ArtifactRegistryClient(
        client_options=ClientOptions(api_endpoint=endpoint),
    )


def artifact_registry_tag_status(*, image_base: str, tag: str) -> ArtifactRegistryTagStatus:
    """Whether ``bmt-orchestrator`` has ``tag`` in Artifact Registry, via the Python client library.

    Uses :meth:`google.cloud.artifactregistry_v1.ArtifactRegistryClient.get_tag` (not the
    ``gcloud`` CLI). Requires `Application Default Credentials`_ (e.g. ``GOOGLE_APPLICATION_CREDENTIALS``
    or a supported metadata / user credential source).

    .. _Application Default Credentials: https://cloud.google.com/docs/authentication/application-default-credentials

    Returns:
        ``present`` — tag exists.
        ``absent`` — API reports the tag does not exist (rebuild/push needed).
        ``unavailable`` — could not query (missing credentials, permission, network, parse error).
    """
    try:
        location, project, repository, package = parse_orchestrator_image_base(image_base)
    except ValueError:
        logger.warning("artifact registry: invalid image base %r", image_base)
        return "unavailable"

    client = _artifact_registry_client(location)
    name = client.tag_path(project, location, repository, package, tag)
    try:
        client.get_tag(name=name)
    except gexc.NotFound:
        return "absent"
    except (gexc.GoogleAPICallError, DefaultCredentialsError) as exc:
        logger.info("artifact registry tag check unavailable: %s", exc)
        return "unavailable"
    except OSError as exc:
        logger.info("artifact registry tag check unavailable: %s", exc)
        return "unavailable"
    else:
        return "present"
