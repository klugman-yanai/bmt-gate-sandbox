#!/usr/bin/env python3
"""Validate code/runtime bucket contract for manual sync deployments.

Paths such as sk/results/false_rejects and runner URIs are project-specific
(current sk project). CLI and contract allow overrides.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tools.repo.paths import DEFAULT_CONFIG_ROOT
from tools.repo.results_prefix import resolve_results_prefix
from tools.shared.bucket_env import (
    bucket_from_env,
    code_bucket_root_uri,
    runtime_bucket_root_uri,
    truthy,
)

REQUIRED_CODE = [
    "root_orchestrator.py",
    "pyproject.toml",
    "sk/bmt_manager.py",
    "sk/config/bmt_jobs.json",
    "sk/config/input_template.json",
    "bootstrap/startup_entrypoint.sh",
]


def exists(uri: str) -> bool:
    return (
        subprocess.run(
            ["gcloud", "storage", "ls", uri],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def has_snapshot_leaf(runtime_root: str, results_prefix: str, leaf_name: str) -> bool:
    uri = f"{runtime_root}/{results_prefix.rstrip('/')}/snapshots/*/{leaf_name}"
    proc = subprocess.run(
        ["gcloud", "storage", "ls", uri],
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and bool((proc.stdout or "").strip())


class BucketValidateContract:
    """Validate code/runtime bucket contract for manual sync deployments."""

    def run(self, *, bucket: str, require_runner: bool = False) -> int:
        if not bucket:
            print("::error::Set GCS_BUCKET (or pass --bucket)", file=sys.stderr)
            return 1

        # Resolve results_prefix from config (single primary BMT: sk/false_reject_namuh)
        # __file__ is under tools/...; go up to repo root then apply DEFAULT_CONFIG_ROOT
        repo_root = Path(__file__).resolve().parent.parent.parent
        config_root = repo_root / DEFAULT_CONFIG_ROOT
        results_prefix = resolve_results_prefix(config_root, "sk", "false_reject_namuh")

        code_root = code_bucket_root_uri(bucket)
        runtime_root = runtime_bucket_root_uri(bucket)
        missing = False

        print(f"Validating code root: {code_root}")
        for rel in REQUIRED_CODE:
            uri = f"{code_root}/{rel}"
            if exists(uri):
                print(f"FOUND {uri}")
            else:
                print(f"::error::Missing required code object: {uri}", file=sys.stderr)
                missing = True

        print(f"Validating runtime root: {runtime_root}")
        required_runtime = [f"{results_prefix}/current.json"]
        for rel in required_runtime:
            uri = f"{runtime_root}/{rel}"
            if exists(uri):
                print(f"FOUND {uri}")
            else:
                print(f"::error::Missing required runtime object: {uri}", file=sys.stderr)
                missing = True

        if has_snapshot_leaf(runtime_root, results_prefix, "latest.json"):
            print(f"FOUND snapshot latest.json under {runtime_root}/{results_prefix}/snapshots/")
        else:
            print(
                f"::error::Missing canonical snapshot latest.json under {runtime_root}/{results_prefix}/snapshots/",
                file=sys.stderr,
            )
            missing = True

        if has_snapshot_leaf(runtime_root, results_prefix, "ci_verdict.json"):
            print(f"FOUND snapshot ci_verdict.json under {runtime_root}/{results_prefix}/snapshots/")
        else:
            print(
                f"::error::Missing canonical snapshot ci_verdict.json under {runtime_root}/{results_prefix}/snapshots/",
                file=sys.stderr,
            )
            missing = True

        if require_runner:
            runner_uri = f"{runtime_root}/sk/runners/sk_gcc_release/kardome_runner"
            if exists(runner_uri):
                print(f"FOUND {runner_uri}")
            else:
                print(f"::error::Missing required object: {runner_uri}", file=sys.stderr)
                missing = True

        if missing:
            return 1

        print("Bucket contract validation passed")
        return 0


if __name__ == "__main__":
    import os

    bucket = bucket_from_env()
    require_runner = truthy(os.environ.get("BMT_REQUIRE_RUNNER"))
    raise SystemExit(BucketValidateContract().run(bucket=bucket, require_runner=require_runner))
