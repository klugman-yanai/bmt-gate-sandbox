#!/usr/bin/env python3
"""Pulumi login + up from bmt.tfvars.json. Exports vars to GitHub only when changes were applied.

Required in config: gcp_project, gcp_zone, gcs_bucket, service_account.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from tools.repo.paths import pulumi_dir
from tools.shared.rich_minimal import step as _step_impl, step_console, success_panel

CONFIG_FILENAME = "bmt.tfvars.json"
STACK_NAME = "prod"
BACKEND_PREFIX = "pulumi/bmt-vm"


def _verbose() -> bool:
    return "--verbose" in sys.argv or "-v" in sys.argv


def _load_config() -> dict:
    config_path = pulumi_dir() / CONFIG_FILENAME
    if not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with config_path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{CONFIG_FILENAME} must be a JSON object")
    for key in ("gcp_project", "gcp_zone", "gcs_bucket", "service_account", "gcp_wif_provider"):
        if key not in data or data[key] is None or str(data[key]).strip() == "":
            raise ValueError(f"{CONFIG_FILENAME} must set non-empty '{key}'")
    return data


def _run(
    cmd: list[str], *, capture: bool = False, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    merged_env = {**os.environ, **(env or {})}
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, check=False, env=merged_env)
    return subprocess.run(cmd, text=True, check=False, env=merged_env)


def _run_repo_vars(verbose: bool) -> int:
    cmd = [sys.executable, "-m", "tools.pulumi.pulumi_repo_vars", "--apply"]
    if verbose:
        cmd.append("--verbose")
    return subprocess.run(cmd, check=False).returncode


def _had_changes(output: str) -> bool:
    """True if Pulumi reported changes (not 'no changes')."""
    return "0 to create, 0 to update, 0 to delete" not in output.lower()


def main() -> int:
    if not pulumi_dir().is_dir():
        print(f"::error::Pulumi dir not found: {pulumi_dir()}", file=sys.stderr)
        return 1

    try:
        config = _load_config()
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1

    bucket = str(config["gcs_bucket"]).strip()
    pulumi_dir_str = str(pulumi_dir())
    verbose = _verbose()
    console = step_console(verbose)
    if console is not None:
        console.print("[bold]Pulumi[/]")

    # Login to GCS backend
    backend_url = f"gs://{bucket}/{BACKEND_PREFIX}"
    proc = _run(["pulumi", "login", backend_url, "--cwd", pulumi_dir_str], capture=not verbose)
    if not verbose:
        _step_impl(console, "Login", proc.returncode == 0)
    if proc.returncode != 0:
        if not verbose:
            print(proc.stderr or proc.stdout or "pulumi login failed", file=sys.stderr)
        return proc.returncode

    # Select or create stack
    proc = _run(["pulumi", "stack", "select", STACK_NAME, "--create", "--cwd", pulumi_dir_str], capture=not verbose)
    if not verbose:
        _step_impl(console, "Stack select", proc.returncode == 0)
    if proc.returncode != 0:
        if not verbose:
            print(proc.stderr or proc.stdout or "pulumi stack select failed", file=sys.stderr)
        return proc.returncode

    # Set GCP project config
    proc = _run(
        ["pulumi", "config", "set", "gcp:project", config["gcp_project"], "--cwd", pulumi_dir_str], capture=not verbose
    )
    if not verbose:
        _step_impl(console, "Config set", proc.returncode == 0)
    if proc.returncode != 0:
        if not verbose:
            print(proc.stderr or proc.stdout or "pulumi config set failed", file=sys.stderr)
        return proc.returncode

    # Install Python deps
    proc = _run(["pulumi", "install", "--cwd", pulumi_dir_str], capture=not verbose)
    if not verbose:
        _step_impl(console, "Install", proc.returncode == 0)
    if proc.returncode != 0:
        if not verbose:
            print(proc.stderr or proc.stdout or "pulumi install failed", file=sys.stderr)
        return proc.returncode

    # Preview
    if verbose:
        proc = _run(["pulumi", "preview", "--cwd", pulumi_dir_str])
        if proc.returncode != 0:
            return proc.returncode

    # Up
    up_cmd = ["pulumi", "up", "--yes", "--cwd", pulumi_dir_str]
    proc = _run(up_cmd, capture=True)
    up_out = (proc.stdout or "") + (proc.stderr or "")
    if not verbose:
        _step_impl(console, "Up", proc.returncode == 0)
    if proc.returncode != 0:
        print(up_out, file=sys.stderr)
        return proc.returncode
    if verbose:
        print(up_out)

    # Export repo vars if changes were applied
    vars_rc = 0
    if _had_changes(up_out):
        vars_rc = _run_repo_vars(verbose)
        if not verbose:
            _step_impl(console, "Repo vars", vars_rc == 0)
        if vars_rc != 0:
            return 1
    elif not verbose:
        if console is not None:
            console.print("  [dim]Repo vars…[/] [dim](no changes, skipped)[/]")
        else:
            print("  Repo vars… (no changes, skipped)")

    if not verbose:
        success_panel(console, "Apply", "Stack up to date; repo vars synced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
