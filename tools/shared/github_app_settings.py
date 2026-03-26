"""Centralized GitHub App id and private-key **path** resolution from env.

Precedence matches the former ``get_app_id_from_env`` / ``get_private_key_path_from_env``
chains in ``gh_app_perms``: for each tuple, the first key whose value is **non-empty**
after strip wins (empty strings do not block a later key — same as ``a or b``).

We do not use ``pydantic`` ``AliasChoices`` for env here: Settings would treat an empty
explicit env value as set and would not fall through to the next alias.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from backend.github.github_auth import DEV_PROFILE, PRIMARY_PROFILE

__all__ = [
    "DEV_APP_ID_KEYS",
    "DEV_PRIVATE_KEY_PATH_KEYS",
    "PRIMARY_APP_ID_KEYS",
    "PRIMARY_PRIVATE_KEY_PATH_KEYS",
    "app_id_for_profile",
    "first_nonempty_env",
    "private_key_path_for_profile",
]

# Order matters: first non-empty value wins (matches former ``or`` chains).
DEV_APP_ID_KEYS: tuple[str, ...] = ("GITHUB_APP_DEV_ID", "GH_APP_DEV_ID")
PRIMARY_APP_ID_KEYS: tuple[str, ...] = ("GITHUB_APP_ID", "GH_APP_ID")

DEV_PRIVATE_KEY_PATH_KEYS: tuple[str, ...] = (
    "GITHUB_APP_DEV_PRIVATE_KEY_PATH",
    "GH_APP_DEV_PRIVATE_KEY_PATH",
    "BMT_APP_PRIVATE_KEY_PATH",
)
PRIMARY_PRIVATE_KEY_PATH_KEYS: tuple[str, ...] = (
    "GITHUB_APP_PRIVATE_KEY_PATH",
    "GH_APP_PRIVATE_KEY_PATH",
    "BMT_APP_PRIVATE_KEY_PATH",
)


def first_nonempty_env(keys: tuple[str, ...], env: Mapping[str, str] | None = None) -> str:
    """Return the first stripped non-empty value for *keys* in *env* (default: ``os.environ``)."""
    resolved = env if env is not None else os.environ
    for key in keys:
        raw = resolved.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if value:
            return value
    return ""


def app_id_for_profile(profile: str, env: Mapping[str, str] | None = None) -> str:
    """Resolve app id for *profile* (``dev`` or ``primary``)."""
    if profile == DEV_PROFILE:
        return first_nonempty_env(DEV_APP_ID_KEYS, env)
    if profile == PRIMARY_PROFILE:
        return first_nonempty_env(PRIMARY_APP_ID_KEYS, env)
    return first_nonempty_env(PRIMARY_APP_ID_KEYS, env)


def private_key_path_for_profile(profile: str, env: Mapping[str, str] | None = None) -> str:
    """Resolve PEM path for *profile*."""
    if profile == DEV_PROFILE:
        return first_nonempty_env(DEV_PRIVATE_KEY_PATH_KEYS, env)
    if profile == PRIMARY_PROFILE:
        return first_nonempty_env(PRIMARY_PRIVATE_KEY_PATH_KEYS, env)
    return first_nonempty_env(PRIMARY_PRIVATE_KEY_PATH_KEYS, env)
