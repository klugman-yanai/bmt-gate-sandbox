#!/usr/bin/env python3
"""Validate required GitHub repo variables against VM metadata."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from tools.shared.env_contract import list_repo_vs_vm_metadata_vars, load_env_contract
from tools.shared.gh import cmd_exists


def _run_text(cmd: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _gh_var(name: str) -> str:
    rc, out, _err = _run_text(["gh", "variable", "get", name])
    return out if rc == 0 else ""


def _resolve_required(name: str, cli_value: str | None, cli_flag: str) -> str:
    value = (cli_value or "").strip() or (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Set {name} or pass {cli_flag}.")
    return value


def _normalize(name: str, value: str) -> str:
    return (value or "").strip()


def _read_vm_metadata(project: str, zone: str, vm_name: str, key: str) -> str:
    rc, out, _err = _run_text(
        [
            "gcloud",
            "compute",
            "instances",
            "describe",
            vm_name,
            "--zone",
            zone,
            "--project",
            project,
            "--format",
            f"get(metadata.items.{key})",
        ]
    )
    return out if rc == 0 else ""


def _render(value: str) -> str:
    return value or "<empty>"


class GhValidateVmVars:
    """Validate repo vars vs VM metadata based on contract consistency checks."""

    def run(
        self,
        *,
        vm_name: str | None = None,
        zone: str | None = None,
        project: str | None = None,
        contract: str | None = None,
    ) -> int:
        if not cmd_exists("gh"):
            print("::error::gh CLI not found", file=sys.stderr)
            return 2
        if not cmd_exists("gcloud"):
            print("::error::gcloud CLI not found", file=sys.stderr)
            return 2

        try:
            resolved_vm = _resolve_required("BMT_VM_NAME", vm_name, "--vm-name")
            resolved_zone = _resolve_required("GCP_ZONE", zone, "--zone")
            resolved_project = _resolve_required("GCP_PROJECT", project, "--project")
        except RuntimeError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 2

        print(f"Target VM: {resolved_vm}  zone={resolved_zone}  project={resolved_project}")
        print()
        print("Comparing GitHub repo variables vs VM metadata:")

        try:
            env_contract = load_env_contract(contract)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"::error::Failed to load env contract: {exc}", file=sys.stderr)
            return 2
        keys = list_repo_vs_vm_metadata_vars(env_contract)
        if not keys:
            print("::error::No repo_vs_vm_metadata keys defined in env contract.", file=sys.stderr)
            return 2

        mismatches: list[str] = []
        for key in keys:
            repo_raw = _gh_var(key)
            vm_raw = _read_vm_metadata(resolved_project, resolved_zone, resolved_vm, key)
            repo_norm = _normalize(key, repo_raw)
            vm_norm = _normalize(key, vm_raw)

            status = "OK" if repo_norm == vm_norm else "MISMATCH"
            print(f"- {key}: {status}")
            print(f"  repo: {_render(repo_raw)}")
            print(f"  vm  : {_render(vm_raw)}")
            if repo_norm != vm_norm:
                mismatches.append(key)

        if mismatches:
            print()
            print(f"::error::Mismatch detected for: {', '.join(mismatches)}", file=sys.stderr)
            print(
                "::error::Update repo vars and resync VM metadata (workflow sync-vm-metadata or set_startup_script_url.sh).",
                file=sys.stderr,
            )
            return 1

        print()
        print("::notice::Repo vars and VM metadata match for required vars.")
        return 0


if __name__ == "__main__":
    import os

    vm_name = (os.environ.get("BMT_VM_NAME") or "").strip() or None
    zone = (os.environ.get("GCP_ZONE") or "").strip() or None
    project = (os.environ.get("GCP_PROJECT") or "").strip() or None
    contract = (os.environ.get("BMT_ENV_CONTRACT") or "").strip() or None
    raise SystemExit(
        GhValidateVmVars().run(vm_name=vm_name, zone=zone, project=project, contract=contract)
    )
