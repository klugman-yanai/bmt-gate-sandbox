"""Tests for backend.config.env_parse."""

from __future__ import annotations

import pytest
from backend.config.env_parse import is_truthy_env_value

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, False),
        ("", False),
        ("   ", False),
        ("0", False),
        ("false", False),
        ("no", False),
        ("maybe", False),
        ("1", True),
        ("true", True),
        ("yes", True),
        ("TRUE", True),
        (" Yes ", True),
        ("\ttrue\n", True),
    ],
)
def test_is_truthy_env_value(raw: str | None, expected: bool) -> None:
    assert is_truthy_env_value(raw) is expected
