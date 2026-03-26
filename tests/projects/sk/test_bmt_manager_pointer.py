"""Tests for pointer resolution and snapshot path construction in backend/projects/sk/bmt_manager.py."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import backend.projects.shared.bmt_manager_base as base
import backend.projects.sk.bmt_manager as mgr


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
        out = base._resolve_last_passing_run_id(bucket_root, results_prefix)
    assert out is None


def test_resolve_last_passing_returns_none_when_last_passing_null():
    """When current.json exists but last_passing is null, returns None."""
    bucket_root = "gs://my-bucket"
    results_prefix = "sk/results/false_rejects"
    pointer_data = {"latest": "run-123", "last_passing": None, "updated_at": "2026-02-22T10:00:00Z"}

    blob = _make_mock_blob(exists=True, text=json.dumps(pointer_data))
    with patch.object(base, "_get_gcs_client", return_value=_make_mock_client(blob)):
        out = base._resolve_last_passing_run_id(bucket_root, results_prefix)
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
        out = base._resolve_last_passing_run_id(bucket_root, results_prefix)
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


def test_dataset_local_path_used_when_set(tmp_path, monkeypatch):
    """When BMT_DATASET_LOCAL_PATH is set to a valid dir, get_inputs_root() returns it and dataset rsync is skipped."""
    monkeypatch.setenv("BMT_DATASET_LOCAL_PATH", str(tmp_path))
    rsync_calls = []

    def record_rsync(src: str, dest) -> None:
        rsync_calls.append(("rsync", src, str(dest)))
        dest_path = Path(dest)
        dest_path.mkdir(parents=True, exist_ok=True)
        if "runner" in src or "runners" in src:
            (dest_path / "kardome_runner").write_text("", encoding="utf-8")

    def fake_cp(src: str, dest) -> None:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_text("{}", encoding="utf-8")

    with (
        patch("backend.projects.sk.bmt_manager._gcloud_rsync", side_effect=record_rsync),
        patch("backend.projects.sk.bmt_manager._gcloud_cp", side_effect=fake_cp),
        patch("backend.projects.sk.bmt_manager._gcloud_ls_json", return_value=[{"name": "kardome_runner"}]),
        patch("backend.projects.sk.bmt_manager._gcs_exists", return_value=True),
        patch("backend.projects.sk.bmt_manager._gcs_object_meta", return_value={"generation": "1", "size": 0}),
    ):
        from backend.projects.sk import bmt_manager as sk_mgr

        from tools.repo.paths import DEFAULT_CONFIG_ROOT, repo_root

        root = repo_root()
        jobs_path = root / DEFAULT_CONFIG_ROOT / "projects/sk/bmt_jobs.json"
        if not jobs_path.exists():
            import pytest

            pytest.skip("jobs config not found")
        bmt_id = "4a5b6e82-a048-5c96-8734-2f64d2288378"  # false_reject_namuh UUID
        jobs_data = json.loads(jobs_path.read_text())
        bmt_cfg = jobs_data["bmts"][bmt_id]
        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        args = argparse.Namespace(
            bucket="dummy-bucket",
            project_id="sk",
            bmt_id=bmt_id,
            jobs_config=str(jobs_path),
            workspace_root=str(ws),
            run_context="ci",
            run_id="test-run-1",
            max_jobs=4,
            limit=0,
            human=False,
            summary_out=str(ws / "summary.json"),
        )
        manager = sk_mgr.SKBmtManager(args, bmt_cfg)
        manager.sync_durations_sec = {}
        manager.cache_stats = {"cache_hits": [], "cache_misses": [], "states": {}}
        manager.setup_assets()
        assert manager.get_inputs_root() == tmp_path.resolve()
        dataset_rsyncs = [c for c in rsync_calls if "false_rejects" in c[1] or "dataset" in c[1].lower()]
        assert len(dataset_rsyncs) == 0
