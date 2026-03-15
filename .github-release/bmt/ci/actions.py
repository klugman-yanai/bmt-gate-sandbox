"""GitHub Actions output: annotations, groups, GITHUB_OUTPUT append."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _escape(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def gh_error(message: str) -> None:
    print(f"::error::{_escape(message)}", file=sys.stderr, flush=True)


def gh_warning(message: str) -> None:
    print(f"::warning::{_escape(message)}", file=sys.stderr, flush=True)


def gh_notice(message: str) -> None:
    print(f"::notice::{_escape(message)}", file=sys.stderr, flush=True)


def gh_debug(message: str) -> None:
    print(f"::debug::{_escape(message)}", file=sys.stderr, flush=True)


def gh_group(title: str) -> None:
    print(f"::group::{_escape(title)}", flush=True)


def gh_endgroup() -> None:
    print("::endgroup::", flush=True)


def write_github_output(github_output: str | None, key: str, value: str) -> None:
    """Append key=value to GITHUB_OUTPUT file (silently no-ops if path is None)."""
    if not github_output:
        return
    with Path(github_output).open("a", encoding="utf-8") as fh:
        fh.write(f"{key}={value}\n")
