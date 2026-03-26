"""Tests for pending-trigger guard in trigger command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from bmt_gate import gcs as gcs_module
from bmt_gate.trigger import TriggerManager
from bmt_gate.trigger import DEFAULT_DESCRIPTION_PENDING, DEFAULT_RUNTIME_CONTEXT, PROJECT_WIDE_BMT_ID

from tools.repo.sk_bmt_ids import SK_BMT_FALSE_REJECT_NAMUH


def _set_required_env(monkeypatch: pytest.MonkeyPatch, output_file: Path, matrix: str, run_context: str) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("GCS_BUCKET", "bucket-a")
    monkeypatch.setenv("GCP_WIF_PROVIDER", "projects/1/locations/global/workloadIdentityPools/p/providers/p")
    monkeypatch.setenv("GCP_SA_EMAIL", "bmt@example.iam.gserviceaccount.com")
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("GCP_ZONE", "zone")
    monkeypatch.setenv("BMT_LIVE_VM", "vm")
    monkeypatch.setenv("GITHUB_RUN_ID", "10001")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/dev")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("BMT_STATUS_CONTEXT", "BMT Gate")
    monkeypatch.setenv("FILTERED_MATRIX_JSON", matrix)
    monkeypatch.setenv("RUN_CONTEXT", run_context)


def _mock_pubsub_publisher(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub Pub/Sub publish so trigger tests do not call real GCP (topic default is now set in constants)."""
    mock_future = MagicMock()
    mock_future.result.return_value = None
    mock_client = MagicMock()
    mock_client.topic_path = lambda project, topic: f"projects/{project}/topics/{topic}"
    mock_client.publish.return_value = mock_future
    try:
        from google.cloud import pubsub_v1

        monkeypatch.setattr(pubsub_v1, "PublisherClient", MagicMock(return_value=mock_client))
    except ImportError:
        pass


def test_trigger_rejects_when_other_pending_trigger_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_file = tmp_path / "out.txt"
    matrix = json.dumps({"include": [{"project": "sk", "bmt_id": SK_BMT_FALSE_REJECT_NAMUH}]})
    _set_required_env(monkeypatch, output_file, matrix, "dev")

    runtime_root = "gs://bucket-a"
    monkeypatch.setattr(
        gcs_module,
        "list_prefix",
        lambda _prefix: [
            f"{runtime_root}/triggers/runs/99999.json",
            f"{runtime_root}/triggers/runs/10001.json",
        ],
    )
    uploaded: list[str] = []
    monkeypatch.setattr(gcs_module, "upload_json", lambda uri, _payload: uploaded.append(uri))

    with pytest.raises(RuntimeError, match="pending run trigger"):
        TriggerManager.from_env().write()
    assert uploaded == []


def test_trigger_allows_when_only_current_run_trigger_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_file = tmp_path / "out.txt"
    matrix = json.dumps({"include": [{"project": "sk", "bmt_id": SK_BMT_FALSE_REJECT_NAMUH}]})
    _set_required_env(monkeypatch, output_file, matrix, "dev")
    _mock_pubsub_publisher(monkeypatch)

    current_trigger = "gs://bucket-a/triggers/runs/10001.json"
    monkeypatch.setattr(gcs_module, "list_prefix", lambda _prefix: [current_trigger])
    uploaded: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(gcs_module, "upload_json", lambda uri, payload: uploaded.append((uri, payload)))

    TriggerManager.from_env().write()
    assert len(uploaded) == 1
    assert uploaded[0][0] == current_trigger
    payload = uploaded[0][1]
    assert payload["description_pending"] == DEFAULT_DESCRIPTION_PENDING
    assert payload["runtime_status_context"] == DEFAULT_RUNTIME_CONTEXT
    assert payload["legs"] == [
        {
            "project": "sk",
            "bmt_id": PROJECT_WIDE_BMT_ID,
            "run_id": payload["legs"][0]["run_id"],
            "request_scope": "project_wide",
            "triggered_at": payload["legs"][0]["triggered_at"],
        }
    ]
    assert "description_success" not in payload
    assert "description_failure" not in payload
    assert "code_manifest_digest" not in payload
    assert output_file.exists()


def test_trigger_collapses_multiple_rows_to_unique_project_requests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_file = tmp_path / "out.txt"
    matrix = json.dumps(
        {
            "include": [
                {"project": "sk", "bmt_id": "foo"},
                {"project": "sk", "bmt_id": "bar"},
                {"project": "lgtv", "bmt_id": "baz"},
            ]
        }
    )
    _set_required_env(monkeypatch, output_file, matrix, "dev")
    _mock_pubsub_publisher(monkeypatch)

    current_trigger = "gs://bucket-a/triggers/runs/10001.json"
    monkeypatch.setattr(gcs_module, "list_prefix", lambda _prefix: [current_trigger])
    uploaded: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(gcs_module, "upload_json", lambda uri, payload: uploaded.append((uri, payload)))

    TriggerManager.from_env().write()
    payload = uploaded[0][1]
    legs = payload["legs"]
    assert isinstance(legs, list)
    assert len(legs) == 2
    assert [row["project"] for row in legs] == ["sk", "lgtv"]
    assert all(row["bmt_id"] == PROJECT_WIDE_BMT_ID for row in legs)
    assert all(row["request_scope"] == "project_wide" for row in legs)


def test_trigger_rejects_queueing_for_pr_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_file = tmp_path / "out.txt"
    matrix = json.dumps({"include": [{"project": "sk", "bmt_id": SK_BMT_FALSE_REJECT_NAMUH}]})
    _set_required_env(monkeypatch, output_file, matrix, "pr")
    monkeypatch.setenv("PR_NUMBER", "42")

    runtime_root = "gs://bucket-a"
    monkeypatch.setattr(
        gcs_module,
        "list_prefix",
        lambda _prefix: [
            f"{runtime_root}/triggers/runs/99999.json",
            f"{runtime_root}/triggers/runs/10001.json",
        ],
    )
    uploaded: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(gcs_module, "upload_json", lambda uri, payload: uploaded.append((uri, payload)))
    with pytest.raises(RuntimeError, match="pending run trigger"):
        TriggerManager.from_env().write()
    assert uploaded == []
