"""Serialize ``BmtManifest`` to repo JSON (Pydantic v2); for future Python-first specs / export."""

from __future__ import annotations

from pathlib import Path

from gcp.image.runtime.models import BmtManifest


def write_bmt_manifest_json(path: Path, manifest: BmtManifest) -> None:
    """Write ``bmt.json`` with stable, review-friendly formatting (``results_prefix`` alias preserved)."""
    text = manifest.model_dump_json(by_alias=True, indent=2, exclude_none=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_bmt_manifest(path: Path) -> BmtManifest:
    return BmtManifest.model_validate_json(path.read_text(encoding="utf-8"))
