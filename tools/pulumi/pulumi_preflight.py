#!/usr/bin/env python3
"""Preflight checks for `just pulumi`: config, pulumi, gcloud, bucket, image, gh.

Run from repo root. Exits 0 if all checks pass, 1 with a clear message otherwise.
"""

from __future__ import annotations

import json
import subprocess
import sys

from tools.repo.paths import pulumi_dir
from tools.shared.cli_availability import command_available
from tools.shared.contributor_docs import ContributorDocRefs, gcloud_cli_missing_message

CONFIG_FILENAME = "bmt.tfvars.json"
EXAMPLE_FILENAME = "bmt.tfvars.example.json"
REQUIRED_KEYS = ("gcp_project", "gcp_zone", "gcs_bucket", "service_account", "gcp_wif_provider")
IMAGE_FAMILY = "bmt-runtime"


def _load_config() -> dict:
    config_path = pulumi_dir() / CONFIG_FILENAME
    example_path = pulumi_dir() / EXAMPLE_FILENAME
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Config not found: {config_path}. "
            f"Copy {example_path.name} to {CONFIG_FILENAME} and set {', '.join(REQUIRED_KEYS)}."
        )
    with config_path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{CONFIG_FILENAME} must be a JSON object.")
    for key in REQUIRED_KEYS:
        if key not in data or data[key] is None or str(data[key]).strip() == "":
            raise ValueError(f"{CONFIG_FILENAME} must set non-empty '{key}'.")
    return data


def _check_pulumi() -> None:
    if not command_available("pulumi"):
        refs = ContributorDocRefs.discover()
        raise SystemExit(
            "::error::"
            + refs.external_cli_missing_line(
                cli="pulumi",
                hint="Install Pulumi CLI: https://www.pulumi.com/docs/install/",
            )
        )


def _check_gcloud() -> None:
    if not command_available("gcloud"):
        raise SystemExit("::error::" + gcloud_cli_missing_message())
    r = subprocess.run(
        ["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0 or not (r.stdout or "").strip():
        raise SystemExit("::error::gcloud not authenticated. Run: gcloud auth login")


def _check_bucket(bucket: str) -> None:
    r = subprocess.run(
        ["gcloud", "storage", "buckets", "describe", f"gs://{bucket}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise SystemExit(
            f"::error::Bucket gs://{bucket} not found or not accessible.\n"
            "Create it or run: gcloud auth application-default login"
        )


def _check_image(project: str) -> None:
    r = subprocess.run(
        [
            "gcloud",
            "compute",
            "images",
            "describe-from-family",
            IMAGE_FAMILY,
            "--project",
            project,
            "--format=value(name)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0 or not (r.stdout or "").strip():
        raise SystemExit(
            f"::error::Image family '{IMAGE_FAMILY}' not found in project {project}.\n"
            "Build the image first: just build (or run Packer manually)."
        )


def _check_gh() -> None:
    if not command_available("gh"):
        refs = ContributorDocRefs.discover()
        raise SystemExit(
            "::error::"
            + refs.external_cli_missing_line(
                cli="gh",
                hint="Install GitHub CLI for the export-vars step (just pulumi): https://cli.github.com/",
            )
        )
    r = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise SystemExit(
            "::error::gh not authenticated. Run: gh auth login\n"
            "(Required to push Pulumi outputs to GitHub repo variables.)"
        )


def main() -> int:
    if not pulumi_dir().is_dir():
        print(f"::error::Pulumi dir not found: {pulumi_dir()}", file=sys.stderr)
        return 1
    try:
        config = _load_config()
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1

    project = str(config["gcp_project"]).strip()
    bucket = str(config["gcs_bucket"]).strip()

    _check_pulumi()
    _check_gcloud()
    _check_bucket(bucket)
    _check_image(project)
    _check_gh()

    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    from tools.shared.rich_minimal import step_console, success_panel

    if verbose:
        print("Preflight OK: config, pulumi, gcloud, bucket, image, gh.")
    else:
        console = step_console(verbose)
        checks = "config · pulumi · gcloud · bucket · image · gh"
        success_panel(console, "Preflight", checks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
