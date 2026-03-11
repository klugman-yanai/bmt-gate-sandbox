"""BMT config: delegate to gcp/code/config/bmt_config.py (single source of truth).
Loads from .bmt/context.json when present (avoids env vars); falls back to env."""

from __future__ import annotations

import os
from pathlib import Path

from gcp.code.config.bmt_config import (
    BmtConfig,
    BmtContext,
)
from gcp.code.config.bmt_config import (
    get_config as _get_config_lib,
)
from gcp.code.config.bmt_config import (
    get_context_path as _get_context_path_lib,
)
from gcp.code.config.bmt_config import (
    load_bmt_config as _load_bmt_config_lib,
)
from gcp.code.config.bmt_config import (
    load_context_from_file as _load_context_from_file_lib,
)
from gcp.code.config.bmt_config import (
    reset_config_cache as _reset_config_cache_lib,
)

__all__ = [
    "BmtConfig",
    "BmtContext",
    "get_config",
    "get_context",
    "load_bmt_config",
    "reset_config_cache",
]

_CONFIG_CACHE: BmtConfig | None = None
_CONTEXT_CACHE: BmtContext | None = None


def load_bmt_config(
    config_path: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> BmtConfig:
    """Load config from lib (runtime = env or os.environ). Config_path ignored; lib has no JSON."""
    global _CONFIG_CACHE, _CONTEXT_CACHE
    _CONTEXT_CACHE = None
    runtime = dict(env) if env is not None else dict(os.environ)
    _CONFIG_CACHE = _load_bmt_config_lib(config_path=None, env=runtime)
    return _CONFIG_CACHE


def get_config() -> BmtConfig:
    """Load config: from .bmt/context.json if present, else from env. Cached per process."""
    global _CONFIG_CACHE, _CONTEXT_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    path = _get_context_path_lib(runtime=os.environ)
    ctx = _load_context_from_file_lib(path)
    if ctx is not None:
        _CONTEXT_CACHE = ctx
        _CONFIG_CACHE = ctx.config
        return _CONFIG_CACHE
    _CONFIG_CACHE = _get_config_lib(runtime=os.environ)
    return _CONFIG_CACHE


def get_context() -> BmtContext | None:
    """Return loaded context from file if we loaded from .bmt/context.json; else None."""
    global _CONTEXT_CACHE
    if _CONTEXT_CACHE is not None:
        return _CONTEXT_CACHE
    path = _get_context_path_lib(runtime=os.environ)
    ctx = _load_context_from_file_lib(path)
    if ctx is not None:
        _CONTEXT_CACHE = ctx
        return _CONTEXT_CACHE
    return None


def reset_config_cache() -> None:
    """Clear the config and context cache. Use from tests to force reload."""
    global _CONFIG_CACHE, _CONTEXT_CACHE
    _CONFIG_CACHE = None
    _CONTEXT_CACHE = None
    _reset_config_cache_lib()
