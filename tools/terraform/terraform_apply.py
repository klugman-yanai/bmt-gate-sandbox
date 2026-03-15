#!/usr/bin/env python3
"""Terraform init + plan + apply from bmt.tfvars.json. Exports vars to GitHub only when changes were applied.

Required in tfvars: gcp_project, gcp_zone, gcs_bucket, service_account. Optional: bmt_vm_name.
Exits if plan would destroy/replace VM unless BMT_TERRAFORM_ALLOW_DESTROY=1.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

CONFIG_FILENAME = "bmt.tfvars.json"
EXAMPLE_FILENAME = "bmt.tfvars.example.json"
BACKEND_PREFIX = "terraform/bmt-vm"
TFPLAN_NAME = "tfplan"


def _verbose() -> bool:
    """True when --verbose or -v was passed on the CLI."""
    return "--verbose" in sys.argv or "-v" in sys.argv


def _is_409_topics(err: str) -> bool:
    """True if apply failed with 409 (resource already exists) for our Pub/Sub topics."""
    if "409" not in err or "already exists" not in err:
        return False
    return "bmt-triggers" in err


def _run_import_topics() -> int:
    """Import existing Pub/Sub topics into state. Returns 0 on success."""
    from tools.terraform import terraform_import_topics
    return terraform_import_topics.main()


def _run_repo_vars(verbose: bool) -> int:
    """Export Terraform outputs to GitHub repo vars. Returns 0 on success."""
    cmd = [sys.executable, "-m", "tools.terraform.terraform_repo_vars", "--apply"]
    if verbose:
        cmd.append("--verbose")
    return subprocess.run(cmd, check=False).returncode


def _apply_had_changes(apply_out: str) -> bool:
    """True if Terraform apply reported that it made changes (not 'No changes')."""
    return "No changes." not in apply_out


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _terraform_dir() -> Path:
    return _repo_root() / "infra" / "terraform"


def _load_config() -> dict:
    config_path = _terraform_dir() / CONFIG_FILENAME
    example_path = _terraform_dir() / EXAMPLE_FILENAME
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Declarative config not found: {config_path}\n"
            f"Copy {example_path.name} to {CONFIG_FILENAME} and set gcp_project, gcp_zone, gcs_bucket, service_account."
        )
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{CONFIG_FILENAME} must be a JSON object")
    for key in ("gcp_project", "gcp_zone", "gcs_bucket", "service_account"):
        if key not in data or data[key] is None or str(data[key]).strip() == "":
            raise ValueError(f"{CONFIG_FILENAME} must set non-empty '{key}'")
    return data


def main() -> int:
    if not _terraform_dir().is_dir():
        print(f"::error::Terraform dir not found: {_terraform_dir()}", file=sys.stderr)
        return 1

    try:
        config = _load_config()
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1

    bucket = str(config["gcs_bucket"]).strip()
    tf_dir_str = str(_terraform_dir())
    var_file_path = _terraform_dir() / CONFIG_FILENAME

    init_cmd = [
        "terraform",
        "-chdir=" + tf_dir_str,
        "init",
        "-reconfigure",
        "-backend-config=bucket=" + bucket,
        "-backend-config=prefix=" + BACKEND_PREFIX,
    ]
    verbose = _verbose()
    if not verbose:
        proc = subprocess.run(init_cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            print(proc.stderr or proc.stdout or "init failed", file=sys.stderr)
            return proc.returncode
    else:
        proc = subprocess.run(init_cmd, check=False)
        if proc.returncode != 0:
            return proc.returncode

    tfplan_path = _terraform_dir() / TFPLAN_NAME
    used_existing_plan = tfplan_path.is_file()

    if not used_existing_plan:
        plan_cmd = [
            "terraform",
            "-chdir=" + tf_dir_str,
            "plan",
            "-out=" + TFPLAN_NAME,
            "-var-file=" + str(var_file_path),
        ]
        proc = subprocess.run(plan_cmd, capture_output=True, text=True, check=False)
        plan_out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 1:
            print(plan_out, file=sys.stderr)
            return 1
        if verbose:
            print(plan_out)
        vm_ref = "google_compute_instance.bmt_vm"
        if vm_ref in plan_out and (
            "will be destroyed" in plan_out or "must be replaced" in plan_out
        ):
            allow_destroy = os.environ.get("BMT_TERRAFORM_ALLOW_DESTROY", "").strip() == "1"
            if not allow_destroy:
                print(
                    "::error::Plan would destroy or replace the BMT VM. Set BMT_TERRAFORM_ALLOW_DESTROY=1 to allow.",
                    file=sys.stderr,
                )
                return 1

    apply_cmd = [
        "terraform",
        "-chdir=" + tf_dir_str,
        "apply",
        "-input=false",
        TFPLAN_NAME,
    ]
    proc = subprocess.run(apply_cmd, capture_output=True, text=True, check=False)
    apply_err = proc.stderr or ""
    apply_out = (proc.stdout or "") + apply_err
    if proc.returncode != 0:
        if verbose:
            print(apply_out, file=sys.stderr)
        if _is_409_topics(apply_err):
            if not verbose:
                print("Topics already exist in GCP; importing into state and retrying...", file=sys.stderr)
            tfplan_path.unlink(missing_ok=True)
            if _run_import_topics() != 0:
                return 1
            plan_cmd = [
                "terraform",
                "-chdir=" + tf_dir_str,
                "plan",
                "-out=" + TFPLAN_NAME,
                "-var-file=" + str(var_file_path),
            ]
            p = subprocess.run(plan_cmd, capture_output=True, text=True, check=False)
            plan_out = (p.stdout or "") + (p.stderr or "")
            if p.returncode != 0:
                print(plan_out, file=sys.stderr)
                return 1
            if verbose:
                print(plan_out)
            proc = subprocess.run(apply_cmd, capture_output=True, text=True, check=False)
            if verbose:
                print(proc.stdout or "", end="")
                if proc.stderr:
                    print(proc.stderr, file=sys.stderr)
            if proc.returncode == 0:
                tfplan_path.unlink(missing_ok=True)
                retry_out = (proc.stdout or "") + (proc.stderr or "")
                if _apply_had_changes(retry_out) and _run_repo_vars(verbose) != 0:
                    return 1
                if not verbose:
                    print("Apply OK.")
                return 0
            if not verbose:
                print(proc.stderr or proc.stdout or "Apply failed", file=sys.stderr)
            return proc.returncode
        return proc.returncode

    tfplan_path.unlink(missing_ok=True)
    if _apply_had_changes(apply_out) and _run_repo_vars(verbose) != 0:
        return 1
    if not verbose:
        print("Apply OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
