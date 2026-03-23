"""Enforce a small root set of workflow YAML files under .github/workflows/."""

from __future__ import annotations

import pytest

from tools.repo.paths import repo_root

pytestmark = pytest.mark.unit

# Ship / release workflows and repo-default CI live at the workflows directory root.
# Operational and dev-only workflows live under internal/.
_ALLOWED_ROOT_WORKFLOW_YML = frozenset(
    {
        "bmt-cancel-on-pr-close.yml",
        "build-and-test-dev.yml",
        "build-and-test.yml",
        "bmt-handoff.yml",
        "clang-format-auto-fix.yml",
    }
)


def test_workflows_directory_root_has_only_allowed_yml() -> None:
    root = repo_root() / ".github" / "workflows"
    names = {p.name for p in root.glob("*.yml")}
    assert names == _ALLOWED_ROOT_WORKFLOW_YML, (
        f"Expected root .github/workflows/*.yml to be exactly {_ALLOWED_ROOT_WORKFLOW_YML}, got {sorted(names)}"
    )
