"""Docs alignment checks for pipeline follow-up operator surfaces."""

from __future__ import annotations

import pytest

from tools.repo.paths import repo_root

pytestmark = pytest.mark.unit


def _read(rel: str) -> str:
    return (repo_root() / rel).read_text(encoding="utf-8")


def test_runbook_and_e2e_docs_cover_ops_doctor_and_dispatch_receipts() -> None:
    runbook = _read("docs/runbook.md")
    e2e = _read("docs/pipeline-e2e-summary.md")

    assert "uv run bmt ops doctor --workflow-run-id <id>" in runbook
    assert "triggers/dispatch/<id>.json" in runbook
    assert "triggers/dispatch/{wid}.json" in e2e
    assert "bmt_recovery_used" in e2e


def test_architecture_and_weak_points_docs_cover_reconciliation_surface() -> None:
    architecture = _read("docs/architecture.md")
    weak_points = _read("docs/weak-points-remediation.md")

    assert "uv run bmt ops doctor" in architecture
    assert "Future structure note" in architecture
    assert "triggers/dispatch/{wid}.json" in weak_points
    assert "needs_reconciliation" in weak_points
