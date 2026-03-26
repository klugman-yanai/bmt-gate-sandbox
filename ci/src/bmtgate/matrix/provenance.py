"""SLSA-style provenance JSON for runner uploads."""

from __future__ import annotations

import json
import os
from typing import Any

from whenever import Instant

from bmtgate.clients import gcs

_SLSA_STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
_SLSA_PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
_SLSA_BUILD_TYPE = "https://kardome.com/bmt/runner-upload/v1"


def write_runner_provenance(
    bucket: str,
    root: str,
    dest_prefix: str,
    local_files: list[dict[str, Any]],
    source_ref: str,
    project: str,
    preset: str,
) -> None:
    now = Instant.now().format_iso(unit="second")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    git_sha = os.environ.get("GITHUB_SHA", "")
    builder_id = (
        f"https://github.com/{repository}/.github/workflows/build-and-test.yml"
        if repository
        else _SLSA_BUILD_TYPE
    )
    provenance = {
        "_type": _SLSA_STATEMENT_TYPE,
        "subject": [
            {"name": f"{root}/{dest_prefix}/{r['name']}", "digest": {"sha256": str(r["sha256"])}}
            for r in local_files
        ],
        "predicateType": _SLSA_PREDICATE_TYPE,
        "predicate": {
            "buildDefinition": {
                "buildType": _SLSA_BUILD_TYPE,
                "externalParameters": {
                    "source_ref": source_ref,
                    "project": project,
                    "preset": preset,
                },
                "resolvedDependencies": [
                    {"uri": f"https://github.com/{repository}", "digest": {"gitCommit": git_sha}}
                ]
                if git_sha
                else [],
            },
            "runDetails": {
                "builder": {"id": builder_id},
                "metadata": {
                    "invocationId": run_id,
                    "startedOn": now,
                    "finishedOn": now,
                    "github_repository": repository,
                    "github_run_id": run_id,
                    "gcs_bucket": bucket,
                    "dest_prefix": dest_prefix,
                },
            },
        },
    }
    dest = f"{root}/{dest_prefix}/runner.slsa.json"
    try:
        gcs.write_object(dest, json.dumps(provenance, indent=2) + "\n")
    except gcs.GcsError as exc:
        print(f"::warning::Failed to upload runner provenance: {exc}")
        return
    print(f"Uploaded runner provenance (SLSA v1.0) -> {dest}")
