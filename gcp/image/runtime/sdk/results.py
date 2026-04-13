"""Backward-compatible re-export. Import from bmt_sdk instead."""

from bmt_sdk.results import (
    CaseResult,
    CaseStatus,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)

__all__ = [
    "CaseResult",
    "CaseStatus",
    "ExecutionResult",
    "PreparedAssets",
    "ScoreResult",
    "VerdictResult",
]
