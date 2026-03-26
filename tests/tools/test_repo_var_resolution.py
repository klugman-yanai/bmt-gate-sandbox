from __future__ import annotations

import subprocess

import pytest

from tools.shared.bucket_env import bucket_from_env
from tools.shared.repo_vars import clear_repo_var_cache, repo_var

pytestmark = pytest.mark.unit


def _gh_value(_name: str) -> str:
    return "gh-value"


def _gh_bucket(_name: str) -> str:
    return "gh-bucket"


def test_repo_var_prefers_environment(monkeypatch) -> None:
    clear_repo_var_cache()
    monkeypatch.setenv("GCS_BUCKET", "env-bucket")
    monkeypatch.setattr("tools.shared.repo_vars._gh_repo_var", _gh_value)

    assert repo_var("GCS_BUCKET") == "env-bucket"
    assert bucket_from_env() == "env-bucket"


def test_repo_var_falls_back_to_github_repo_vars(monkeypatch) -> None:
    clear_repo_var_cache()
    monkeypatch.delenv("GCS_BUCKET", raising=False)
    monkeypatch.setattr("tools.shared.repo_vars._gh_repo_var", _gh_bucket)

    assert repo_var("GCS_BUCKET") == "gh-bucket"
    assert bucket_from_env() == "gh-bucket"


def test_repo_var_returns_empty_when_gh_lookup_fails(monkeypatch) -> None:
    clear_repo_var_cache()
    monkeypatch.delenv("GCS_BUCKET", raising=False)

    def _raise(name: str) -> str:
        raise subprocess.CalledProcessError(returncode=1, cmd=["gh", "variable", "get", name])

    monkeypatch.setattr("tools.shared.repo_vars._gh_repo_var", _raise)

    assert repo_var("GCS_BUCKET") == ""
