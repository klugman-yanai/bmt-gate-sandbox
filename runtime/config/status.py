"""GitHub commit-status and check-run enums (L0 leaf — no gcp.image imports)."""

from __future__ import annotations

from enum import StrEnum


class CommitStatus(StrEnum):
    """GitHub commit status states (API: POST /repos/{owner}/{repo}/statuses/{sha})."""

    PENDING = "pending"
    SUCCESS = "success"
    ERROR = "error"
    FAILURE = "failure"


class CheckConclusion(StrEnum):
    """GitHub check-run conclusion values (API: PATCH /repos/{owner}/{repo}/check-runs/{id})."""

    SUCCESS = "success"
    FAILURE = "failure"
    NEUTRAL = "neutral"
    CANCELLED = "cancelled"


class CheckStatus(StrEnum):
    """GitHub check-run status values."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
