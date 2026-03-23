#!/usr/bin/env python3
"""Export Pulumi stack outputs to GitHub repo variables.

All infra-derived vars (including GCP_WIF_PROVIDER from bmt.config.json gcp_wif_provider)
come from Pulumi. Manual vars (e.g. BMT_STATUS_CONTEXT) can still be set via bmt.config.json
"github_vars" or directly in GitHub. Run from repo root.
"""

from __future__ import annotations

import json
import subprocess
import sys

from tools.repo.paths import pulumi_dir
from tools.repo.vars_contract import (
    INFRA_OUTPUT_TO_VAR,
    REPO_VARS_CONTRACT,
)

CONFIG_FILENAME = "bmt.config.json"
ALLOWED_GITHUB_VARS = frozenset(REPO_VARS_CONTRACT.manual_vars)


def _load_github_vars_from_tfvars() -> dict[str, str]:
    """Load optional github_vars from bmt.config.json. Only allowed keys are returned."""
    path = pulumi_dir() / CONFIG_FILENAME
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {}
    block = data.get("github_vars")
    if not isinstance(block, dict):
        return {}
    return {
        k: str(v).strip() for k, v in block.items() if k in ALLOWED_GITHUB_VARS and v is not None and str(v).strip()
    }


def _pulumi_output_raw(name: str) -> str:
    pdir = pulumi_dir()
    if not pdir.is_dir():
        raise FileNotFoundError(f"Pulumi dir not found: {pdir}")
    proc = subprocess.run(
        ["pulumi", "stack", "output", name, "--cwd", str(pdir)],
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"pulumi stack output {name} failed: {err or out or 'no output'}")
    if not out:
        raise RuntimeError(f"Pulumi output '{name}' is empty. Run `just pulumi` first.")
    return out


def get_expected_repo_vars_from_pulumi() -> dict[str, str]:
    """Return GitHub var name -> value from Pulumi outputs and contract defaults.

    All infra vars (including GCP_WIF_PROVIDER from gcp_wif_provider) are required in config
    and pushed from Pulumi. Manual vars from github_vars override when present.
    """
    defaults = REPO_VARS_CONTRACT.default_dict()
    github_vars = _load_github_vars_from_tfvars()
    var_to_infra: dict[str, str] = {v: k for k, v in INFRA_OUTPUT_TO_VAR.items()}
    result: dict[str, str] = {}
    for name in REPO_VARS_CONTRACT.all_var_names():
        if name in var_to_infra:
            result[name] = _pulumi_output_raw(var_to_infra[name])
        else:
            result[name] = defaults.get(name, "")
    result.update(github_vars)
    return result


class PulumiRepoVars:
    """Export Pulumi stack outputs + contract defaults to GitHub repo variables."""

    def run(
        self,
        *,
        apply: bool = False,
        dry_run: bool = False,
    ) -> int:
        try:
            vars_to_set = get_expected_repo_vars_from_pulumi()
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
        verbose = "--verbose" in sys.argv or "-v" in sys.argv
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
            if verbose:
                print(f"Set {name}")
        if not verbose:
            n = len(vars_to_set)
            if sys.stdout.isatty():
                from rich.console import Console

                Console().print(f"  [green]Pushed {n} repo var{'s' if n != 1 else ''}.[/]")
            else:
                print(f"Pushed {n} repo var(s).")
        return 0


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    dry_run = "--dry-run" in sys.argv
    raise SystemExit(PulumiRepoVars().run(apply=apply, dry_run=dry_run))
