"""Tests for tools.shared.github_app_settings (GitHub App env precedence)."""

from __future__ import annotations

from pathlib import Path

import pytest
from backend.github.github_auth import DEV_PROFILE, PRIMARY_PROFILE

from tools.shared.github_app_settings import (
    DEV_APP_ID_KEYS,
    PRIMARY_APP_ID_KEYS,
    app_id_for_profile,
    first_nonempty_env,
    private_key_path_for_profile,
)

pytestmark = pytest.mark.unit


def test_first_nonempty_skips_empty_string_like_or_chain() -> None:
    """Empty first key must not block second (matches ``os.environ.get(a) or os.environ.get(b)``)."""
    env = {
        "GITHUB_APP_ID": "",
        "GH_APP_ID": "from-gh",
    }
    assert first_nonempty_env(PRIMARY_APP_ID_KEYS, env) == "from-gh"


def test_first_nonempty_respects_key_order() -> None:
    env = {
        "GITHUB_APP_ID": "primary-wins",
        "GH_APP_ID": "ignored",
    }
    assert first_nonempty_env(PRIMARY_APP_ID_KEYS, env) == "primary-wins"


@pytest.mark.parametrize(
    ("profile", "env", "expected"),
    [
        (
            DEV_PROFILE,
            {"GITHUB_APP_DEV_ID": "dev1"},
            "dev1",
        ),
        (
            DEV_PROFILE,
            {"GITHUB_APP_DEV_ID": "", "GH_APP_DEV_ID": "dev2"},
            "dev2",
        ),
        (
            PRIMARY_PROFILE,
            {"GITHUB_APP_ID": "p1"},
            "p1",
        ),
        (
            PRIMARY_PROFILE,
            {"GITHUB_APP_ID": "", "GH_APP_ID": "p2"},
            "p2",
        ),
    ],
)
def test_app_id_for_profile(profile: str, env: dict[str, str], expected: str) -> None:
    assert app_id_for_profile(profile, env) == expected


def test_private_key_path_three_key_chain_dev(tmp_path: Path) -> None:
    key = tmp_path / "key.pem"
    key.write_text("k", encoding="utf-8")
    env = {
        "GITHUB_APP_DEV_PRIVATE_KEY_PATH": "",
        "GH_APP_DEV_PRIVATE_KEY_PATH": "",
        "BMT_APP_PRIVATE_KEY_PATH": str(key),
    }
    assert private_key_path_for_profile(DEV_PROFILE, env) == str(key)


def test_private_key_path_primary_prefers_github_named() -> None:
    env = {
        "GITHUB_APP_PRIVATE_KEY_PATH": "/a.pem",
        "GH_APP_PRIVATE_KEY_PATH": "/b.pem",
    }
    assert private_key_path_for_profile(PRIMARY_PROFILE, env) == "/a.pem"
