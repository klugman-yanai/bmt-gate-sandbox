"""Execution and scoring value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

CaseStatus = Literal["ok", "failed"]


@dataclass(frozen=True, slots=True)
class PreparedAssets:
    """Return value of :meth:`bmt_sdk.plugin.BmtPlugin.prepare`."""

    dataset_root: Path
    workspace_root: Path
    runner_path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaseResult:
    """One input file: numeric primary metric in ``metrics``."""

    case_id: str
    input_path: Path
    exit_code: int
    status: CaseStatus
    metrics: dict[str, float] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    error: str = ""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Input to :meth:`bmt_sdk.plugin.BmtPlugin.score`."""

    execution_mode_used: str
    case_results: list[CaseResult]
    raw_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """Input to :meth:`bmt_sdk.plugin.BmtPlugin.evaluate` and check rendering."""

    aggregate_score: float
    metrics: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CheckRunCopy:
    """Optional wording for the BMT Gate check; merge into ``ScoreResult.extra``."""

    success_in_words: str | None = None
    reason_text: str | None = None
    metric_label: str | None = None

    def as_extra_fragment(self) -> dict[str, dict[str, str]]:
        payload: dict[str, str] = {}
        if isinstance(self.success_in_words, str) and self.success_in_words.strip():
            payload["success_in_words"] = self.success_in_words.strip()
        if isinstance(self.reason_text, str) and self.reason_text.strip():
            payload["reason_text"] = self.reason_text.strip()
        if isinstance(self.metric_label, str) and self.metric_label.strip():
            payload["metric_label"] = self.metric_label.strip()
        if not payload:
            return {}
        return {"check_run_copy": payload}


def merge_check_run_copy(extra: dict[str, Any], copy: CheckRunCopy | None) -> dict[str, Any]:
    """Copy of ``extra`` with ``check_run_copy`` fields from ``copy``."""
    out = dict(extra)
    if copy is None:
        return out
    out.update(copy.as_extra_fragment())
    return out


@dataclass(frozen=True, slots=True)
class VerdictResult:
    """Pass/fail and ``reason_code`` for the gate."""

    passed: bool
    status: str
    reason_code: str
    summary: dict[str, Any] = field(default_factory=dict)
