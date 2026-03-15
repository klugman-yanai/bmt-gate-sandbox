#!/usr/bin/env python3
"""Create a green VM from a pre-baked image while preserving core settings from current VM.

Required env: GCP_PROJECT, GCP_ZONE, BMT_LIVE_VM (source blue VM name).
Optional: BMT_GREEN_VM_NAME (default: <base>-green when source ends with -blue, else <source>-green),
  BMT_IMAGE_FAMILY (default from constants), BMT_IMAGE_NAME (explicit image),
  BMT_GREEN_ALLOW_RECREATE (default 0; set 1 to delete/recreate).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from whenever import Instant

from gcp.image.config.constants import DEFAULT_IMAGE_FAMILY


def main() -> int:
    project = os.environ.get("GCP_PROJECT", "").strip()
    zone = os.environ.get("GCP_ZONE", "").strip()
    vm_name = os.environ.get("BMT_LIVE_VM", "").strip()
    green_name = os.environ.get("BMT_GREEN_VM_NAME", "").strip() or (
        f"{vm_name.removesuffix('-blue')}-green" if vm_name.endswith("-blue") else f"{vm_name}-green"
    )
    image_family = os.environ.get("BMT_IMAGE_FAMILY", DEFAULT_IMAGE_FAMILY)
    image_name = os.environ.get("BMT_IMAGE_NAME", "").strip()
    allow_recreate = os.environ.get("BMT_GREEN_ALLOW_RECREATE", "0").strip() == "1"

    if not all([project, zone, vm_name]):
        print("Set GCP_PROJECT, GCP_ZONE, and BMT_LIVE_VM.", file=sys.stderr)
        return 1

    for cmd in ["gcloud", "jq"]:
        r = subprocess.run(["which", cmd], capture_output=True, check=False)
        if r.returncode != 0:
            print(f"Missing required command: {cmd}", file=sys.stderr)
            return 1

    if not image_name:
        r = subprocess.run(
            ["gcloud", "compute", "images", "describe-from-family", image_family, "--project", project, "--format=value(name)"],
            capture_output=True, text=True, check=False,
        )
        if r.returncode != 0 or not (r.stdout or "").strip():
            print(f"Could not resolve image from family {image_family} in project {project}.", file=sys.stderr)
            return 1
        image_name = r.stdout.strip()

    r = subprocess.run(
        ["gcloud", "compute", "instances", "describe", green_name, "--project", project, "--zone", zone],
        capture_output=True, text=True, check=False,
    )
    if r.returncode == 0:
        if not allow_recreate:
            print(f"Green VM {green_name} already exists. Set BMT_GREEN_ALLOW_RECREATE=1 to recreate.", file=sys.stderr)
            return 1
        print(f"Deleting existing green VM {green_name}...")
        subprocess.run(
            ["gcloud", "compute", "instances", "delete", green_name, "--project", project, "--zone", zone, "--quiet"],
            check=True,
        )

    with tempfile.TemporaryDirectory(prefix="bmt-green-vm-") as tmp_dir:
        base_json = Path(tmp_dir) / "base-vm.json"
        r = subprocess.run(
            ["gcloud", "compute", "instances", "describe", vm_name, "--project", project, "--zone", zone, "--format=json"],
            capture_output=True, text=True, check=False,
        )
        if r.returncode != 0:
            print(r.stderr or r.stdout or "describe failed", file=sys.stderr)
            return 1
        data = json.loads(r.stdout)

        machine_type = (data.get("machineType") or "").split("/")[-1]
        network = (data.get("networkInterfaces") or [{}])[0].get("network", "").split("/")[-1]
        subnetwork = (data.get("networkInterfaces") or [{}])[0].get("subnetwork", "").split("/")[-1]
        service_account = (data.get("serviceAccounts") or [{}])[0].get("email", "")
        scopes = ",".join((data.get("serviceAccounts") or [{}])[0].get("scopes", []))
        tags = ",".join((data.get("tags") or {}).get("items", []))

        disks = data.get("disks") or []
        boot = next((d for d in disks if d.get("boot")), {})
        boot_disk_source = (boot.get("source") or "").split("/")[-1]
        boot_disk_size_gb = boot.get("diskSizeGb", "")
        boot_disk_type = ""
        if boot_disk_source:
            r = subprocess.run(
                ["gcloud", "compute", "disks", "describe", boot_disk_source, "--project", project, "--zone", zone, "--format=value(type)"],
                capture_output=True, text=True, check=False,
            )
            if r.returncode == 0 and r.stdout:
                boot_disk_type = r.stdout.strip().split("/")[-1]
            r = subprocess.run(
                ["gcloud", "compute", "disks", "describe", boot_disk_source, "--project", project, "--zone", zone, "--format=value(sizeGb)"],
                capture_output=True, text=True, check=False,
            )
            if r.returncode == 0 and r.stdout:
                boot_disk_size_gb = r.stdout.strip()

        meta_items = {item["key"]: item["value"] for item in (data.get("metadata") or {}).get("items", [])}
        gcs_bucket = meta_items.get("GCS_BUCKET", "")
        bmt_repo_root = meta_items.get("BMT_REPO_ROOT", "/opt/bmt")
        startup_script = meta_items.get("startup-script", "")
        startup_script_url = meta_items.get("startup-script-url", "")

        ts_iso = Instant.now().format_iso(unit="second")
        ts_label_raw = Instant.now().format_iso(unit="second", basic=True)
        ts_label = f"{ts_label_raw[:8]}-{ts_label_raw[8:]}"  # YYYYMMDD-HHMMSS
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
        if startup_script_url:
            metadata_pairs.append(f"startup-script-url={startup_script_url}")
        else:
            metadata_pairs.append("startup-script-url=")
        metadata_str = ",".join(metadata_pairs)

        create_cmd = [
            "gcloud", "compute", "instances", "create", green_name,
            "--project", project,
            "--zone", zone,
            "--machine-type", machine_type,
            "--image", image_name,
            "--metadata", metadata_str,
            "--labels", labels,
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

        print(f"Creating green VM {green_name} from image {image_name}...")
        print(f"Inherited boot disk profile: size={boot_disk_size_gb or '<default>'}GB type={boot_disk_type or '<default>'}")
        r = subprocess.run(create_cmd, check=False)
        if r.returncode != 0:
            return 1

    print("Green VM created:")
    print(f"  vm:       {green_name}")
    print(f"  image:    {image_name}")
    print(f"  labels:   {labels}")
    print(f"  gcs:      {gcs_bucket}")
    print(f"  repoRoot: {bmt_repo_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
