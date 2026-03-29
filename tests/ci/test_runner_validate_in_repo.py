from __future__ import annotations

from pathlib import Path

import pytest
from bmtgate.clients.gcs import GcsError
from bmtgate.matrix.runner import RunnerManager

pytestmark = pytest.mark.unit


def _runner_manager() -> RunnerManager:
    return RunnerManager(cfg=object(), ctx=None)


def test_validate_in_repo_accepts_runner_present_in_bucket(monkeypatch) -> None:
    marker_calls: list[str] = []
    monkeypatch.setenv("PROJECT", "sk")
    monkeypatch.setenv("PRESET", "default")
    monkeypatch.setenv("GCS_BUCKET", "demo-bucket")
    monkeypatch.setattr("bmtgate.matrix.runner.gcs.object_exists", lambda _uri: True)
    def _record_marker(_self: RunnerManager) -> None:
        marker_calls.append("marker")

    monkeypatch.setattr("bmtgate.matrix.runner.RunnerManager._write_handoff_uploaded_marker", _record_marker)

    _runner_manager().validate_in_repo()

    assert marker_calls == ["marker"]


def test_validate_in_repo_accepts_local_repo_fallback_when_bucket_reports_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    marker_calls: list[str] = []
    monkeypatch.chdir(tmp_path)
    local_runner = tmp_path / "benchmarks" / "projects" / "sk" / "kardome_runner"
    local_runner.parent.mkdir(parents=True, exist_ok=True)
    local_runner.write_bytes(b"runner")

    monkeypatch.setenv("PROJECT", "sk")
    monkeypatch.setenv("PRESET", "default")
    monkeypatch.setenv("GCS_BUCKET", "demo-bucket")
    monkeypatch.setattr("bmtgate.matrix.runner.gcs.object_exists", lambda _uri: False)
    def _record_marker(_self: RunnerManager) -> None:
        marker_calls.append("marker")

    monkeypatch.setattr("bmtgate.matrix.runner.RunnerManager._write_handoff_uploaded_marker", _record_marker)

    _runner_manager().validate_in_repo()

    assert marker_calls == ["marker"]


def test_validate_in_repo_hard_fails_on_gcs_verification_error_even_with_local_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    marker_calls: list[str] = []
    monkeypatch.chdir(tmp_path)
    local_runner = tmp_path / "benchmarks" / "projects" / "sk" / "kardome_runner"
    local_runner.parent.mkdir(parents=True, exist_ok=True)
    local_runner.write_bytes(b"runner")

    monkeypatch.setenv("PROJECT", "sk")
    monkeypatch.setenv("PRESET", "default")
    monkeypatch.setenv("GCS_BUCKET", "demo-bucket")
    monkeypatch.setattr(
        "bmtgate.matrix.runner.gcs.object_exists",
        lambda _uri: (_ for _ in ()).throw(GcsError("quota spike")),
    )
    def _record_marker(_self: RunnerManager) -> None:
        marker_calls.append("marker")

    monkeypatch.setattr("bmtgate.matrix.runner.RunnerManager._write_handoff_uploaded_marker", _record_marker)

    with pytest.raises(RuntimeError, match="Failed to verify runner in GCS"):
        _runner_manager().validate_in_repo()

    assert marker_calls == []
