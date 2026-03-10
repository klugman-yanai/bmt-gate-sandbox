"""Write merged BMT config to GITHUB_ENV for use by subsequent workflow steps."""

from __future__ import annotations

import os
from dataclasses import fields

from cli.shared import get_config
from cli.shared.config import BmtConfig


def _github_env_escape(value: str) -> str:
    """Escape value for appending to GITHUB_ENV (% and newlines)."""
    return value.replace("%", "%25").replace("\n", "%0A")


def run_load_env() -> None:
    """Load config (JSON + env overlay) and append KEY=value lines to GITHUB_ENV."""
    github_env = os.environ.get("GITHUB_ENV")
    if not github_env:
        raise RuntimeError("GITHUB_ENV is not set (not running in a GitHub Actions step?)")
    cfg = get_config()
    with open(github_env, "a", encoding="utf-8") as fh:
        for field in fields(BmtConfig):
            key = field.name.upper()
            val = str(getattr(cfg, field.name))
            fh.write(f"{key}={_github_env_escape(val)}\n")
