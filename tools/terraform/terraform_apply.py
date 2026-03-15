#!/usr/bin/env python3
"""Run Terraform init + apply non-interactively using GitHub repo variables as input.

All required variable values come from the repo: GitHub variables (GCP_PROJECT, GCP_ZONE,
GCS_BUCKET, GCP_SA_EMAIL) and in-repo defaults (startup_wrapper_script_path, bmt_vm_name).
No prompts. Run from repo root. Requires gh CLI and terraform on PATH.

Safeguards:
- Runs plan before apply; applies the saved plan so apply matches the plan you saw.
- If the plan would destroy or replace the BMT VM (google_compute_instance.bmt_vm),
  exits with error unless BMT_TERRAFORM_ALLOW_DESTROY=1 is set.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# GitHub variable name -> Terraform -var name
GH_VAR_TO_TF_VAR = [
    ("GCP_PROJECT", "gcp_project"),
    ("GCP_ZONE", "gcp_zone"),
    ("GCS_BUCKET", "gcs_bucket"),
    ("GCP_SA_EMAIL", "service_account"),
]

BACKEND_PREFIX = "terraform/bmt-vm"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _terraform_dir() -> Path:
    return _repo_root() / "infra" / "terraform"


def _gh_var(name: str) -> str:
    proc = subprocess.run(
        ["gh", "variable", "get", name],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh variable get {name} failed (is it set?): {proc.stderr or proc.stdout or ''}"
        )
    return (proc.stdout or "").strip()


def main() -> int:
    if not _terraform_dir().is_dir():
        print(f"::error::Terraform dir not found: {_terraform_dir()}", file=sys.stderr)
        return 1

    try:
        tf_vars = {tf: _gh_var(gh) for gh, tf in GH_VAR_TO_TF_VAR}
    except RuntimeError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1

    bucket = tf_vars["gcs_bucket"]
    tf_dir_str = str(_terraform_dir())
    init_cmd = [
        "terraform",
        "-chdir=" + tf_dir_str,
        "init",
        "-reconfigure",
        "-backend-config=bucket=" + bucket,
        "-backend-config=prefix=" + BACKEND_PREFIX,
    ]
    proc = subprocess.run(init_cmd, check=False)
    if proc.returncode != 0:
        return proc.returncode

    # Plan first (safeguard: we apply the plan file so apply matches what was planned)
    plan_vars = []
    for tf_name, value in tf_vars.items():
        plan_vars.extend(["-var", f"{tf_name}={value}"])
    plan_cmd = [
        "terraform",
        "-chdir=" + tf_dir_str,
        "plan",
        "-out=tfplan",
        *plan_vars,
    ]
    proc = subprocess.run(plan_cmd, capture_output=True, text=True, check=False)
    plan_out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 1:
        print(plan_out, file=sys.stderr)
        return 1
    print(plan_out)
    # Block VM destroy/replace unless explicitly allowed
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
        "tfplan",
    ]
    proc = subprocess.run(apply_cmd, check=False)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
