"""Pydantic models for kardome batch JSON results (SkPlugin batch mode)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.runtime.sdk.results import CaseArtifacts, CaseMetrics, CaseResult, CaseStatus


class KardomeBatchCase(BaseModel):
    """One row in batch JSON ``results`` array."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    file: str | None = None
    case_id: str | None = None
    status: Literal["ok", "failed"]
    namuh_count: float
    exit_code: int = 0
    error: str = ""

    @field_validator("namuh_count")
    @classmethod
    def _finite_namuh(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("namuh_count must be finite")
        return v

    @model_validator(mode="after")
    def _non_empty_identity(self) -> KardomeBatchCase:
        cid = (self.case_id or "").strip()
        fid = (self.file or "").strip()
        if not cid and not fid:
            raise ValueError("Each result needs non-empty case_id or file")
        return self

    def to_case_result(self) -> CaseResult:
        """Map to plugin :class:`CaseResult` (legacy batch adapter contract)."""
        case_id = (self.case_id or self.file or "").strip()
        file_raw = self.file
        input_path = Path(str(file_raw).strip() if file_raw is not None else case_id)
        return CaseResult(
            case_id=case_id,
            input_path=input_path,
            exit_code=int(self.exit_code),
            status=CaseStatus(self.status),
            metrics=CaseMetrics(root={"namuh_count": float(self.namuh_count)}),
            artifacts=CaseArtifacts(root={}),
            runner_case_diagnostic=str(self.error or ""),
        )


class KardomeBatchFile(BaseModel):
    """Root object for batch JSON written under the task workspace."""

    model_config = ConfigDict(extra="ignore")

    results: list[KardomeBatchCase] = Field(min_length=1)
