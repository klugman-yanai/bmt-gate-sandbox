#!/usr/bin/env python3
"""Preflight checks for `just terraform`: config, gcloud, bucket, image, gh.

Run from repo root. Exits 0 if all checks pass, 1 with a clear message otherwise.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from tools.repo.paths import repo_root, INFRA_TERRAFORM

CONFIG_FILENAME = "bmt.tfvars.json"
EXAMPLE_FILENAME = "bmt.tfvars.example.json"
REQUIRED_KEYS = ("gcp_project", "gcp_zone", "gcs_bucket", "service_account")
IMAGE_FAMILY = "bmt-runtime"


def _terraform_dir() -> Path:
    return repo_root() / INFRA_TERRAFORM


def _load_config() -> dict:
    config_path = _terraform_dir() / CONFIG_FILENAME
    example_path = _terraform_dir() / EXAMPLE_FILENAME
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Config not found: {config_path}. "
            f"Copy {example_path.name} to {CONFIG_FILENAME} and set {', '.join(REQUIRED_KEYS)}."
        )
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{CONFIG_FILENAME} must be a JSON object.")
    for key in REQUIRED_KEYS:
        if key not in data or data[key] is None or str(data[key]).strip() == "":
            raise ValueError(f"{CONFIG_FILENAME} must set non-empty '{key}'.")
    return data


def _check_startup_script(config: dict) -> None:
    path_raw = config.get("startup_wrapper_script_path", "").strip()
    if not path_raw:
        return
    # Path is relative to infra/terraform
    script_path = (_terraform_dir() / path_raw).resolve()
    if not script_path.is_file():
        raise SystemExit(
            f"::error::startup_wrapper_script_path not found: {script_path}\n"
            f"(resolved from infra/terraform/{path_raw})"
        )


def _check_gcloud() -> None:
    if not shutil.which("gcloud"):
        raise SystemExit("::error::gcloud not found. Install Google Cloud SDK and ensure gcloud is on PATH.")
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
            "gcloud", "compute", "images", "describe-from-family",
            IMAGE_FAMILY,
            "--project", project,
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
    if not shutil.which("gh"):
        raise SystemExit(
            "::error::gh not found. Install GitHub CLI for the export-vars step (just terraform)."
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
            "(Required to push Terraform outputs to GitHub repo variables.)"
        )


def main() -> int:
    if not _terraform_dir().is_dir():
        print(f"::error::Terraform dir not found: {_terraform_dir()}", file=sys.stderr)
        return 1
    try:
        config = _load_config()
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1

    project = str(config["gcp_project"]).strip()
    bucket = str(config["gcs_bucket"]).strip()

    _check_startup_script(config)
    _check_gcloud()
    _check_bucket(bucket)
    _check_image(project)
    _check_gh()

    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    print("Preflight OK: config, gcloud, bucket, image, gh." if verbose else "Preflight OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
