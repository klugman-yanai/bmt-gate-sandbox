"""Contract: bmt/failure-fallback classify merge (jq) prefers steps.classify outputs."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.unit


def _merge_classify(*, handshake_outputs: dict, classify_step_outputs: dict) -> dict:
    """Mirror `.github/actions/bmt/failure-fallback` Build failure context merge."""
    jq = shutil.which("jq")
    if not jq:
        pytest.skip("jq not installed")
    invoke = {
        "path": handshake_outputs.get("classify_path") or "unknown",
        "has_legs": handshake_outputs.get("has_legs") or "false",
        "accepted_projects": handshake_outputs.get("accepted_projects") or "[]",
        "filtered_matrix": handshake_outputs.get("filtered_matrix") or '{"include":[]}',
    }
    proc = subprocess.run(
        [
            jq,
            "-n",
            "--argjson",
            "invoke",
            json.dumps(invoke),
            "--argjson",
            "steps",
            json.dumps(classify_step_outputs),
            """
            {
              path: ($steps.path // $invoke.path // "unknown"),
              has_legs: ($steps.has_legs // $invoke.has_legs // "false"),
              accepted_projects: ($steps.accepted_projects // $invoke.accepted_projects // "[]"),
              filtered_matrix: ($steps.filtered_matrix // $invoke.filtered_matrix // "{\\"include\\":[]}")
            }
            """,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def test_merge_prefers_classify_step_over_empty_invoke() -> None:
    out = _merge_classify(
        handshake_outputs={},
        classify_step_outputs={
            "path": "run",
            "has_legs": "true",
            "accepted_projects": '["sk"]',
            "filtered_matrix": '{"include":[{"project":"sk"}]}',
        },
    )
    assert out["path"] == "run"
    assert out["has_legs"] == "true"
    assert out["accepted_projects"] == '["sk"]'


def test_merge_falls_back_when_steps_empty() -> None:
    out = _merge_classify(
        handshake_outputs={
            "classify_path": "skip_no_legs",
            "has_legs": "false",
        },
        classify_step_outputs={},
    )
    assert out["path"] == "skip_no_legs"
    assert out["has_legs"] == "false"
