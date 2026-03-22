"""BMT CI driver: matrix, trigger, VM lifecycle, runner upload. Module name: ci (under .github/bmt/)."""

from __future__ import annotations

__all__ = [
    "get_config",
    "get_context",
]

from ci import config

get_config = config.get_config
get_context = config.get_context
