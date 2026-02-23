"""Start the BMT VM so it can process the run trigger written by the trigger step."""

from __future__ import annotations

import os

import click

from ci.adapters import gcloud_cli


def _required_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Set {name}.")
    return value


@click.command("start-vm")
def command() -> None:
    """Start the BMT VM (reads GCP_PROJECT, GCP_ZONE, BMT_VM_NAME from env)."""
    project = _required_env("GCP_PROJECT")
    zone = _required_env("GCP_ZONE")
    instance_name = _required_env("BMT_VM_NAME")
    try:
        gcloud_cli.vm_start(project, zone, instance_name)
    except gcloud_cli.GcloudError as exc:
        print(f"::error::{exc}")
        raise
    print(f"Started VM {instance_name} (zone={zone})")
