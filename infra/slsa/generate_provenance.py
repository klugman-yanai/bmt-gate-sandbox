#!/usr/bin/env python3
"""Generate a SLSA v1.0 provenance document for a BMT image or runner artifact.

Usage:
    # After Packer image build (workflow passes builder-id and bucket from github.repository / vars.GCS_BUCKET):
    python3 generate_provenance.py image \
        --image-name bmt-runtime-20260311-120000 \
        --image-family bmt-runtime \
        --gcs-bucket <GCS_BUCKET> \
        --builder-id "https://github.com/<owner>/<repo>/.github/workflows/bmt-vm-image-build.yml" \
        --git-sha <sha> \
        --out provenance.json

    # After runner upload:
    python3 generate_provenance.py runner \
        --artifact-uri gs://<bucket>/runtime/runner/runner.tar.gz \
        --artifact-sha256 <hex> \
        --builder-id "https://github.com/<owner>/<repo>/.github/workflows/<workflow>.yml" \
        --git-sha <sha> \
        --out provenance.json

The output is a SLSA v1.0 provenance JSON stored in GCS under:
    gs://<bucket>/provenance/images/<image-name>.slsa.json
    gs://<bucket>/provenance/runners/<run-id>.slsa.json

Verification: at VM startup, vm_watcher reads and checks .image_manifest.json against
the provenance document stored in GCS to confirm the running image matches what CI built.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from whenever import Instant

# ---------------------------------------------------------------------------
# SLSA v1.0 provenance envelope
# ---------------------------------------------------------------------------

SLSA_PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"


def _now_utc() -> str:
    return Instant.now().format_iso(unit="second")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def build_provenance(
    *,
    subject_name: str,
    subject_digest: dict[str, str],
    builder_id: str,
    build_type: str,
    source_uri: str,
    git_sha: str,
    invocation_id: str,
    started_on: str,
    finished_on: str,
    extra_metadata: dict | None = None,
) -> dict:
    """Return a SLSA v1.0 provenance statement as a dict."""
    return {
        "_type": STATEMENT_TYPE,
        "subject": [
            {
                "name": subject_name,
                "digest": subject_digest,
            }
        ],
        "predicateType": SLSA_PREDICATE_TYPE,
        "predicate": {
            "buildDefinition": {
                "buildType": build_type,
                "externalParameters": {
                    "source": source_uri,
                    "ref": git_sha,
                },
                "resolvedDependencies": [
                    {
                        "uri": source_uri,
                        "digest": {"gitCommit": git_sha},
                    }
                ],
            },
            "runDetails": {
                "builder": {"id": builder_id},
                "metadata": {
                    "invocationId": invocation_id,
                    "startedOn": started_on,
                    "finishedOn": finished_on,
                    **(extra_metadata or {}),
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_image(args: argparse.Namespace) -> None:
    """Generate provenance for a Packer-built GCE image."""
    # Read deps_fingerprint from the manifest uploaded by Packer
    manifest_uri = f"gs://{args.gcs_bucket}/provenance/image-manifests/{args.image_name}.json"
    manifest: dict = {}
    try:
        raw = subprocess.check_output(["gcloud", "storage", "cat", manifest_uri], text=True)
        manifest = json.loads(raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"Warning: could not read image manifest from {manifest_uri}: {exc}", file=sys.stderr)

    subject_digest = {
        "sha256": _sha256_str(args.image_name),  # GCE images have no content hash; use name digest
    }
    if manifest.get("deps_fingerprint"):
        subject_digest["deps_fingerprint"] = manifest["deps_fingerprint"]

    provenance = build_provenance(
        subject_name=f"gcr.io/{args.gcp_project}/{args.image_family}/{args.image_name}"
        if args.gcp_project
        else args.image_name,
        subject_digest=subject_digest,
        builder_id=args.builder_id,
        build_type="https://kardome.com/bmt/packer-image-build/v1",
        source_uri=f"gs://{args.gcs_bucket}/code",
        git_sha=args.git_sha,
        invocation_id=args.invocation_id or os.environ.get("GITHUB_RUN_ID", ""),
        started_on=manifest.get("bake_timestamp_utc") or _now_utc(),
        finished_on=_now_utc(),
        extra_metadata={
            "image_name": args.image_name,
            "image_family": args.image_family,
            "gcs_bucket": args.gcs_bucket,
            "manifest_uri": manifest_uri,
        },
    )

    out_path = Path(args.out)
    out_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote image provenance: {out_path}")

    dest_uri = f"gs://{args.gcs_bucket}/provenance/images/{args.image_name}.slsa.json"
    subprocess.check_call(["gcloud", "storage", "cp", str(out_path), dest_uri])
    print(f"Uploaded image provenance: {dest_uri}")


def cmd_runner(args: argparse.Namespace) -> None:
    """Generate provenance for an uploaded runner artifact."""
    artifact_sha256 = args.artifact_sha256
    if not artifact_sha256 and args.artifact_local_path:
        artifact_sha256 = _sha256_file(Path(args.artifact_local_path))

    if not artifact_sha256:
        print("Provide --artifact-sha256 or --artifact-local-path", file=sys.stderr)
        sys.exit(1)

    # Derive bucket from artifact URI  gs://bucket/...
    bucket = args.gcs_bucket or (
        args.artifact_uri.removeprefix("gs://").split("/")[0] if args.artifact_uri.startswith("gs://") else ""
    )

    provenance = build_provenance(
        subject_name=args.artifact_uri,
        subject_digest={"sha256": artifact_sha256},
        builder_id=args.builder_id,
        build_type="https://kardome.com/bmt/runner-upload/v1",
        source_uri=f"https://github.com/{args.github_repository}" if args.github_repository else args.artifact_uri,
        git_sha=args.git_sha,
        invocation_id=args.invocation_id or os.environ.get("GITHUB_RUN_ID", ""),
        started_on=_now_utc(),
        finished_on=_now_utc(),
        extra_metadata={
            "artifact_uri": args.artifact_uri,
            "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
            "github_repository": args.github_repository or os.environ.get("GITHUB_REPOSITORY", ""),
        },
    )

    out_path = Path(args.out)
    out_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote runner provenance: {out_path}")

    if bucket and args.run_id:
        dest_uri = f"gs://{bucket}/provenance/runners/{args.run_id}.slsa.json"
        subprocess.check_call(["gcloud", "storage", "cp", str(out_path), dest_uri])
        print(f"Uploaded runner provenance: {dest_uri}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SLSA v1.0 provenance for BMT artifacts")
    sub = parser.add_subparsers(dest="command", required=True)

    # -- image subcommand --
    img = sub.add_parser("image", help="Provenance for a Packer-built GCE image")
    img.add_argument("--image-name", required=True)
    img.add_argument("--image-family", required=True)
    img.add_argument("--gcs-bucket", required=True)
    img.add_argument("--gcp-project", default="")
    img.add_argument("--builder-id", required=True, help="URI identifying the builder workflow")
    img.add_argument("--git-sha", required=True)
    img.add_argument("--invocation-id", default="")
    img.add_argument("--out", default="provenance.json")

    # -- runner subcommand --
    run = sub.add_parser("runner", help="Provenance for an uploaded runner artifact")
    run.add_argument("--artifact-uri", required=True, help="GCS URI of the artifact")
    run.add_argument("--artifact-sha256", default="")
    run.add_argument("--artifact-local-path", default="", help="Local file to compute sha256 from")
    run.add_argument("--gcs-bucket", default="")
    run.add_argument("--builder-id", required=True)
    run.add_argument("--git-sha", required=True)
    run.add_argument("--github-repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    run.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""), help="Used for GCS dest path")
    run.add_argument("--invocation-id", default="")
    run.add_argument("--out", default="provenance.json")

    args = parser.parse_args()
    if args.command == "image":
        cmd_image(args)
    elif args.command == "runner":
        cmd_runner(args)


if __name__ == "__main__":
    main()
