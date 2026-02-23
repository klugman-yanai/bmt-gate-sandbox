"""Synchronize VM metadata keys used by watcher startup with workflow env vars."""

from __future__ import annotations

import os

import click

from ci.adapters import gcloud_cli
from ci.commands.start_vm import _required_env


@click.command("sync-vm-metadata")
def command() -> None:
    """Sync GCS_BUCKET and BMT_BUCKET_PREFIX into VM custom metadata."""
    project = _required_env("GCP_PROJECT")
    zone = _required_env("GCP_ZONE")
    instance_name = _required_env("BMT_VM_NAME")
    bucket = _required_env("GCS_BUCKET")
    prefix = (os.environ.get("BMT_BUCKET_PREFIX") or "").strip("/")

    metadata = {"GCS_BUCKET": bucket, "BMT_BUCKET_PREFIX": prefix}
    try:
        gcloud_cli.vm_add_metadata(project, zone, instance_name, metadata)
    except gcloud_cli.GcloudError as exc:
        print(f"::error::{exc}")
        raise
    prefix_rendered = prefix or "<none>"
    print(f"Synced VM metadata for {instance_name}: GCS_BUCKET={bucket} BMT_BUCKET_PREFIX={prefix_rendered}")
