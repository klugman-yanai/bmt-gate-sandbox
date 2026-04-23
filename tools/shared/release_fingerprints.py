"""Helpers that compute per-surface fingerprints for the CI release marker.

Each function is side-effect-free and returns either a string fingerprint or
``None`` when the underlying tool fails (never raises — callers decide whether
``None`` should be fatal). The workflow composes the fingerprints into a single
``gs://$BUCKET/_state/release.json`` via the ``bmt release mark`` CLI.

See ``docs/architecture.md`` (handoff + release marker) and ``.github/workflows/release.yml``.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def plugins_tree_sha(repo_root: Path, subdir: str = "plugins/projects") -> str | None:
    """Return the git tree SHA of ``<repo_root>/<subdir>`` at HEAD.

    Uses ``git rev-parse HEAD:<subdir>`` — git's own content-addressable identifier
    for the directory. Returns ``None`` if the subdir does not exist at HEAD or git
    is unavailable, so the release marker simply omits ``plugins_sha`` rather than
    failing the release job for a non-critical fingerprint.
    """
    if not (repo_root / subdir).is_dir():
        return None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", f"HEAD:{subdir}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    if len(sha) != 40 or not all(c in "0123456789abcdef" for c in sha):
        return None
    return sha


def pulumi_stack_sha(pulumi_dir: Path, stack_name: str = "prod") -> str | None:
    """Return ``sha256`` of ``pulumi stack export`` output.

    Captures a stable fingerprint of the applied Pulumi state (resources,
    outputs, etc.) so the release marker can answer "is this stack the one
    produced by this release?". ``None`` on any pulumi failure; the release
    marker will simply omit the field.
    """
    if not pulumi_dir.is_dir():
        return None
    try:
        proc = subprocess.run(
            ["pulumi", "stack", "export", "--stack", stack_name, "--cwd", str(pulumi_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    payload = proc.stdout
    if not payload.strip():
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def emit_github_output(key: str, value: str) -> None:
    """Append ``key=value`` to ``$GITHUB_OUTPUT`` when set; no-op otherwise.

    Values must be single-line (no newlines), matching the context where CI
    consumes these fingerprints; the caller owns formatting. The newline check
    runs before the env-var check so local development catches malformed values
    even when ``$GITHUB_OUTPUT`` is unset.
    """
    import os

    if "\n" in value:
        raise ValueError(f"GitHub Actions output value for {key!r} contains a newline: {value!r}")
    path = os.environ.get("GITHUB_OUTPUT", "").strip()
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")
