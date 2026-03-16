#!/usr/bin/env python3
"""Create a green VM from a pre-baked image while preserving core settings from current VM.

Required env: GCP_PROJECT, BMT_LIVE_VM (source blue VM name).
Optional: BMT_GREEN_VM_NAME, BMT_IMAGE_FAMILY, BMT_IMAGE_NAME, BMT_GREEN_ALLOW_RECREATE. Zone is fixed (europe-west4-a).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from whenever import Instant

from gcp.image.config.constants import DEFAULT_GCP_ZONE, DEFAULT_IMAGE_FAMILY


def _have_required_commands() -> bool:
    for cmd in ["gcloud", "jq"]:
        r = subprocess.run(["which", cmd], capture_output=True, check=False)
        if r.returncode != 0:
            return False
    return True


def _resolve_image_name(project: str, image_family: str, image_name: str) -> str | None:
    """Return image name from env or describe-from-family. None on failure."""
    if image_name:
        return image_name
    r = subprocess.run(
        [
            "gcloud",
            "compute",
            "images",
            "describe-from-family",
            image_family,
            "--project",
            project,
            "--format=value(name)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    return r.stdout.strip()


def _ensure_green_absent(project: str, zone: str, green_name: str, *, allow_recreate: bool) -> bool:
    """If green VM exists and allow_recreate: delete it. If exists and not allow_recreate: return False. Else True."""
    r = subprocess.run(
        ["gcloud", "compute", "instances", "describe", green_name, "--project", project, "--zone", zone],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return True
    if not allow_recreate:
        return False
    subprocess.run(
        ["gcloud", "compute", "instances", "delete", green_name, "--project", project, "--zone", zone, "--quiet"],
        check=True,
    )
    return True


def _describe_blue_vm(project: str, zone: str, vm_name: str) -> dict | None:
    """Describe blue VM, return parsed JSON or None."""
    r = subprocess.run(
        [
            "gcloud",
            "compute",
            "instances",
            "describe",
            vm_name,
            "--project",
            project,
            "--zone",
            zone,
            "--format=json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)


def _boot_disk_size_and_type(project: str, zone: str, data: dict) -> tuple[str, str]:
    """Return (boot_disk_size_gb, boot_disk_type) from blue VM data."""
    disks = data.get("disks") or []
    boot = next((d for d in disks if d.get("boot")), {})
    boot_disk_source = (boot.get("source") or "").split("/")[-1]
    size_gb = boot.get("diskSizeGb", "")
    disk_type = ""
    if not boot_disk_source:
        return size_gb, disk_type
    r = subprocess.run(
        [
            "gcloud",
            "compute",
            "disks",
            "describe",
            boot_disk_source,
            "--project",
            project,
            "--zone",
            zone,
            "--format=value(type)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode == 0 and r.stdout:
        disk_type = r.stdout.strip().split("/")[-1]
    r = subprocess.run(
        [
            "gcloud",
            "compute",
            "disks",
            "describe",
            boot_disk_source,
            "--project",
            project,
            "--zone",
            zone,
            "--format=value(sizeGb)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode == 0 and r.stdout:
        size_gb = r.stdout.strip()
    return size_gb, disk_type


def _metadata_str_and_labels(data: dict, image_family: str, image_name: str) -> tuple[str, str]:
    """Build metadata string and labels from blue VM data."""
    meta_items = {item["key"]: item["value"] for item in (data.get("metadata") or {}).get("items", [])}
    gcs_bucket = meta_items.get("GCS_BUCKET", "")
    bmt_repo_root = meta_items.get("BMT_REPO_ROOT", "/opt/bmt")
    startup_script_url = meta_items.get("startup-script-url", "")
    ts_iso = Instant.now().format_iso(unit="second")
    ts_label_raw = Instant.now().format_iso(unit="second", basic=True)
    ts_label = f"{ts_label_raw[:8]}-{ts_label_raw[8:]}"
    family_label = re.sub(r"[^a-z0-9-]", "", image_family.lower().replace("_", "-"))
    version_label = re.sub(r"[^a-z0-9-]", "", image_name.lower().replace("_", "-"))
    labels = f"bmt-image-family={family_label},bmt-image-version={version_label},bmt-bake-timestamp={ts_label}"
    metadata_pairs = [
        f"GCS_BUCKET={gcs_bucket}",
        f"BMT_REPO_ROOT={bmt_repo_root}",
        f"bmt_image_family={image_family}",
        f"bmt_image_version={image_name}",
        f"bmt_bake_timestamp={ts_iso}",
    ]
    metadata_pairs.append(f"startup-script-url={startup_script_url}" if startup_script_url else "startup-script-url=")
    return ",".join(metadata_pairs), labels


def _build_create_cmd(
    data: dict,
    project: str,
    zone: str,
    green_name: str,
    image_name: str,
    image_family: str,
    tmp_dir: str,
) -> list[str]:
    """Build gcloud compute instances create command from blue VM data."""
    ni = (data.get("networkInterfaces") or [{}])[0]
    sa = (data.get("serviceAccounts") or [{}])[0]
    machine_type = (data.get("machineType") or "").split("/")[-1]
    network = ni.get("network", "").split("/")[-1]
    subnetwork = ni.get("subnetwork", "").split("/")[-1]
    service_account = sa.get("email", "")
    scopes = ",".join(sa.get("scopes", []))
    tags = ",".join((data.get("tags") or {}).get("items", []))
    boot_disk_size_gb, boot_disk_type = _boot_disk_size_and_type(project, zone, data)
    metadata_str, labels = _metadata_str_and_labels(data, image_family, image_name)
    meta_items = {item["key"]: item["value"] for item in (data.get("metadata") or {}).get("items", [])}
    startup_script = meta_items.get("startup-script", "")

    create_cmd = [
        "gcloud",
        "compute",
        "instances",
        "create",
        green_name,
        "--project",
        project,
        "--zone",
        zone,
        "--machine-type",
        machine_type,
        "--image",
        image_name,
        "--metadata",
        metadata_str,
        "--labels",
        labels,
    ]
    if network:
        create_cmd.extend(["--network", network])
    if subnetwork:
        create_cmd.extend(["--subnet", subnetwork])
    if service_account:
        create_cmd.extend(["--service-account", service_account])
    if scopes:
        create_cmd.extend(["--scopes", scopes])
    if boot_disk_size_gb:
        create_cmd.extend(["--boot-disk-size", f"{boot_disk_size_gb}GB"])
    if boot_disk_type:
        create_cmd.extend(["--boot-disk-type", boot_disk_type])
    if tags:
        create_cmd.extend(["--tags", tags])
    if startup_script:
        script_file = Path(tmp_dir) / "startup-script.sh"
        script_file.write_text(startup_script, encoding="utf-8")
        create_cmd.extend(["--metadata-from-file", f"startup-script={script_file}"])
    return create_cmd


def main() -> int:
    project = os.environ.get("GCP_PROJECT", "").strip()
    zone = DEFAULT_GCP_ZONE
    vm_name = os.environ.get("BMT_LIVE_VM", "").strip()
    green_name = os.environ.get("BMT_GREEN_VM_NAME", "").strip() or (
        f"{vm_name.removesuffix('-blue')}-green" if vm_name.endswith("-blue") else f"{vm_name}-green"
    )
    image_family = os.environ.get("BMT_IMAGE_FAMILY", DEFAULT_IMAGE_FAMILY)
    image_name_from_env = os.environ.get("BMT_IMAGE_NAME", "").strip()
    allow_recreate = os.environ.get("BMT_GREEN_ALLOW_RECREATE", "0").strip() == "1"

    if not all([project, zone, vm_name]) or not _have_required_commands():
        return 1
    image_name = _resolve_image_name(project, image_family, image_name_from_env)
    if not image_name:
        return 1
    if not _ensure_green_absent(project, zone, green_name, allow_recreate=allow_recreate):
        return 1

    with tempfile.TemporaryDirectory(prefix="bmt-green-vm-") as tmp_dir:
        data = _describe_blue_vm(project, zone, vm_name)
        if data is None:
            return 1
        create_cmd = _build_create_cmd(data, project, zone, green_name, image_name, image_family, tmp_dir)
        r = subprocess.run(create_cmd, check=False)
        if r.returncode != 0:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
