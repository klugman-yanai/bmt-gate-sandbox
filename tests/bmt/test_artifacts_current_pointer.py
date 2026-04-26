"""Tests for current.json pointer helpers used before snapshot prune."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.artifacts import prune_snapshots, read_existing_current_pointer_ids, read_existing_last_passing


def test_read_existing_current_pointer_ids_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "results" / "sk" / "demo_bmt"
    root.mkdir(parents=True)
    (root / "current.json").write_text(
        json.dumps({"latest": "run-a", "last_passing": "run-b", "updated_at": "x"}),
        encoding="utf-8",
    )
    assert read_existing_current_pointer_ids(root) == ("run-a", "run-b")


def test_read_existing_last_passing_uses_shared_reader(tmp_path: Path) -> None:
    root = tmp_path / "results" / "sk" / "demo_bmt2"
    root.mkdir(parents=True)
    (root / "current.json").write_text(
        json.dumps({"latest": "run-z", "last_passing": "run-y"}),
        encoding="utf-8",
    )
    assert read_existing_last_passing(root) == "run-y"


def test_prune_retains_prior_pointer_snapshots(tmp_path: Path) -> None:
    """Coordinator-style merge: retain snapshot dirs named in current.json even if not in the new minimal keep set."""
    root = tmp_path / "results" / "sk" / "demo_bmt3"
    snap = root / "snapshots"
    for name in ("prior-latest", "new-leg", "to-delete"):
        (snap / name).mkdir(parents=True)
    (root / "current.json").write_text(
        json.dumps({"latest": "prior-latest", "last_passing": "prior-latest"}),
        encoding="utf-8",
    )
    keep: set[str] = {"new-leg"}
    prior_latest, prior_last = read_existing_current_pointer_ids(root)
    for ref in (prior_latest, prior_last):
        if ref:
            keep.add(ref)
    prune_snapshots(results_root=root, keep_run_ids=keep)
    names = {p.name for p in snap.iterdir() if p.is_dir()}
    assert names == {"prior-latest", "new-leg"}
    assert "to-delete" not in names
