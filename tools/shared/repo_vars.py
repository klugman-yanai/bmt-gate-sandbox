"""Resolve local developer config from environment or GitHub repo variables."""

from __future__ import annotations

import shutil
import subprocess
from functools import cache

from tools.repo.paths import repo_root
from tools.shared.env import get as env_get


def _gh_repo_var(name: str) -> str:
    gh = shutil.which("gh")
    if gh is None:
        return ""
    result = subprocess.run(
        [gh, "variable", "get", name],
        capture_output=True,
        check=False,
        cwd=repo_root(),
        text=True,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            returncode=result.returncode,
            cmd=result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result.stdout.strip()


@cache
def _cached_repo_var(name: str) -> str:
    return _gh_repo_var(name)


def clear_repo_var_cache() -> None:
    _cached_repo_var.cache_clear()


def repo_var(name: str) -> str:
    env_value = env_get(name)
    if env_value:
        return env_value
    try:
        return _cached_repo_var(name)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""
