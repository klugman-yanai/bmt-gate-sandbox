#!/usr/bin/env python3
"""Export Terraform outputs + contract defaults to GitHub repo variables.

Hybrid: infra-derived vars from Terraform (terraform output -raw <name>);
behavioral vars from repo_vars_contract defaults. Run from repo root.
Secrets (GCP_WIF_PROVIDER, BMT_DISPATCH_APP_ID, BMT_DISPATCH_APP_PRIVATE_KEY)
are not set here; set them manually. See infra/README.md.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tools.repo.vars_contract import REPO_VARS_CONTRACT, TERRAFORM_OUTPUT_TO_VAR
from tools.shared.bucket_env import truthy


def _repo_root() -> Path:
    # __file__ is tools/terraform/terraform_repo_vars.py -> repo root is parent.parent.parent
    return Path(__file__).resolve().parent.parent.parent


def _terraform_dir() -> Path:
    return _repo_root() / "infra" / "terraform"


def _terraform_output_raw(name: str) -> str:
    tf_dir = _terraform_dir()
    if not tf_dir.is_dir():
        raise FileNotFoundError(f"Terraform dir not found: {tf_dir}")
    proc = subprocess.run(
        ["terraform", "output", "-raw", name],
        cwd=tf_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"terraform output -raw {name} failed: {(proc.stderr or proc.stdout or '').strip()}"
        )
    return (proc.stdout or "").strip()


def get_expected_repo_vars_from_terraform() -> dict[str, str]:
    """Return GitHub var name -> value: Terraform for infra vars, contract defaults for the rest."""
    defaults = REPO_VARS_CONTRACT.default_dict()
    var_to_tf: dict[str, str] = {v: k for k, v in TERRAFORM_OUTPUT_TO_VAR.items()}
    result: dict[str, str] = {}
    for name in REPO_VARS_CONTRACT.all_var_names():
        if name in var_to_tf:
            tf_name = var_to_tf[name]
            result[name] = _terraform_output_raw(tf_name)
        else:
            result[name] = defaults.get(name, "")
    return result


class TerraformRepoVars:
    """Export Terraform outputs + contract defaults to GitHub repo variables."""

    def run(
        self,
        *,
        apply: bool = False,
        dry_run: bool = False,
    ) -> int:
        try:
            vars_to_set = get_expected_repo_vars_from_terraform()
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            print(f"::error::{e}", file=sys.stderr)
            return 1
        if not vars_to_set:
            print("No repo vars to export.", file=sys.stderr)
            return 1
        if dry_run:
            for name in sorted(vars_to_set.keys()):
                print(f"Would set {name}=<redacted>")
            return 0
        if not apply:
            for name, value in sorted(vars_to_set.items()):
                print(f"{name}={value}")
            return 0
        for name, value in sorted(vars_to_set.items()):
            proc = subprocess.run(
                ["gh", "variable", "set", name, "--body", value],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                print(f"::error::gh variable set {name} failed: {proc.stderr or proc.stdout}", file=sys.stderr)
                return 1
            print(f"Set {name}")
        return 0


if __name__ == "__main__":
    apply = truthy(os.environ.get("BMT_APPLY"))
    dry_run = truthy(os.environ.get("BMT_DRY_RUN"))
    raise SystemExit(TerraformRepoVars().run(apply=apply, dry_run=dry_run))
