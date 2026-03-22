"""Execution and scoring value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PreparedAssets:
    dataset_root: Path
    workspace_root: Path
    runner_path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    input_path: Path
    exit_code: int
    status: str
    metrics: dict[str, float] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    error: str = ""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    execution_mode_used: str
    case_results: list[CaseResult]
    raw_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScoreResult:
    aggregate_score: float
    metrics: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VerdictResult:
    passed: bool
    status: str
    reason_code: str
    summary: dict[str, Any] = field(default_factory=dict)
