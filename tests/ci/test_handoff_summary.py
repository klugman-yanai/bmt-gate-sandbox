"""Tests for BMT handoff step summary markdown."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from kardome_bmt.config import BmtConfig
from kardome_bmt.handoff_env import HandoffEnv
from kardome_bmt.handoff_summary import write_handoff_step_summary


def test_run_success_summary_single_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "step_summary.md"
    summary.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_REPOSITORY", "klugman-yanai/bmt-gcloud")
    monkeypatch.setenv(
        "WORKFLOW_EXECUTION_URL",
        "https://console.cloud.google.com/workflows/workflow/europe-west4/bmt-workflow/execution/x?project=train-kws-202311",
    )
    monkeypatch.setenv("WORKFLOW_EXECUTION_STATE", "ACTIVE")
    monkeypatch.setenv("DIAGNOSTICS_ARTIFACT", "bmt-handoff-diagnostics-24717270540")

    env = HandoffEnv(
        prepare_result="success",
        mode="run_success",
        head_sha="3e45a9ac076298eb4f8e94cb0dc91d031dfc8bd3",
        pr_number="100",
        orch_has_legs=True,
        repository="klugman-yanai/bmt-gcloud",
        head_branch="chore/open-pipeline-view-20260421",
        filtered_matrix_raw=json.dumps({"include": [{"project": "sk"}]}),
        accepted_projects_raw=json.dumps(["sk"]),
        dispatch_confirmed=True,
        failure_reason="",
        server="https://github.com",
        run_id="24717270540",
    )
    cfg = BmtConfig.model_validate({"gcp_project": "train-kws-202311", "gcs_bucket": "train-kws-202311-bmt-gate"})
    write_handoff_step_summary(cfg, env)

    text = summary.read_text(encoding="utf-8")
    assert text.startswith("## BMT\n")
    assert "BMT Handoff Context" not in text
    assert "Dispatch Status" not in text
    assert "Runtime Health Snapshot" not in text
    assert "[PR #100]" in text
    assert "[Handoff workflow]" in text
    assert "train-kws-202311" in text
    assert "GCP execution" in text
    assert "`ACTIVE`" in text
    assert "bmt-handoff-diagnostics-24717270540" in text


def test_failure_summary_includes_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "step_summary.md"
    summary.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_REPOSITORY", "klugman-yanai/bmt-gcloud")
    monkeypatch.setenv("CLASSIFY_OUTCOME", "success")
    monkeypatch.setenv("INVOKE_OUTCOME", "failure")

    env = HandoffEnv(
        prepare_result="success",
        mode="failure",
        head_sha="3e45a9ac076298eb4f8e94cb0dc91d031dfc8bd3",
        pr_number="100",
        orch_has_legs=True,
        repository="klugman-yanai/bmt-gcloud",
        head_branch="main",
        filtered_matrix_raw=json.dumps({"include": [{"project": "sk"}]}),
        accepted_projects_raw=json.dumps(["sk"]),
        dispatch_confirmed=False,
        failure_reason="invoke blew up",
        server="https://github.com",
        run_id="9",
    )
    cfg = BmtConfig.model_validate({"gcp_project": "p", "gcs_bucket": "b"})
    write_handoff_step_summary(cfg, env)

    text = summary.read_text(encoding="utf-8")
    assert "## BMT" in text
    assert "invoke blew up" in text
    assert "classify `success`" in text
    assert "invoke `failure`" in text


def test_verbose_matrix_appends_details(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "step_summary.md"
    summary.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_REPOSITORY", "klugman-yanai/bmt-gcloud")
    monkeypatch.setenv("BMT_HANDOFF_VERBOSE_SUMMARY", "1")

    env = HandoffEnv(
        prepare_result="success",
        mode="run_success",
        head_sha="abcdabcdabcdabcdabcdabcdabcdabcdabcd",
        pr_number="",
        orch_has_legs=False,
        repository="o/r",
        head_branch="x",
        filtered_matrix_raw=json.dumps({"include": [{"project": "a"}]}),
        accepted_projects_raw="[]",
        dispatch_confirmed=True,
        failure_reason="",
        server="https://github.com",
        run_id="1",
    )
    cfg = BmtConfig.model_validate({})
    write_handoff_step_summary(cfg, env)
    text = summary.read_text(encoding="utf-8")
    assert "<details>" in text
    assert '"project": "a"' in text
