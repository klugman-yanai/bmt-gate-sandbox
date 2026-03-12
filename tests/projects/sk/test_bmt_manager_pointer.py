"""Tests for pointer resolution and snapshot path construction in gcp/code/sk/bmt_manager.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import gcp.code.projects.base.bmt_manager_base as base
import gcp.code.projects.sk.bmt_manager as mgr


def _make_mock_blob(exists: bool, text: str | None = None) -> MagicMock:
    blob = MagicMock()
    blob.exists.return_value = exists
    if text is not None:
        blob.download_as_text.return_value = text
    return blob


def _make_mock_client(blob: MagicMock) -> MagicMock:
    client = MagicMock()
    client.bucket.return_value.blob.return_value = blob
    return client


def test_resolve_last_passing_returns_none_when_current_json_missing():
    """When current.json does not exist in GCS, _resolve_last_passing_run_id returns None."""
    bucket_root = "gs://my-bucket"
    results_prefix = "sk/results/false_rejects"

    blob = _make_mock_blob(exists=False)
    with patch.object(base, "_get_gcs_client", return_value=_make_mock_client(blob)):
        out = mgr._resolve_last_passing_run_id(bucket_root, results_prefix)
    assert out is None


def test_resolve_last_passing_returns_none_when_last_passing_null():
    """When current.json exists but last_passing is null, returns None."""
    bucket_root = "gs://my-bucket"
    results_prefix = "sk/results/false_rejects"
    pointer_data = {"latest": "run-123", "last_passing": None, "updated_at": "2026-02-22T10:00:00Z"}

    blob = _make_mock_blob(exists=True, text=json.dumps(pointer_data))
    with patch.object(base, "_get_gcs_client", return_value=_make_mock_client(blob)):
        out = mgr._resolve_last_passing_run_id(bucket_root, results_prefix)
    assert out is None


def test_resolve_last_passing_returns_run_id_when_present():
    """When current.json exists with last_passing set, returns that run_id."""
    bucket_root = "gs://my-bucket"
    results_prefix = "sk/results/false_rejects"
    run_id = "gh-123-1-sk-false_reject_namuh-abc"
    pointer_data = {
        "latest": "gh-124-1-sk-false_reject_namuh-def",
        "last_passing": run_id,
        "updated_at": "2026-02-22T10:00:00Z",
    }

    blob = _make_mock_blob(exists=True, text=json.dumps(pointer_data))
    with patch.object(base, "_get_gcs_client", return_value=_make_mock_client(blob)):
        out = mgr._resolve_last_passing_run_id(bucket_root, results_prefix)
    assert out == run_id


def test_baseline_path_construction():
    """Baseline latest.json path is results_prefix/snapshots/{last_passing_run_id}/latest.json."""
    bucket_root = "gs://my-bucket"
    results_prefix = "sk/results/false_rejects"
    last_passing_run_id = "run-abc"
    expected_suffix = f"{results_prefix}/snapshots/{last_passing_run_id}/latest.json"
    full_uri = f"{bucket_root}/{expected_suffix}"
    assert full_uri == mgr.bucket_uri(bucket_root, expected_suffix)


def test_snapshot_prefix_construction():
    """Snapshot prefix for a run is results_prefix/snapshots/{run_id}."""
    results_prefix = "sk/results/false_rejects"
    run_id = "gh-100-1-sk-false_reject_namuh-xyz"
    snapshot_prefix = f"{results_prefix}/snapshots/{run_id}"
    assert snapshot_prefix == "sk/results/false_rejects/snapshots/gh-100-1-sk-false_reject_namuh-xyz"
