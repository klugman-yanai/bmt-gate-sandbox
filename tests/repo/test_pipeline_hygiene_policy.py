"""Policy guardrails for pipeline adapters and shared control-plane contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.repo.paths import repo_root

pytestmark = pytest.mark.unit

_ALLOWED_GITHUBKIT_IMPORTS = {
    "backend/src/backend/github/client.py",
    "ci/src/bmtgate/clients/github.py",
    "tools/repo/gh_app_perms.py",
}

_CONTROL_PLANE_LITERAL_ALLOWLIST = {
    "contracts/src/bmtcontract/constants.py",
    "contracts/src/bmtcontract/paths.py",
}

_NO_BROAD_EXCEPT_FILES = {
    "backend/src/backend/github/github_auth.py",
    "backend/src/backend/github/statuses.py",
    "ci/src/bmtgate/clients/gcs.py",
    "ci/src/bmtgate/clients/github.py",
    "ci/src/bmtgate/clients/workflows.py",
    "ci/src/bmtgate/handoff/dispatch.py",
    "tools/bmt/stage_doctor.py",
    "tools/bmt/ops_doctor.py",
}


def test_direct_githubkit_imports_stay_within_adapter_modules() -> None:
    root = repo_root()
    offenders: list[str] = []
    for rel in _python_files_under(root, "backend/src", "ci/src", "tools"):
        text = (root / rel).read_text(encoding="utf-8")
        if ("from githubkit" in text or "import githubkit" in text) and rel not in _ALLOWED_GITHUBKIT_IMPORTS:
            offenders.append(rel)
    assert offenders == []


def test_control_plane_literals_live_in_bmtcontract_only() -> None:
    root = repo_root()
    offenders: list[str] = []
    literals = (
        "triggers/dispatch/",
        "triggers/finalization/",
        "triggers/leases/",
        '"bmt_recovery_used"',
        '"bmt_dispatch_fallback_used"',
    )
    for rel in _python_files_under(root, "backend/src", "ci/src", "tools", "contracts/src"):
        text = (root / rel).read_text(encoding="utf-8")
        if any(literal in text for literal in literals) and rel not in _CONTROL_PLANE_LITERAL_ALLOWLIST:
            offenders.append(rel)
    assert offenders == []


def test_selected_pipeline_adapters_do_not_use_broad_except_exception() -> None:
    root = repo_root()
    offenders: list[str] = []
    for rel in sorted(_NO_BROAD_EXCEPT_FILES):
        text = (root / rel).read_text(encoding="utf-8")
        if "except Exception" in text:
            offenders.append(rel)
    assert offenders == []


def test_handoff_workflow_keeps_bmt_recovery_used_as_primary_public_output() -> None:
    handoff = (repo_root() / ".github" / "workflows" / "bmt-handoff.yml").read_text(encoding="utf-8")

    assert "bmt_recovery_used" in handoff
    assert "Deprecated alias of bmt_recovery_used." in handoff


def _python_files_under(root: Path, *dirs: str) -> list[str]:
    files: list[str] = []
    for rel_dir in dirs:
        base = root / rel_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            files.append(path.relative_to(root).as_posix())
    return files
