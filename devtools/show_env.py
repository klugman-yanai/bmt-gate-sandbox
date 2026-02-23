#!/usr/bin/env python3
"""Show env vars used by CI, VM, and devtools."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))


def run_cmd(args: list[str], check: bool = False) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, args)
    return result.stdout.strip()


def cmd_exists(name: str) -> bool:
    return subprocess.run(["which", name], capture_output=True, check=False).returncode == 0


def gh_var(name: str) -> str | None:
    if not cmd_exists("gh"):
        return None
    result = subprocess.run(["gh", "variable", "get", name], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def gh_secret_exists(name: str) -> bool:
    if not cmd_exists("gh"):
        return False
    result = subprocess.run(["gh", "secret", "list", "--json", "name"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return False

    try:
        secrets = json.loads(result.stdout)
        return any(s.get("name") == name for s in secrets)
    except json.JSONDecodeError:
        return False


def gh_var_or_default(name: str, default: str | None = None) -> tuple[str, bool]:
    val = gh_var(name)
    if val:
        return val, False
    return default or "", True


def gcloud_config(name: str) -> str | None:
    if not cmd_exists("gcloud"):
        return None
    result = subprocess.run(["gcloud", "config", "get-value", name], capture_output=True, text=True, check=False)
    val = result.stdout.strip()
    return val if val and not val.startswith("(unset)") else None


def project_from_sa(sa_email: str) -> str | None:
    match = re.search(r"@([^.]+)\.iam\.gserviceaccount\.com", sa_email)
    return match.group(1) if match else None


def print_env_var(name: str, val: str | None, default: str | None = None) -> None:
    if val:
        print(f"  {name}={val}")
    elif default is not None:
        if default == "":
            print(f'  {name}="" (default)')
        else:
            print(f"  {name}={default} (default)")
    else:
        print(f"  {name}=(unset)")


def print_github_section() -> None:
    print(
        "GitHub (gh) — used by: ci.yml, start_vm, run_trigger, job_matrix, wait; VM bootstrap scripts. Unset = CI uses default below."
    )
    if not cmd_exists("gh"):
        print("  (gh not available; run 'gh auth login' in repo to list GitHub vars)")
        return

    for name in ["GCS_BUCKET", "GCP_WIF_PROVIDER", "GCP_SA_EMAIL", "GCP_ZONE", "BMT_VM_NAME"]:
        print_env_var(name, gh_var(name))

    sa_email = gh_var("GCP_SA_EMAIL")
    proj_val = gh_var("GCP_PROJECT")
    if proj_val:
        print(f"  GCP_PROJECT={proj_val}")
    elif sa_email:
        proj = project_from_sa(sa_email)
        if proj:
            print(f"  GCP_PROJECT={proj} (default, from SA)")
        else:
            print("  GCP_PROJECT=(unset)")
    else:
        print("  GCP_PROJECT=(unset)")

    print_env_var("BMT_BUCKET_PREFIX", gh_var("BMT_BUCKET_PREFIX"), default="")
    print_env_var("BMT_PROJECTS", gh_var("BMT_PROJECTS"), default="")
    print_env_var("BMT_STATUS_CONTEXT", None, default="BMT Gate")
    print_env_var(
        "BMT_DESCRIPTION_PENDING",
        None,
        default="BMT running on VM; status will update when complete.",
    )

    if gh_secret_exists("GITHUB_STATUS_TOKEN") or gh_var("GITHUB_STATUS_TOKEN"):
        print("  GITHUB_STATUS_TOKEN=*** (repo)")
    else:
        print("  GITHUB_STATUS_TOKEN=(unset in repo)")


def print_gcloud_section() -> None:
    print(
        "\ngcloud — used by: audit_vm_and_bucket, ssh_install, setup_vm_startup; start_vm uses gh vars, falls back to gcloud project."
    )
    if not cmd_exists("gcloud"):
        print("  (gcloud not available)")
        return

    print(f"  project={gcloud_config('project') or '(unset)'}")
    print(f"  account={gcloud_config('account') or '(unset)'}")
    print(f"  compute/zone={gcloud_config('compute/zone') or '(unset)'}")


def print_vm_section() -> None:
    print("\nVM env — used by: vm_watcher.py only (posts commit status). VM must be running to read.")
    if not cmd_exists("gh") or not cmd_exists("gcloud"):
        print("  (need gh and gcloud to read VM env)")
        return

    sa_email = gh_var("GCP_SA_EMAIL")
    vm_project = gh_var("GCP_PROJECT")
    if not vm_project and sa_email:
        vm_project = project_from_sa(sa_email)
    if not vm_project:
        vm_project = gcloud_config("project")

    vm_zone = gh_var("GCP_ZONE")
    vm_name = gh_var("BMT_VM_NAME")

    if not vm_project or not vm_zone or not vm_name:
        print("  (need GCP_PROJECT/GCP_SA_EMAIL, GCP_ZONE, BMT_VM_NAME from gh to connect)")
        return

    result = subprocess.run(
        [
            "gcloud",
            "compute",
            "instances",
            "describe",
            vm_name,
            f"--zone={vm_zone}",
            f"--project={vm_project}",
            "--format=value(status)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    vm_status = result.stdout.strip() if result.returncode == 0 else ""

    if vm_status != "RUNNING":
        print(f"  (VM {vm_name} not RUNNING; start VM to see VM env)")
        return

    ssh_result = subprocess.run(
        [
            "gcloud",
            "compute",
            "ssh",
            vm_name,
            f"--zone={vm_zone}",
            f"--project={vm_project}",
            '--command=[ -n "${GITHUB_STATUS_TOKEN:-}" ] && echo set || echo unset',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    token_status = ssh_result.stdout.strip() if ssh_result.returncode == 0 else ""

    if token_status == "set":
        print("  GITHUB_STATUS_TOKEN=*** (set on VM)")
    elif token_status == "unset":
        print("  GITHUB_STATUS_TOKEN=(unset on VM)")
    else:
        print("  (VM unreachable or ssh failed)")


def print_local_section() -> None:
    print(
        "\nLocal env — used by: sync_remote, upload_*, validate_bucket_contract, run-manager-gcs (BUCKET or GCS_BUCKET)."
    )
    bucket = os.environ.get("BUCKET")
    gcs_bucket = os.environ.get("GCS_BUCKET")
    prefix = os.environ.get("BMT_BUCKET_PREFIX")

    print_env_var("BUCKET", bucket or None)
    print_env_var("GCS_BUCKET", gcs_bucket or None)
    print_env_var("BMT_BUCKET_PREFIX", prefix or None)

    eff_bucket = bucket or gcs_bucket
    if eff_bucket:
        print(f"  effective bucket (devtools use this): {eff_bucket}")
    elif cmd_exists("gh"):
        gh_bucket = gh_var("GCS_BUCKET")
        if gh_bucket:
            print(
                f"  effective bucket: (none in shell); GitHub GCS_BUCKET={gh_bucket} — export GCS_BUCKET to use for devtools"
            )
        else:
            print("  effective bucket: (none)")
    else:
        print("  effective bucket: (none — set BUCKET or GCS_BUCKET)")


def main() -> int:
    print_github_section()
    print_gcloud_section()
    print_vm_section()
    print_local_section()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
