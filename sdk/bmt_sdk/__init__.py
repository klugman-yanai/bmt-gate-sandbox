"""Stable BMT plugin SDK — zero external dependencies.

Typical usage::

    from bmt_sdk import BmtPlugin, ExecutionContext
    from bmt_sdk.results import ExecutionResult, PreparedAssets, ScoreResult, VerdictResult

Install with: pip install bmt-sdk
"""

from bmt_sdk.context import ExecutionContext
from bmt_sdk.models import BmtManifestView, ProjectManifestView
from bmt_sdk.plugin import BmtPlugin
from bmt_sdk.results import (
    CaseResult,
    CaseStatus,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)

__all__ = [
    "BmtManifestView",
    "BmtPlugin",
    "CaseResult",
    "CaseStatus",
    "ExecutionContext",
    "ExecutionResult",
    "PreparedAssets",
    "ProjectManifestView",
    "ScoreResult",
    "VerdictResult",
]
