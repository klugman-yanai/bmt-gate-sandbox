"""Tests for gate comparison normalization in gcp/code/sk/bmt_manager.py."""

from __future__ import annotations

import gcp.code.projects.sk.bmt_manager as mgr


def test_false_reject_forces_gte_comparison() -> None:
    assert mgr._effective_gate_comparison("false_reject_namuh", "lte") == "gte"


def test_non_false_reject_keeps_lte_comparison() -> None:
    assert mgr._effective_gate_comparison("false_accept_namuh", "lte") == "lte"


def test_comparison_normalization_trims_and_lowercases() -> None:
    assert mgr._effective_gate_comparison("false_reject_namuh", " GtE ") == "gte"
