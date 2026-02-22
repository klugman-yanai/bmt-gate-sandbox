"""Start the BMT VM so it can process the run trigger written by the trigger step."""

from __future__ import annotations

import os

import click

from ci.adapters import gcloud_cli


def _project_from_sa_email(sa_email: str) -> str | None:
    """Derive GCP project ID from service account email (e.g. x@PROJECT.iam.gserviceaccount.com)."""
    sa_email = (sa_email or "").strip()
    if "@" not in sa_email:
        return None
    domain = sa_email.split("@", 1)[1]
    if domain.endswith(".iam.gserviceaccount.com"):
        return domain.removesuffix(".iam.gserviceaccount.com") or None
    return None


@click.command("start-vm")
def command() -> None:
    """Start the BMT VM (reads GCP_PROJECT or GCP_SA_EMAIL, GCP_ZONE, BMT_VM_NAME from env)."""
    project = (os.environ.get("GCP_PROJECT") or "").strip()
    if not project:
        project = _project_from_sa_email(os.environ.get("GCP_SA_EMAIL") or "") or ""
    zone = (os.environ.get("GCP_ZONE") or "").strip()
    instance_name = (os.environ.get("BMT_VM_NAME") or os.environ.get("VM_NAME") or "").strip()
    if not project or not zone or not instance_name:
        raise RuntimeError(
            "Set GCP_ZONE and BMT_VM_NAME (or VM_NAME). "
            "Set GCP_PROJECT or GCP_SA_EMAIL (project is derived from SA email if unset)."
        )
    try:
        gcloud_cli.vm_start(project, zone, instance_name)
    except gcloud_cli.GcloudError as exc:
        print(f"::error::{exc}")
        raise
    print(f"Started VM {instance_name} (zone={zone})")
