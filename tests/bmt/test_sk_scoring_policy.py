"""Unit tests for SK scoring policy helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SK_SRC = str(Path(__file__).resolve().parents[2] / "benchmarks/projects/sk/plugin_workspaces/default/src")


def _sp():
    if _SK_SRC not in sys.path:
        sys.path.insert(0, _SK_SRC)
    from sk_plugin import sk_scoring_policy as sp

    return sp


def test_scoring_policy_record_defaults() -> None:
    sp = _sp()
    rec = sp.scoring_policy_record({})
    assert rec["schema_version"] == sp.SCORING_POLICY_SCHEMA_VERSION
    assert rec["primary_metric"] == "namuh_count"
    assert rec["reducer"] == "mean_ok_cases"
    assert rec["failure_policy"] == "strict"
    assert rec["comparison"] == "gte"
    assert rec["score_direction_hint"] == "higher_better"


def test_scoring_policy_record_merges_reporting_hints() -> None:
    sp = _sp()
    rec = sp.scoring_policy_record(
        {"comparison": "lte", "reporting_hints": {"utterances_per_file": 20, "dataset_note": "probe"}}
    )
    assert rec["reporting_hints"]["utterances_per_file"] == 20
    assert rec["reporting_hints"]["dataset_note"] == "probe"


def test_build_case_outcomes_truncates_long_error(tmp_path: Path) -> None:
    from backend.runtime.sdk.results import CaseResult

    sp = _sp()
    long_err = "x" * 3000
    log_path = tmp_path / "f.wav.log"
    cases = [
        CaseResult(
            case_id="f.wav",
            input_path=Path("/d/f.wav"),
            exit_code=1,
            status="failed",
            metrics={"namuh_count": 0.0},
            artifacts={"log_path": str(log_path)},
            error=long_err,
        )
    ]
    out = sp.build_case_outcomes(cases, max_error_chars=100)
    assert len(out) == 1
    assert len(out[0]["error"]) <= 100
    assert out[0]["log_name"] == "f.wav.log"


def test_aggregate_mean_ok_cases_empty() -> None:
    sp = _sp()
    assert sp.aggregate_mean_ok_cases([]) == 0.0
