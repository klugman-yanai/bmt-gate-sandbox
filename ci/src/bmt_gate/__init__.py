"""BMT CI driver: matrix, trigger, VM lifecycle, runner upload. Package: bmt_gate (under ci/)."""

from __future__ import annotations

__all__ = [
    "get_config",
    "get_context",
]

from bmt_gate import config

get_config = config.get_config
get_context = config.get_context
