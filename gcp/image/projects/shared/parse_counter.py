"""Shared counter-based runner output parser.

Used by projects whose runners emit a line like ``Hi NAMUH counter = <N>``.
Projects with different output formats implement their own parsing — the framework
does not assume any single runner output format.

The parsing boundary ensures that gate and coordinator logic only consumes typed
``FileRunResult`` objects, never raw runner stdout.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from gcp.image.models import BmtJobParsingConfig


def build_counter_regex(parsing_config: BmtJobParsingConfig | dict[str, Any] | None = None) -> re.Pattern[str]:
    """Build a compiled regex for extracting the counter value from runner output.

    Resolution order:
    1. Explicit ``counter_pattern`` from config
    2. ``keyword``-based pattern: ``Hi <keyword> counter = (\\d+)``
    3. Default: ``Hi NAMUH counter = (\\d+)``
    """
    if parsing_config is None:
        return re.compile(r"Hi NAMUH counter = (\d+)")

    if isinstance(parsing_config, BmtJobParsingConfig):
        pattern = parsing_config.counter_pattern.strip()
        keyword = parsing_config.keyword.strip()
    else:
        pattern = str(parsing_config.get("counter_pattern", "")).strip()
        keyword = str(parsing_config.get("keyword", "NAMUH")).strip()

    if pattern:
        return re.compile(pattern)
    if keyword:
        return re.compile(rf"Hi {re.escape(keyword)} counter = (\d+)")
    return re.compile(r"Hi NAMUH counter = (\d+)")


def read_counter_from_file(log_path: Path, counter_re: re.Pattern[str]) -> int:
    """Read runner log file and extract the last counter value. Returns 0 if not found."""
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return read_counter_from_text(text, counter_re)


def read_counter_from_text(text: str, counter_re: re.Pattern[str]) -> int:
    """Extract the last counter value from text. Returns 0 if not found."""
    matches = counter_re.findall(text)
    if not matches:
        return 0
    return int(matches[-1])
