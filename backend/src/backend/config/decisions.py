"""Closed sets for gate decisions and structured failure reasons (string enums)."""

from __future__ import annotations

from enum import StrEnum


class GateDecision(StrEnum):
    """CI gate outcome (string values stable for JSON/logs)."""

    ACCEPTED = "accepted"
    ACCEPTED_WITH_WARNINGS = "accepted_with_warnings"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


class ReasonCode(StrEnum):
    """Known reason codes for leg/plan outcomes (extend as new codes are introduced)."""

    JOBS_SCHEMA_INVALID = "jobs_schema_invalid"
    BMT_NOT_DEFINED = "bmt_not_defined"
    BMT_DISABLED = "bmt_disabled"
    SUPERSEDED = "superseded"
    INCOMPLETE_PLAN = "incomplete_plan"
    RUNNER_FAILURES = "runner_failures"
    RUNNER_TIMEOUT = "runner_timeout"
    DEMO_FORCE_PASS = "demo_force_pass"
    PARTIAL_MISSING = "partial_missing"
