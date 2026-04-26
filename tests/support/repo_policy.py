"""Repository-level test policy constants and path helpers.

Centralizes hardcoded project/dataset references so they appear in one place
and are easy to update when the sample data changes.
"""

from __future__ import annotations

from pathlib import Path

SAMPLE_PROJECT = "sk"
SAMPLE_BMT = "false_rejects"


def repo_stage_root(repo_root: Path) -> Path:
    """Path to the gcp/stage directory (local mirror of the GCS bucket)."""
    return repo_root / "gcp" / "stage"


def repo_stage_bmt_manifest(project: str, bmt_slug: str, *, repo_root: Path | None = None) -> Path:
    """Absolute path to a BMT manifest in gcp/stage, or relative path when repo_root is None.

    When ``repo_root`` is None, returns a path relative to the repo root — safe to
    use in tests that rely on the ``_stable_repo_cwd`` conftest fixture.
    """
    rel = Path("gcp") / "stage" / "projects" / project / "bmts" / bmt_slug / "bmt.json"
    return repo_root / rel if repo_root is not None else rel
