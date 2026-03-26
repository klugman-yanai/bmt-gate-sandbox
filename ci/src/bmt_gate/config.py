"""BMT config: thin re-export from bmt_gate.bmt_config. Load env into GITHUB_ENV."""

from __future__ import annotations

import os

from bmt_gate.bmt_config import (
    BmtConfig,
    BmtContext,
)
from bmt_gate.bmt_config import (
    get_config as _get_config_lib,
)
from bmt_gate.bmt_config import (
    get_context_path as _get_context_path_lib,
)
from bmt_gate.bmt_config import (
    load_context_from_file as _load_context_from_file_lib,
)

__all__ = ["BmtConfig", "BmtContext", "get_config", "get_context", "load_env"]


def get_config() -> BmtConfig:
    """Load config: from .bmt/context.json if present, else from env."""
    path = _get_context_path_lib(runtime=os.environ)
    ctx = _load_context_from_file_lib(path)
    if ctx is not None:
        return ctx.config
    return _get_config_lib(runtime=os.environ)


def get_context() -> BmtContext | None:
    """Return loaded context from file if we loaded from .bmt/context.json; else None."""
    path = _get_context_path_lib(runtime=os.environ)
    return _load_context_from_file_lib(path)


def _github_env_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\n", "%0A")


def load_env() -> None:
    """Load config from lib and append KEY=value lines to GITHUB_ENV."""
    github_env = os.environ.get("GITHUB_ENV")
    if not github_env:
        raise RuntimeError("GITHUB_ENV is not set (not running in a GitHub Actions step?)")
    cfg = get_config()
    with open(github_env, "a", encoding="utf-8") as fh:
        for name in BmtConfig.model_fields:
            val = getattr(cfg, name)
            key = name.upper()
            fh.write(f"{key}={_github_env_escape(str(val))}\n")
