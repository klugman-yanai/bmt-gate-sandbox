"""Tests for project-wide request expansion in vm_watcher."""

from __future__ import annotations

import vm_watcher as watcher  # type: ignore[import-not-found]


def test_resolve_requested_legs_expands_project_wide_requests(monkeypatch):
    monkeypatch.setattr(watcher, "_gcloud_exists", lambda _uri: True)
    monkeypatch.setattr(
        watcher,
        "_load_jobs_config_from_gcs",
        lambda *_args, **_kwargs: (
            {
                "bmts": {
                    "false_reject_namuh": {"enabled": True},
                    "legacy_disabled": {"enabled": False},
                }
            },
            None,
        ),
    )

    resolved = watcher._resolve_requested_legs(
        legs_raw=[{"project": "sk", "bmt_id": "__all__", "run_id": "gh-1"}],
        code_bucket_root="gs://bucket/code",
    )

    assert len(resolved) == 2
    by_id = {row["bmt_id"]: row for row in resolved}

    assert by_id["false_reject_namuh"]["decision"] == "accepted"
    assert by_id["false_reject_namuh"]["reason"] is None

    assert by_id["legacy_disabled"]["decision"] == "rejected"
    assert by_id["legacy_disabled"]["reason"] == "bmt_disabled"

    run_ids = [str(row["run_id"]) for row in resolved]
    assert len(run_ids) == len(set(run_ids))


def test_resolve_requested_legs_keeps_explicit_bmt_mode(monkeypatch):
    monkeypatch.setattr(watcher, "_gcloud_exists", lambda _uri: True)
    monkeypatch.setattr(
        watcher,
        "_load_jobs_config_from_gcs",
        lambda *_args, **_kwargs: (
            {
                "bmts": {
                    "false_reject_namuh": {"enabled": True},
                }
            },
            None,
        ),
    )

    resolved = watcher._resolve_requested_legs(
        legs_raw=[{"project": "sk", "bmt_id": "false_reject_namuh", "run_id": "gh-1"}],
        code_bucket_root="gs://bucket/code",
    )

    assert len(resolved) == 1
    assert resolved[0]["project"] == "sk"
    assert resolved[0]["bmt_id"] == "false_reject_namuh"
    assert resolved[0]["decision"] == "accepted"
    assert resolved[0]["reason"] is None
