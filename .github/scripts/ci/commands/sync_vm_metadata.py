"""Synchronize VM metadata keys used by watcher startup with workflow env vars."""

from __future__ import annotations

import os
from pathlib import Path

import click

from ci import models
from ci.adapters import gcloud_cli
from ci.commands.start_vm import _required_env


def _metadata_items(payload: dict[str, object]) -> dict[str, str]:
    out: dict[str, str] = {}
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return out
    items = metadata.get("items")
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        if isinstance(key, str) and isinstance(value, str):
            out[key] = value
    return out


def _build_desired_metadata(
    bucket: str,
    repo_root: str,
    wrapper_path: Path,
) -> tuple[dict[str, str], str]:
    """Return (metadata_dict, startup_script_content)."""
    metadata = {
        "GCS_BUCKET": bucket,
        "BMT_REPO_ROOT": repo_root,
        "startup-script-url": "",
    }
    script_content = wrapper_path.read_text(encoding="utf-8")
    return metadata, script_content


@click.command("sync-vm-metadata")
@click.option(
    "--force",
    is_flag=True,
    help="Force sync even if VM metadata already matches (default: skip when in sync).",
)
def command(*, force: bool) -> None:
    """Sync startup-critical VM metadata and inline startup wrapper from the repository."""
    project = _required_env("GCP_PROJECT")
    zone = _required_env("GCP_ZONE")
    instance_name = _required_env("BMT_VM_NAME")
    bucket = _required_env("GCS_BUCKET")
    repo_root = (os.environ.get("BMT_REPO_ROOT") or "/opt/bmt").strip() or "/opt/bmt"
    code_root = models.code_bucket_root_uri(bucket)
    repo_root_path = Path(__file__).resolve().parents[4]
    wrapper_path = repo_root_path / "remote" / "code" / "bootstrap" / "startup_wrapper.sh"
    if not wrapper_path.is_file():
        raise click.ClickException(f"Missing canonical startup wrapper in repo: {wrapper_path}")

    required_code_objects = (
        f"{code_root}/pyproject.toml",
        f"{code_root}/uv.lock",
        f"{code_root}/bootstrap/startup_example.sh",
        f"{code_root}/vm_watcher.py",
        f"{code_root}/root_orchestrator.py",
        f"{code_root}/_tools/uv/linux-x86_64/uv",
        f"{code_root}/_tools/uv/linux-x86_64/uv.sha256",
    )
    missing_objects = [uri for uri in required_code_objects if not gcloud_cli.gcs_exists(uri)]
    if missing_objects:
        joined = "\n".join(f"  - {uri}" for uri in missing_objects)
        raise click.ClickException(
            "Missing required code objects in bucket namespace. "
            "Sync code mirror first (just sync-remote && just verify-sync):\n"
            f"{joined}"
        )

    # Fail-fast: reject non-empty legacy BMT_BUCKET_PREFIX in VM metadata
    try:
        described = gcloud_cli.vm_describe(project, zone, instance_name)
    except gcloud_cli.GcloudError:
        described = None
    if described:
        current = _metadata_items(described)
        legacy_prefix = current.get("BMT_BUCKET_PREFIX", "").strip()
        if legacy_prefix:
            raise click.ClickException(
                f"Legacy BMT_BUCKET_PREFIX='{legacy_prefix}' found in VM metadata for {instance_name}. "
                "BMT_BUCKET_PREFIX has been removed. Clear the VM metadata key before proceeding."
            )

    desired_metadata, desired_script = _build_desired_metadata(bucket, repo_root, wrapper_path)

    if not force and described:
        current = _metadata_items(described)
        if (
            all(current.get(k) == v for k, v in desired_metadata.items())
            and current.get("startup-script", "").strip() == desired_script.strip()
        ):
            print(f"VM metadata for {instance_name} already in sync; skipping. Use --force to re-sync.")
            return

    metadata = {
        "GCS_BUCKET": bucket,
        "BMT_REPO_ROOT": repo_root,
        # Keep startup-script-url empty so only the inline wrapper executes
        # during workflow-driven runs.
        "startup-script-url": "",
    }
    try:
        gcloud_cli.vm_add_metadata(
            project,
            zone,
            instance_name,
            metadata,
            metadata_files={"startup-script": wrapper_path},
        )
        described = gcloud_cli.vm_describe(project, zone, instance_name)
    except gcloud_cli.GcloudError as exc:
        print(f"::error::{exc}")
        raise

    items = _metadata_items(described)
    if items.get("GCS_BUCKET", "").strip() != bucket:
        raise click.ClickException("VM metadata verification failed: GCS_BUCKET did not persist.")
    if items.get("BMT_REPO_ROOT", "").strip() != repo_root:
        raise click.ClickException("VM metadata verification failed: BMT_REPO_ROOT did not persist.")
    if not (items.get("startup-script", "")).strip():
        raise click.ClickException("VM metadata verification failed: startup-script is missing/empty.")
    if (items.get("startup-script-url", "")).strip():
        raise click.ClickException("VM metadata verification failed: startup-script-url is not cleared.")

    print(f"Synced VM metadata for {instance_name}: GCS_BUCKET={bucket} BMT_REPO_ROOT={repo_root}")
    print(f"Updated inline startup-script from {wrapper_path}")
