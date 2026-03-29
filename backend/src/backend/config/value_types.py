"""Nominal types and factories for pipeline identifiers and bucket-relative paths.

``RunId`` and ``ResultsPath`` are ``typing.NewType`` wrappers around ``str`` (zero
runtime overhead). Use ``as_run_id`` / ``as_results_path`` to enforce invariants
when constructing values from untrusted input.
"""

from __future__ import annotations

import re
from typing import NewType

_RUN_ID_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")

RUN_ID_MAX_LEN = 200

RunId = NewType("RunId", str)
ResultsPath = NewType("ResultsPath", str)


def sanitize_run_id(raw: str) -> str:
    """Normalize workflow/run id for GCS object paths (matches CI trigger path contract)."""
    value = _RUN_ID_SAFE.sub("-", (raw or "").strip())
    value = value.strip("-._")
    if not value:
        raise ValueError("run_id is empty after sanitization")
    return value[:RUN_ID_MAX_LEN]


def as_run_id(raw: str) -> RunId:
    """Return a sanitized ``RunId`` (raises if empty after normalization)."""
    return RunId(sanitize_run_id(raw))


def as_results_path(raw: str) -> ResultsPath:
    """Normalize bucket-relative results path: strip, no leading/trailing slashes, no gs://."""
    s = (raw or "").strip()
    if s.startswith("gs://"):
        msg = "results_path must be bucket-relative, not a gs:// URI"
        raise ValueError(msg)
    s = s.lstrip("/").rstrip("/")
    if not s:
        raise ValueError("results_path is empty after normalization")
    return ResultsPath(s)


def results_path_str(value: ResultsPath | str) -> str:
    """String form for formatting (``ResultsPath`` is ``str`` at runtime)."""
    return str(value)
