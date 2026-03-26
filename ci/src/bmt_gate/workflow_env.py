"""Read workflow fields from WorkflowContext or process environment (single pattern)."""

from __future__ import annotations

import os

from bmt_gate.config import WorkflowContext


def read_workflow_str(
    w: WorkflowContext | None,
    attr: str,
    env_var: str,
    default: str = "",
) -> str:
    """Prefer typed workflow context; fall back to ``os.environ``."""
    if w is not None:
        return (getattr(w, attr, None) or default).strip()
    return (os.environ.get(env_var) or default).strip()
