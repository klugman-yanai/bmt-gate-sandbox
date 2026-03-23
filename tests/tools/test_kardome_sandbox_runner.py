"""Tests for tools/scripts/kardome_sandbox_runner counter semantics."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from gcp.image.runtime.stdout_counter_parse import (
    StdoutCounterParseConfig,
    compile_counter_pattern,
    read_counter_from_log,
)

_ROOT = Path(__file__).resolve().parents[2]
_RUNNER_PATH = _ROOT / "tools" / "scripts" / "kardome_sandbox_runner.py"

_spec = importlib.util.spec_from_file_location("kardome_sandbox_runner", _RUNNER_PATH)
assert _spec is not None and _spec.loader is not None
_ksr = importlib.util.module_from_spec(_spec)
sys.modules["kardome_sandbox_runner"] = _ksr
_spec.loader.exec_module(_ksr)

pytestmark = pytest.mark.unit

_DEFAULT_RE = compile_counter_pattern(StdoutCounterParseConfig())


def test_read_counter_returns_none_when_pattern_missing(tmp_path: Path) -> None:
    log = tmp_path / "run.log"
    log.write_text("no NAMUH line here\n", encoding="utf-8")
    assert read_counter_from_log(log, _DEFAULT_RE) is None


def test_read_counter_returns_last_match(tmp_path: Path) -> None:
    log = tmp_path / "run.log"
    log.write_text("Hi NAMUH counter = 1\nHi NAMUH counter = 99\n", encoding="utf-8")
    assert read_counter_from_log(log, _DEFAULT_RE) == 99


def test_read_counter_warns_on_replacement_char(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    caplog.set_level(logging.WARNING)
    log = tmp_path / "run.log"
    log.write_text("Hi NAMUH counter = 1\n\uFFFD\n", encoding="utf-8")
    assert read_counter_from_log(log, _DEFAULT_RE) == 1
    assert "encoding replacement" in caplog.text.lower()


def test_custom_counter_pattern_via_config(tmp_path: Path) -> None:
    log = tmp_path / "run.log"
    log.write_text("SCORE 7\n", encoding="utf-8")
    re_custom = compile_counter_pattern(
        StdoutCounterParseConfig.model_validate({"counter_pattern": r"SCORE (\d+)"})
    )
    assert read_counter_from_log(log, re_custom) == 7
