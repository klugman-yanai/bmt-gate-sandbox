"""Shared helpers for bucket sync and verify tools.

Provides local_digest, download_manifest, and matches used by sync_gcp,
sync_runtime_seed, verify_gcp_sync, and verify_runtime_seed_sync.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

# Files under projects/*/inputs/ that are safe to include in digests and sync.
# Everything else under inputs/ is treated as data (WAVs, audio corpora) and skipped.
_INPUTS_DATA_RE = re.compile(r"^projects/[^/]+/inputs/")
_INPUTS_ALLOWLISTED_FILENAMES = frozenset({".keep", "dataset_manifest.json"})


def is_inputs_data_path(rel: str) -> bool:
    """True if rel is a data file under projects/*/inputs/ (not .keep or dataset_manifest.json).

    Explicit guard against reading large audio corpora or FUSE-mounted datasets.
    Called before pattern-based exclusion in local_digest() and iter_source_files().
    """
    if not _INPUTS_DATA_RE.match(rel):
        return False
    filename = rel.rsplit("/", 1)[-1] if "/" in rel else rel
    return filename not in _INPUTS_ALLOWLISTED_FILENAMES


def matches(patterns: tuple[str, ...], rel: str) -> bool:
    """True if rel matches any of the regex patterns."""
    return any(re.search(p, rel) for p in patterns)


def local_digest(
    src: Path,
    include_artifacts: bool,
    exclude_patterns: tuple[str, ...],
) -> tuple[str, int]:
    """Compute SHA256 digest of sorted rel|sha256|size lines for files under src.

    When include_artifacts is False, paths matching exclude_patterns are skipped.
    Additionally, any data file under projects/*/inputs/ (not .keep or dataset_manifest.json)
    is always skipped regardless of include_artifacts, to prevent reading large audio corpora
    or FUSE-mounted datasets on every sync/commit hook invocation.
    Same algorithm as verify tools for idempotent skip check.
    """
    files: list[tuple[str, str, int]] = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src).as_posix()
        # Explicit guard: never read data files under projects/*/inputs/ (belt-and-suspenders
        # against FUSE mounts or real WAVs landing in the staging area).
        if is_inputs_data_path(rel):
            continue
        if not include_artifacts and matches(exclude_patterns, rel):
            continue
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        files.append((rel, h.hexdigest(), path.stat().st_size))
    digest_input = "\n".join(f"{r}|{s}|{sz}" for r, s, sz in files).encode("utf-8")
    digest = hashlib.sha256(digest_input).hexdigest()
    return digest, len(files)


def download_manifest(uri: str, required: bool = False) -> dict[str, object] | None:
    """Download and parse JSON manifest from GCS. Returns None on failure unless required=True."""
    proc = subprocess.run(
        ["gcloud", "storage", "cat", uri],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        if required:
            raise RuntimeError(f"Failed to read manifest {uri}: {(proc.stderr or proc.stdout or '').strip()}")
        return None
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        if required:
            raise RuntimeError(f"Manifest at {uri} is not valid JSON: {e}") from e
        return None
    if not isinstance(out, dict) and required:
        raise RuntimeError(f"Manifest at {uri} is not a JSON object")
    return out if isinstance(out, dict) else None
