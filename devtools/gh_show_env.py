#!/usr/bin/env python3
"""Show env vars used by CI, VM, and devtools."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import click
from click_exit import run_click_command

_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))

from shared_env_contract import default_contract_path, list_context_vars, load_env_contract


@dataclass(frozen=True)
class SecretHint:
    name: str
    present_label: str
    absent_label: str = "(unset)"


APP_TRIGGER_SECRET_HINTS: tuple[SecretHint, ...] = (
    SecretHint("APP_TEST_ID", "*** (repo secret)"),
    SecretHint("APP_TEST_PRIVATE_KEY", "*** (repo secret)"),
)


def cmd_exists(name: str) -> bool:
    return subprocess.run(["which", name], capture_output=True, check=False).returncode == 0


def gh_var(name: str) -> str | None:
    if not cmd_exists("gh"):
        return None
    result = subprocess.run(["gh", "variable", "get", name], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def gh_secret_names() -> set[str] | None:
    if not cmd_exists("gh"):
        return None
    result = subprocess.run(["gh", "secret", "list", "--json", "name"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    try:
        secrets = json.loads(result.stdout)
        return {str(s.get("name", "")).strip() for s in secrets if str(s.get("name", "")).strip()}
    except json.JSONDecodeError:
        return None


def gcloud_config(name: str) -> str | None:
    if not cmd_exists("gcloud"):
        return None
    result = subprocess.run(["gcloud", "config", "get-value", name], capture_output=True, text=True, check=False)
    val = result.stdout.strip()
    return val if val and not val.startswith("(unset)") else None


def print_env_var(name: str, val: str | None, default: str | None = None) -> None:
    if val:
        click.echo(f"  {name}={val}")
    elif default is not None:
        if default == "":
            click.echo(f'  {name}="" (default)')
        else:
            click.echo(f"  {name}={default} (default)")
    else:
        click.echo(f"  {name}=(unset)")


def _contract_defaults(contract: dict[str, object]) -> dict[str, str]:
    defaults_raw = contract.get("defaults", {})
    if not isinstance(defaults_raw, dict):
        return {}
    return {str(k): str(v) for k, v in defaults_raw.items()}


def print_repo_secret_hints(secret_hints: tuple[SecretHint, ...], secret_names: set[str]) -> None:
    for secret_hint in secret_hints:
        if secret_hint.name in secret_names:
            click.echo(f"    {secret_hint.name}={secret_hint.present_label}")
        else:
            click.echo(f"    {secret_hint.name}={secret_hint.absent_label}")


def print_github_section(contract: dict[str, object]) -> None:
    header = (
        "GitHub (gh) — used by: build-and-test.yml, start_vm, run_trigger, job_matrix, wait; "
        "VM bootstrap scripts. Unset = CI uses default below."
    )
    click.echo(header)
    click.echo(f"  contract: {default_contract_path()}")

    if not cmd_exists("gh"):
        click.echo("  (gh not available; run 'gh auth login' in repo to list GitHub vars)")
        return

    required_vars = list_context_vars(contract, "github_repo_vars", "required")
    if not required_vars:
        required_vars = ["GCS_BUCKET", "GCP_WIF_PROVIDER", "GCP_SA_EMAIL", "GCP_PROJECT", "GCP_ZONE", "BMT_VM_NAME"]
    for name in required_vars:
        print_env_var(name, gh_var(name))

    defaults = _contract_defaults(contract)
    optional_vars = list_context_vars(contract, "github_repo_vars", "optional")
    if not optional_vars:
        optional_vars = [
            "BMT_BUCKET_PREFIX",
            "BMT_PROJECTS",
            "BMT_STATUS_CONTEXT",
            "BMT_HANDSHAKE_TIMEOUT_SEC",
        ]
    for name in optional_vars:
        print_env_var(name, gh_var(name), default=defaults.get(name))

    click.echo("  App-trigger secrets (CI trigger-bmt):")
    secret_names = gh_secret_names() or set()
    print_repo_secret_hints(APP_TRIGGER_SECRET_HINTS, secret_names)


def print_gcloud_section() -> None:
    click.echo(
        "\ngcloud — used by: audit_vm_and_bucket, ssh_install, setup_vm_startup; tools require explicit canonical vars."
    )
    if not cmd_exists("gcloud"):
        click.echo("  (gcloud not available)")
        return

    click.echo(f"  project={gcloud_config('project') or '(unset)'}")
    click.echo(f"  account={gcloud_config('account') or '(unset)'}")
    click.echo(f"  compute/zone={gcloud_config('compute/zone') or '(unset)'}")


def get_vm_project() -> str | None:
    return gh_var("GCP_PROJECT")


def print_vm_section() -> None:
    click.echo("\nVM env — used by: vm_watcher.py (App auth, statuses/checks). VM must be running to read.")

    if not cmd_exists("gh") or not cmd_exists("gcloud"):
        click.echo("  (need gh and gcloud to read VM env)")
        return

    vm_project = get_vm_project()
    vm_zone = gh_var("GCP_ZONE")
    vm_name = gh_var("BMT_VM_NAME")

    if not vm_project or not vm_zone or not vm_name:
        click.echo("  (need GCP_PROJECT, GCP_ZONE, BMT_VM_NAME from gh to connect)")
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
        click.echo(f"  (VM {vm_name} not RUNNING; start VM to see VM env)")
        return

    ssh_result = subprocess.run(
        [
            "gcloud",
            "compute",
            "ssh",
            vm_name,
            f"--zone={vm_zone}",
            f"--project={vm_project}",
            (
                "--command=for name in "
                "GITHUB_APP_TEST_ID GITHUB_APP_TEST_INSTALLATION_ID GITHUB_APP_TEST_PRIVATE_KEY "
                "GITHUB_APP_PROD_ID GITHUB_APP_PROD_INSTALLATION_ID GITHUB_APP_PROD_PRIVATE_KEY; do "
                'if [ -n "${!name:-}" ]; then echo "$name=set"; else echo "$name=unset"; fi; '
                "done"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if ssh_result.returncode != 0:
        click.echo("  (VM unreachable or ssh failed)")
        return

    states: dict[str, str] = {}
    for raw_line in ssh_result.stdout.splitlines():
        line = raw_line.strip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        states[name.strip()] = value.strip()

    def app_bundle_state(prefix: str) -> str:
        names = [f"{prefix}_ID", f"{prefix}_INSTALLATION_ID", f"{prefix}_PRIVATE_KEY"]
        values = [states.get(name, "unset") for name in names]
        if all(value == "set" for value in values):
            return "ready"
        if all(value == "unset" for value in values):
            return "unset"
        return "partial"

    click.echo(f"  GITHUB_APP_TEST_*={app_bundle_state('GITHUB_APP_TEST')}")
    click.echo(f"  GITHUB_APP_PROD_*={app_bundle_state('GITHUB_APP_PROD')}")
    click.echo("  hint: each enabled repository needs *_ID + *_INSTALLATION_ID + *_PRIVATE_KEY")


def print_local_section() -> None:
    click.echo(
        "\nLocal env — used by: sync_remote, upload_*, validate_bucket_contract, "
        "run-manager-gcs (canonical: GCS_BUCKET)."
    )
    gcs_bucket = os.environ.get("GCS_BUCKET")
    prefix = os.environ.get("BMT_BUCKET_PREFIX")

    print_env_var("GCS_BUCKET", gcs_bucket or None)
    print_env_var("BMT_BUCKET_PREFIX", prefix or None)

    if gcs_bucket:
        click.echo(f"  effective bucket (devtools use this): {gcs_bucket}")
        return

    click.echo("  effective bucket: (none — set GCS_BUCKET)")


@click.command()
def main() -> int:
    try:
        contract = load_env_contract()
    except (OSError, ValueError, json.JSONDecodeError):
        contract = {}
    print_github_section(contract)
    print_gcloud_section()
    print_vm_section()
    print_local_section()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))
