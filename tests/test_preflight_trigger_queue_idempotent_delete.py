from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CLI_ROOT = _ROOT / ".github" / "bmt"
if str(_CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLI_ROOT))

from cli import gcs  # noqa: E402
from cli.commands import workflow_trigger  # noqa: E402


def _valid_trigger_payload(*, triggered_at: str) -> dict[str, object]:
    return {
        "workflow_run_id": "111",
        "repository": "foo/bar",
        "sha": "0123456789abcdef0123456789abcdef01234567",
        "ref": "refs/heads/dev",
        "bucket": "test-bucket",
        "legs": [{"project": "sk", "bmt_id": "x", "run_id": "r1"}],
        "triggered_at": triggered_at,
    }


def test_preflight_trigger_queue_treats_not_found_delete_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Simulate a race where a stale trigger is listed but deleted before remove.

    Expected behavior: preflight exits successfully and does not request VM restart.
    """
    run_uri = "gs://test-bucket/runtime/triggers/runs/111.json"
    runs_prefix = "gs://test-bucket/runtime/triggers/runs/"
    listed_once = {"value": False}

    def _list_prefix(prefix: str) -> list[str]:
        if prefix == runs_prefix and not listed_once["value"]:
            listed_once["value"] = True
            return [run_uri]
        return []

    def _download_json(uri: str) -> tuple[dict[str, object] | None, str | None]:
        if uri == run_uri:
            return _valid_trigger_payload(triggered_at="2000-01-01T00:00:00Z"), None
        return None, "not found"

    def _delete_object(uri: str) -> None:
        if uri == run_uri:
            raise gcs.GcsError("404 not found")

    monkeypatch.setenv("GCS_BUCKET", "test-bucket")
    monkeypatch.setenv("GITHUB_RUN_ID", "222")
    monkeypatch.setenv("RUN_CONTEXT", "dev")
    monkeypatch.setenv("BMT_TRIGGER_STALE_SEC", "900")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "github_output.txt"))
    monkeypatch.setattr(workflow_trigger.gcs, "list_prefix", _list_prefix)
    monkeypatch.setattr(workflow_trigger.gcs, "download_json", _download_json)
    monkeypatch.setattr(workflow_trigger.gcs, "delete_object", _delete_object)

    workflow_trigger.run_preflight_trigger_queue()

    out_text = Path(tmp_path / "github_output.txt").read_text(encoding="utf-8")
    assert "restart_vm=false" in out_text
    assert "stale_cleanup_count=0" in out_text


def test_preflight_trigger_queue_preserves_fresh_non_pr_trigger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fresh non-PR triggers must be preserved (no cross-run trigger deletion)."""
    run_uri = "gs://test-bucket/runtime/triggers/runs/111.json"
    runs_prefix = "gs://test-bucket/runtime/triggers/runs/"
    rm_called = {"value": False}

    def _list_prefix(prefix: str) -> list[str]:
        if prefix == runs_prefix:
            return [run_uri]
        return []

    def _download_json(uri: str) -> tuple[dict[str, object] | None, str | None]:
        if uri == run_uri:
            return _valid_trigger_payload(triggered_at="2099-01-01T00:00:00Z"), None
        return None, "not found"

    def _delete_object(_uri: str) -> None:
        rm_called["value"] = True

    monkeypatch.setenv("GCS_BUCKET", "test-bucket")
    monkeypatch.setenv("GITHUB_RUN_ID", "222")
    monkeypatch.setenv("RUN_CONTEXT", "dev")
    monkeypatch.setenv("BMT_TRIGGER_STALE_SEC", "900")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "github_output.txt"))
    monkeypatch.setattr(workflow_trigger.gcs, "list_prefix", _list_prefix)
    monkeypatch.setattr(workflow_trigger.gcs, "download_json", _download_json)
    monkeypatch.setattr(workflow_trigger.gcs, "delete_object", _delete_object)

    workflow_trigger.run_preflight_trigger_queue()

    out_text = Path(tmp_path / "github_output.txt").read_text(encoding="utf-8")
    assert "restart_vm=false" in out_text
    assert "stale_cleanup_count=0" in out_text
    assert rm_called["value"] is False, "fresh trigger must not be deleted"
