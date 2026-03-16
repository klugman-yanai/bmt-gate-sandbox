"""Tests for Cloud Run task-index dispatch and coordinator mode."""

import json
from pathlib import Path

import pytest

from gcp.image.entrypoint_config import load_entrypoint_config


def test_task_mode_loads_trigger_and_index(tmp_path: Path) -> None:
    """Task mode reads trigger object path and task index."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "mode": "task",
        "bucket": "test-bucket",
        "trigger_object": "triggers/runs/12345.json",
        "workspace_root": str(tmp_path),
    }))
    config = load_entrypoint_config(str(config_file))
    assert config.mode == "task"
    assert config.task is not None
    assert config.task.bucket == "test-bucket"
    assert config.task.trigger_object == "triggers/runs/12345.json"
    assert config.task.task_index == 0  # default


def test_task_mode_reads_task_index_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Task mode picks up CLOUD_RUN_TASK_INDEX from env."""
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "3")
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "mode": "task",
        "bucket": "test-bucket",
        "trigger_object": "triggers/runs/12345.json",
        "workspace_root": str(tmp_path),
    }))
    config = load_entrypoint_config(str(config_file))
    assert config.task is not None
    assert config.task.task_index == 3


def test_coordinator_mode_loads(tmp_path: Path) -> None:
    """Coordinator mode reads workflow run ID and trigger object."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "mode": "coordinator",
        "bucket": "test-bucket",
        "workflow_run_id": "run-12345",
        "trigger_object": "triggers/runs/12345.json",
        "workspace_root": str(tmp_path),
    }))
    config = load_entrypoint_config(str(config_file))
    assert config.mode == "coordinator"
    assert config.coordinator_cfg is not None
    assert config.coordinator_cfg.workflow_run_id == "run-12345"


def test_env_fallback_task_mode_without_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When config file is absent, Cloud Run env vars can bootstrap task mode."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BMT_CONFIG", raising=False)
    monkeypatch.setenv("BMT_TRIGGER_OBJECT", "triggers/runs/abc.json")
    monkeypatch.setenv("BMT_WORKFLOW_RUN_ID", "wf-123")
    monkeypatch.setenv("GCS_BUCKET", "test-bucket")
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "2")
    monkeypatch.setenv("BMT_WORKSPACE_ROOT", "/tmp/work")

    config = load_entrypoint_config()
    assert config.mode == "task"
    assert config.task is not None
    assert config.task.bucket == "test-bucket"
    assert config.task.trigger_object == "triggers/runs/abc.json"
    assert config.task.task_index == 2
