"""Parity tests for matches() compiled-regex behavior."""

from __future__ import annotations

import re

import pytest

from tools.shared.bucket_sync import matches
from tools.shared.layout_patterns import DEFAULT_CODE_EXCLUDES

pytestmark = pytest.mark.unit

_SAMPLE_RELS = (
    "foo/__pycache__/x.pyc",
    "projects/sk/inputs/wavs/a.wav",
    "runtime/main.py",
    "triggers/foo.json",
    "plain.txt",
    "projects/sk/outputs/summary.json",
)


def _reference_matches(patterns: tuple[str, ...], rel: str) -> bool:
    return any(re.search(p, rel) for p in patterns)


@pytest.mark.parametrize("rel", _SAMPLE_RELS)
def test_matches_matches_naive_search(rel: str) -> None:
    assert matches(DEFAULT_CODE_EXCLUDES, rel) == _reference_matches(DEFAULT_CODE_EXCLUDES, rel)


def test_matches_empty_patterns() -> None:
    assert matches((), "anything") is False
