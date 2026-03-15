#!/usr/bin/env python3
# LEGACY: Prefer Packer for image builds (infra/packer/bmt-runtime.pkr.hcl, .github/workflows/bmt-vm-image-build.yml).
# This script remains for manual/one-off builds from local gcp/image without syncing to GCS.
"""Build a pre-baked BMT runtime image (code + deps baked into /opt/bmt).

Lives in infra/scripts/ as image-build tooling; uses local gcp/image as source (code is not in GCS).
Required env: GCP_PROJECT, GCP_ZONE, BMT_LIVE_VM, GCS_BUCKET.
Optional: BMT_IMAGE_FAMILY, BMT_IMAGE_NAME, BMT_BASE_IMAGE_*, BMT_IMAGE_BUILDER_*, BMT_KEEP_IMAGE_BUILDER.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from whenever import Instant

from gcp.image.config.constants import (
    DEFAULT_BASE_IMAGE_FAMILY,
    DEFAULT_BASE_IMAGE_PROJECT,
    DEFAULT_IMAGE_FAMILY,
)
from gcp.image.path_utils import IMAGE_SCRIPTS_SUBDIR

# Resolve gcp/image from repo root (script lives at infra/scripts/build_bmt_image.py).
_script_dir = Path(__file__).resolve().parent
_repo_root = _script_dir.parent.parent
_root = _repo_root / "gcp" / "image"


def _retry(max_attempts: int, delay_sec: int, fn, *args, **kwargs):
    for attempt in range(1, max_attempts + 1):
        try:
            result = fn(*args, **kwargs)
            if result is not False and (result is True or result == 0):
                return result
        except Exception:
            pass
        if attempt < max_attempts:
            print(f"Attempt {attempt}/{max_attempts} failed; retrying in {delay_sec}s...")
            time.sleep(delay_sec)
            delay_sec *= 2
    return None


def main() -> int:
    project = os.environ.get("GCP_PROJECT", "").strip()
    zone = os.environ.get("GCP_ZONE", "").strip()
    vm_name = os.environ.get("BMT_LIVE_VM", "").strip()
    bucket = os.environ.get("GCS_BUCKET", "").strip()
    image_family = os.environ.get("BMT_IMAGE_FAMILY", DEFAULT_IMAGE_FAMILY)
    base_family = os.environ.get("BMT_BASE_IMAGE_FAMILY", DEFAULT_BASE_IMAGE_FAMILY)
    base_project = os.environ.get("BMT_BASE_IMAGE_PROJECT", DEFAULT_BASE_IMAGE_PROJECT)
    expected_family = os.environ.get("BMT_EXPECTED_IMAGE_FAMILY", DEFAULT_IMAGE_FAMILY)
    expected_base = os.environ.get("BMT_EXPECTED_BASE_IMAGE_FAMILY", DEFAULT_BASE_IMAGE_FAMILY)
    builder_machine = os.environ.get("BMT_IMAGE_BUILDER_MACHINE_TYPE", "e2-standard-4")
    keep_builder = os.environ.get("BMT_KEEP_IMAGE_BUILDER", "0").strip() == "1"

    if not all([project, zone, vm_name, bucket]):
        print("::error::Set GCP_PROJECT, GCP_ZONE, BMT_LIVE_VM, and GCS_BUCKET. See script header for required env.", file=sys.stderr)
        return 1
    if image_family != expected_family:
        print(f"::error::Image family policy violation: got '{image_family}', expected '{expected_family}'.", file=sys.stderr)
        return 1
    if base_family != expected_base:
        print(f"::error::Base image family policy violation: got '{base_family}', expected '{expected_base}'.", file=sys.stderr)
        return 1

    for cmd in ["gcloud", "jq", "python3"]:
        r = subprocess.run(["which", cmd], capture_output=True, check=False)
        if r.returncode != 0:
            print(f"::error::Missing required command: {cmd}. Install it and re-run.", file=sys.stderr)
            return 1

    ts = Instant.now().format_iso(unit="second", basic=True)
    ts = f"{ts[:8]}-{ts[8:]}"  # YYYYMMDD-HHMMSS
    image_name = os.environ.get("BMT_IMAGE_NAME", "").strip() or f"{image_family}-{ts}"
    builder_name = os.environ.get("BMT_IMAGE_BUILDER_VM_NAME", "").strip() or f"{vm_name}-image-builder-{ts}"

    builder_created = False
    builder_deleted = False

    def cleanup():
        nonlocal builder_deleted
        if not keep_builder and builder_created and not builder_deleted:
            print(f"Cleaning up builder VM {builder_name}...")
            subprocess.run(
                ["gcloud", "compute", "instances", "delete", builder_name, "--project", project, "--zone", zone, "--quiet"],
                capture_output=True,
                check=False,
            )
            builder_deleted = True

    def wait_for_ssh(instance: str, retries: int = 30, delay: int = 5) -> bool:
        for attempt in range(1, retries + 1):
            r = subprocess.run(
                ["gcloud", "compute", "ssh", instance, "--project", project, "--zone", zone, "--quiet", "--command", "echo ready"],
                capture_output=True,
                check=False,
            )
            if r.returncode == 0:
                print(f"SSH ready on {instance} (attempt {attempt}/{retries}).")
                return True
            print(f"Waiting for SSH on {instance} ({attempt}/{retries})...")
            time.sleep(delay)
        print(f"::error::SSH did not become ready on {instance} within timeout.", file=sys.stderr)
        return False

    try:
        print(f"Reading source VM spec from {vm_name}...")
        r = subprocess.run(
            ["gcloud", "compute", "instances", "describe", vm_name, "--project", project, "--zone", zone, "--format=json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0:
            print(r.stderr or r.stdout or "describe failed", file=sys.stderr)
            return 1
        base_data = json.loads(r.stdout)
        base_sa = (base_data.get("serviceAccounts") or [{}])[0].get("email", "")
        base_scopes = ",".join((base_data.get("serviceAccounts") or [{}])[0].get("scopes", []))
        base_network = (base_data.get("networkInterfaces") or [{}])[0].get("network", "").split("/")[-1]
        base_subnetwork = (base_data.get("networkInterfaces") or [{}])[0].get("subnetwork", "").split("/")[-1]
        base_tags = ",".join((base_data.get("tags") or {}).get("items", []))

        create_cmd = [
            "gcloud", "compute", "instances", "create", builder_name,
            "--project", project, "--zone", zone,
            "--machine-type", builder_machine,
            "--image-family", base_family,
            "--image-project", base_project,
        ]
        if base_sa:
            create_cmd.extend(["--service-account", base_sa])
        if base_scopes:
            create_cmd.extend(["--scopes", base_scopes])
        if base_network:
            create_cmd.extend(["--network", base_network])
        if base_subnetwork:
            create_cmd.extend(["--subnet", base_subnetwork])
        if base_tags:
            create_cmd.extend(["--tags", base_tags])

        print(f"Creating builder VM {builder_name}...")
        subprocess.run(create_cmd, check=True)
        builder_created = True

        if not wait_for_ssh(builder_name):
            return 1

        with tempfile.TemporaryDirectory(prefix="bmt-image-build-") as tmp_dir:
            code_dir = Path(tmp_dir) / "code"
            code_dir.mkdir(parents=True, exist_ok=True)

            # Code is not in GCS; copy from repo gcp/image
            print("Copying gcp/image to build dir (code is not in GCS)...")
            for item in _root.iterdir():
                if item.name.startswith(".") or item.name == "__pycache__":
                    continue
                dest = code_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
                else:
                    shutil.copy2(item, dest)

            install_deps_path = code_dir / IMAGE_SCRIPTS_SUBDIR / "install_deps.py"
            vm_deps_path = code_dir / IMAGE_SCRIPTS_SUBDIR / "vm_deps.txt"
            if not install_deps_path.is_file():
                print("::error::gcp/image is missing scripts/install_deps.py.", file=sys.stderr)
                return 1
            if not vm_deps_path.is_file():
                print("::error::gcp/image is missing scripts/vm_deps.txt.", file=sys.stderr)
                return 1

            print("Uploading code snapshot to builder VM...")
            subprocess.run(
                ["gcloud", "compute", "scp", "--recurse", str(code_dir), f"{builder_name}:/tmp/bmt-code", "--project", project, "--zone", zone, "--quiet"],
                check=True,
            )

        bake_ts = Instant.now().format_iso(unit="second")
        builder_install_script = f"""
set -euo pipefail
sudo rm -rf /opt/bmt
sudo mkdir -p /opt/bmt
sudo cp -a /tmp/bmt-code/. /opt/bmt/
GLIBC_VERSION_RAW=$(ldd --version 2>/dev/null | head -n1 || true)
printf 'GLIBC_VERSION=%s\\n' "$GLIBC_VERSION_RAW" | sudo tee /tmp/bmt-image-build-meta.env >/dev/null
echo 'Installing Google Cloud Ops Agent for Cloud Logging...'
curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
sudo bash add-google-cloud-ops-agent-repo.sh --also-install
rm -f add-google-cloud-ops-agent-repo.sh
echo 'Installing Python 3.12 via deadsnakes PPA...'
for attempt in 1 2 3; do
  sudo add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null && break
  [ $attempt -lt 3 ] && sleep $((attempt * 5)) || exit 1
done
for attempt in 1 2 3; do
  sudo apt-get update -q && sudo apt-get install -y -q python3.12 python3.12-venv python3.12-dev && break
  [ $attempt -lt 3 ] && sleep $((attempt * 10)) || exit 1
done
sudo python3 /opt/bmt/scripts/install_deps.py /opt/bmt
sudo python3 - <<'PY'
import hashlib
import json
from pathlib import Path

repo = Path("/opt/bmt")
build_meta = {{}}
meta_path = Path("/tmp/bmt-image-build-meta.env")
if meta_path.exists():
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        build_meta[key.strip()] = value.strip()

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""

manifest = {{
    "bake_timestamp_utc": "{bake_ts}",
    "image_family": "{image_family}",
    "base_image_family": "{base_family}",
    "base_image_project": "{base_project}",
    "image_source": {{ "bucket": "{bucket}", "code_prefix": "" }},
    "deps_fingerprint": digest(repo / "pyproject.toml"),
    "pyproject_sha256": digest(repo / "pyproject.toml"),
    "glibc_version": build_meta.get("GLIBC_VERSION", ""),
}}
(repo / ".image_manifest.json").write_text(json.dumps(manifest, indent=2) + "\\n", encoding="utf-8")
PY
if command -v cloud-init >/dev/null 2>&1; then
  sudo cloud-init clean --logs --machine-id || sudo cloud-init clean --logs
fi
"""

        def run_builder_install():
            r = subprocess.run(
                ["gcloud", "compute", "ssh", builder_name, "--project", project, "--zone", zone, "--quiet", "--command", builder_install_script],
                capture_output=True,
                text=True,
                check=False,
            )
            return r.returncode == 0

        print("Installing VM dependencies on builder...")
        if _retry(2, 15, run_builder_install) is not True:
            print("::error::Builder install failed", file=sys.stderr)
            return 1

        print("Stopping builder VM...")
        subprocess.run(
            ["gcloud", "compute", "instances", "stop", builder_name, "--project", project, "--zone", zone, "--quiet"],
            check=True,
        )

        family_label = re.sub(r"[^a-z0-9-]", "", image_family.lower().replace("_", "-"))
        version_label = re.sub(r"[^a-z0-9-]", "", image_name.lower().replace("_", "-"))
        ts_label_raw = Instant.now().format_iso(unit="second", basic=True)
        ts_label = f"{ts_label_raw[:8]}-{ts_label_raw[8:]}"  # YYYYMMDD-HHMMSS
        labels = f"bmt-image-family={family_label},bmt-image-version={version_label},bmt-bake-timestamp={ts_label}"

        print(f"Creating image {image_name} (family={image_family})...")
        subprocess.run(
            [
                "gcloud", "compute", "images", "create", image_name,
                "--project", project,
                "--source-disk", builder_name,
                "--source-disk-zone", zone,
                "--family", image_family,
                "--labels", labels,
            ],
            check=True,
        )

        if not keep_builder:
            print(f"Deleting builder VM {builder_name}...")
            subprocess.run(
                ["gcloud", "compute", "instances", "delete", builder_name, "--project", project, "--zone", zone, "--quiet"],
                check=True,
            )
            builder_deleted = True
        else:
            print("Keeping builder VM per BMT_KEEP_IMAGE_BUILDER=1")

        print("Image build complete:")
        print(f"  image:   {image_name}")
        print(f"  family:  {image_family}")
        print(f"  labels:  {labels}")
        return 0
    except subprocess.CalledProcessError as e:
        print(str(e), file=sys.stderr)
        return 1
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
