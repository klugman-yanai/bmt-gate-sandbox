"""BMT pipeline domain status strings (leg verdict + in-flight progress).

These are **not** GitHub Check Run / commit-status API values; those live in
``backend.config.status`` (``CheckConclusion``, ``CommitStatus``, etc.).

JSON artifacts (e.g. ``ci_verdict.json``) continue to use the same string values;
this module is the single source of truth for those literals in Python code.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

# Some call sites / display maps use "failure" as a synonym for terminal fail.
BMT_LEG_FAIL_SYNONYMS: frozenset[str] = frozenset({"fail", "failure"})


class BmtLegStatus(StrEnum):
    """Terminal leg verdict (manager / summary JSON ``status``)."""

    PASS = "pass"
    FAIL = "fail"


class BmtProgressStatus(StrEnum):
    """Coordinator progress row while a leg is not finished."""

    PENDING = "pending"
    RUNNING = "running"


def leg_status_is_pass(status: str) -> bool:
    return status == BmtLegStatus.PASS.value


def leg_status_is_fail(status: str) -> bool:
    return status in BMT_LEG_FAIL_SYNONYMS


def progress_status_is_in_flight(status: str) -> bool:
    return status in (BmtProgressStatus.PENDING.value, BmtProgressStatus.RUNNING.value)


def summary_dict_leg_passed(summary: dict[str, Any]) -> bool:
    """True if a manager-summary dict represents a passing leg.

    ``passed`` wins when present (matches legacy ``passed or status == pass`` logic).
    """
    p = summary.get("passed")
    if p is True:
        return True
    if p is False:
        return False
    return leg_status_is_pass(str(summary.get("status") or ""))
