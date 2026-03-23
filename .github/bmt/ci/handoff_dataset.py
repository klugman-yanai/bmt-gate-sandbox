"""GCS / stage validation for BMT dataset inputs."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ci import gcs
from ci.actions import gh_notice, gh_warning
from ci.config import BmtConfig


def validate_dataset_inputs(cfg: BmtConfig) -> None:
    """Fail early if any enabled BMT has no .wav files in its GCS inputs prefix."""
    bucket = (cfg.gcs_bucket or "").strip() or os.environ.get("GCS_BUCKET", "")
    if not bucket:
        raise RuntimeError("GCS_BUCKET is not set; cannot validate dataset inputs")
    accepted_raw = (os.environ.get("ACCEPTED_PROJECTS") or "[]").strip()
    accepted_projects: list[str] = json.loads(accepted_raw)
    if not isinstance(accepted_projects, list) or not accepted_projects:
        gh_notice("No accepted projects to validate.")
        return

    stage_root = Path("gcp/stage")
    errors: list[str] = []
    for project in accepted_projects:
        bmts_dir = stage_root / "projects" / project / "bmts"
        if not bmts_dir.is_dir():
            gh_warning(f"No bmts dir for project {project!r} at {bmts_dir}")
            continue
        for bmt_json_path in sorted(bmts_dir.glob("*/bmt.json")):
            bmt_slug = bmt_json_path.parent.name
            payload = json.loads(bmt_json_path.read_text(encoding="utf-8"))
            if not payload.get("enabled", True):
                continue
            inputs_prefix = str(payload.get("inputs_prefix", "")).strip()
            if not inputs_prefix:
                errors.append(f"{project}/{bmt_slug}: bmt.json missing inputs_prefix")
                continue
            prefix_uri = f"gs://{bucket}/{inputs_prefix}/"
            blobs = gcs.list_prefix(prefix_uri)
            wav_count = sum(1 for b in blobs if b.lower().endswith(".wav"))
            manifest_uri = f"gs://{bucket}/{inputs_prefix}/dataset_manifest.json"
            manifest_payload, _ = gcs.download_json(manifest_uri)
            if manifest_payload:
                expected_count = len(manifest_payload.get("files", []))
                if wav_count != expected_count:
                    errors.append(
                        f"{project}/{bmt_slug}: GCS has {wav_count} .wav files "
                        f"but manifest expects {expected_count}"
                    )
                else:
                    gh_notice(f"{project}/{bmt_slug}: {wav_count} .wav file(s) match manifest ✓")
            else:
                if wav_count == 0:
                    errors.append(f"{project}/{bmt_slug}: no .wav files found at {prefix_uri}")
                else:
                    gh_notice(f"{project}/{bmt_slug}: {wav_count} .wav file(s) at {prefix_uri}")

    if errors:
        for e in errors:
            print(f"::error::{e}")
        raise RuntimeError(
            f"Dataset validation failed: {len(errors)} BMT(s) have empty input datasets.\n"
            + "\n".join(f"  - {e}" for e in errors)
        )
