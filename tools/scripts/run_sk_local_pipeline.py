#!/usr/bin/env python3
"""Drive the full SK pipeline locally (plan -> tasks -> coordinator) over a curated WAV subset.

Validates the WIP tolerance flip in ``plugins/projects/sk/sk_scoring_policy.py`` and
``plugins/projects/sk/plugin.py``: a leg with at least one ok case must PASS as
``bootstrap_without_baseline``; a leg with zero ok cases must FAIL as ``no_successful_cases``.
Both legs must produce snapshot artifacts and a ``current.json`` pointer.

Stages a tmp ``stage_root`` by symlinking from ``plugins/`` and dropping a curated set of WAVs
under ``projects/sk/inputs/{false_alarms,false_rejects}``. No GCS, no GitHub: ``run_local_mode``
short-circuits both when the relevant env vars are absent.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO_ROOT / "plugins"

# Default debug-WAV source from the prior `tools/scripts/debug_copy_run_sk_wavs.py` session.
DEFAULT_LOCAL_WAV_ROOT = REPO_ROOT / "local_batch/debug_wavs/sk"

# Curated subset chosen from the prior batch:
# - lab_recording_multiple...: 1.8 GB, exited 0 (~187 s)
# - SK_WuW_..._S_60_T_Music_N_45_E_up: ~518 MB, exited -6 SIGABRT (~25 s)
# - SK_WuW_..._S_45_T_None_N_0_E_up: ~520 MB, exited -6 SIGABRT (~25 s)
DEFAULT_FALSE_ALARMS_RELS: tuple[str, ...] = (
    "false_alarms/lab_recording_multiple_speakers_short_speech_random_sources.wav",
    "false_rejects/music/SK_WuW_A_0_D_2.6_H_70_S_60_T_Music_N_45_E_up.wav",
)
DEFAULT_FALSE_REJECTS_RELS: tuple[str, ...] = ("false_rejects/quiet/SK_WuW_A_0_D_2.6_H_70_S_45_T_None_N_0_E_up.wav",)

INPUTS_SKIP_NAMES = {"dataset_manifest.json", ".keep"}


def _mirror_plugins_dir(src: Path, dst: Path, *, inputs_skip_subdir: Path | None) -> None:
    """Recursively mirror ``src`` into ``dst`` using symlinks.

    ``inputs_skip_subdir`` is the relative path (rooted at ``PLUGINS_ROOT``) of an inputs/ subdir
    that we will NOT mirror; the caller will populate it with curated WAV symlinks afterwards.
    Inside any inputs/ subdir we also drop ``dataset_manifest.json`` so the legacy executor's
    completeness check passes (we are intentionally running a subset).
    """
    dst.mkdir(parents=True, exist_ok=True)
    for entry in sorted(src.iterdir()):
        rel_to_plugins = entry.relative_to(PLUGINS_ROOT)
        if inputs_skip_subdir is not None and (
            rel_to_plugins == inputs_skip_subdir or inputs_skip_subdir in rel_to_plugins.parents
        ):
            continue
        target = dst / entry.name
        # Drop dataset_manifest.json and .keep inside any inputs/ subtree to avoid the
        # "dataset_incomplete" gate that fires when only a subset of WAVs is staged.
        if "inputs" in rel_to_plugins.parts and entry.name in INPUTS_SKIP_NAMES:
            continue
        if entry.is_dir():
            _mirror_plugins_dir(entry, target, inputs_skip_subdir=inputs_skip_subdir)
        else:
            target.symlink_to(entry.resolve())


def _build_stage_root(stage_root: Path) -> None:
    """Build ``<stage>/projects/...`` mirroring plugins/ via symlinks; leave SK inputs empty."""
    stage_root.mkdir(parents=True, exist_ok=True)
    projects_dst = stage_root / "projects"
    projects_dst.mkdir(parents=True, exist_ok=True)
    plugins_projects = PLUGINS_ROOT / "projects"
    for entry in sorted(plugins_projects.iterdir()):
        dst = projects_dst / entry.name
        if entry.name == "sk":
            # Mirror sk/ but skip both inputs subdirs; we'll populate them with curated WAVs.
            dst.mkdir(parents=True, exist_ok=True)
            for child in sorted(entry.iterdir()):
                if child.name == "inputs":
                    inputs_dst = dst / "inputs"
                    inputs_dst.mkdir(parents=True, exist_ok=True)
                    for sub in sorted(child.iterdir()):
                        if sub.is_dir() and sub.name in {"false_alarms", "false_rejects"}:
                            (inputs_dst / sub.name).mkdir(parents=True, exist_ok=True)
                        else:
                            target = inputs_dst / sub.name
                            if sub.is_dir():
                                _mirror_plugins_dir(sub, target, inputs_skip_subdir=None)
                            elif sub.name not in INPUTS_SKIP_NAMES:
                                target.symlink_to(sub.resolve())
                    continue
                target = dst / child.name
                if child.is_dir():
                    _mirror_plugins_dir(child, target, inputs_skip_subdir=None)
                else:
                    target.symlink_to(child.resolve())
        elif entry.is_dir():
            _mirror_plugins_dir(entry, dst, inputs_skip_subdir=None)
        else:
            dst.symlink_to(entry.resolve())


def _link_wavs(stage_root: Path, src_root: Path, leg: str, rels: tuple[str, ...]) -> list[Path]:
    """Symlink each ``rels`` WAV from ``src_root`` into ``<stage>/projects/sk/inputs/<leg>/``."""
    leg_dir = stage_root / "projects" / "sk" / "inputs" / leg
    leg_dir.mkdir(parents=True, exist_ok=True)
    linked: list[Path] = []
    for rel in rels:
        src = (src_root / rel).resolve()
        if not src.is_file():
            raise SystemExit(f"WAV not found: {src} (rel={rel}, src_root={src_root})")
        # Flatten name so basename is unique within the leg dir; preserve original stem.
        flat_name = Path(rel).name
        link = leg_dir / flat_name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(src)
        linked.append(link)
    return linked


def _inspect_artifacts(stage_root: Path, workflow_run_id: str) -> dict[str, Any]:
    """Walk the durable results tree (``projects/<p>/results/<slug>/``) for snapshots + pointers.

    The coordinator's ``cleanup_ephemeral_triggers`` removes ``triggers/plans/...`` and
    ``triggers/summaries/...`` after a successful publish, so we cannot rely on them for the
    post-run report. Instead, we walk every ``current.json`` under the results tree and pull
    each pointer's ``latest`` snapshot dir.
    """
    legs_report: list[dict[str, Any]] = []

    def _read(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    projects_root = stage_root / "projects"
    if projects_root.is_dir():
        for current_path in sorted(projects_root.glob("*/results/*/current.json")):
            results_root = current_path.parent
            bmt_slug = results_root.name
            project = results_root.parent.parent.name
            current = _read(current_path) or {}
            run_id = str(current.get("latest") or "")
            snap_root = results_root / "snapshots" / run_id if run_id else results_root / "snapshots" / "_missing_"
            legs_report.append(
                {
                    "project": project,
                    "bmt_slug": bmt_slug,
                    "run_id": run_id,
                    "latest_snapshot_present": (snap_root / "latest.json").is_file(),
                    "latest_snapshot": _read(snap_root / "latest.json"),
                    "ci_verdict_present": (snap_root / "ci_verdict.json").is_file(),
                    "ci_verdict": _read(snap_root / "ci_verdict.json"),
                    "case_digest_present": (snap_root / "case_digest.json").is_file(),
                    "case_digest": _read(snap_root / "case_digest.json"),
                    "current_pointer_present": True,
                    "current_pointer": current,
                }
            )

    return {"workflow_run_id": workflow_run_id, "legs": legs_report}


def _summarize_pass_fail(report: dict[str, Any]) -> dict[str, Any]:
    """Boil down the structured artifact report into one line per leg + an overall status."""
    rows: list[dict[str, Any]] = []
    every_leg_passed = True
    legs_raw = report.get("legs", [])
    legs: list[dict[str, Any]] = legs_raw if isinstance(legs_raw, list) else []
    if not legs:
        every_leg_passed = False
    for leg in legs:
        verdict_raw = leg.get("ci_verdict")
        verdict: dict[str, Any] = verdict_raw if isinstance(verdict_raw, dict) else {}
        latest_raw = leg.get("latest_snapshot")
        latest: dict[str, Any] = latest_raw if isinstance(latest_raw, dict) else {}
        metrics_raw = verdict.get("metrics")
        metrics: dict[str, Any] = metrics_raw if isinstance(metrics_raw, dict) else {}
        status = str(verdict.get("status") or latest.get("status") or "?")
        passed = bool(verdict.get("passed", False))
        if not passed:
            every_leg_passed = False
        rows.append(
            {
                "bmt_slug": leg.get("bmt_slug"),
                "run_id": leg.get("run_id"),
                "status": status,
                "passed": passed,
                "reason_code": verdict.get("reason_code") or latest.get("reason_code"),
                "case_count": metrics.get("case_count"),
                "cases_ok": metrics.get("cases_ok"),
                "cases_failed": metrics.get("cases_failed"),
                "cases_failed_ids": metrics.get("cases_failed_ids"),
                "snapshot_complete": all(
                    [
                        leg.get("latest_snapshot_present"),
                        leg.get("ci_verdict_present"),
                        leg.get("case_digest_present"),
                    ]
                ),
                "current_pointer_present": leg.get("current_pointer_present"),
            }
        )
    return {"every_leg_passed": every_leg_passed, "legs": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src-wav-root",
        type=Path,
        default=DEFAULT_LOCAL_WAV_ROOT,
        help=f"Root containing false_alarms/ and false_rejects/ trees (default: {DEFAULT_LOCAL_WAV_ROOT})",
    )
    parser.add_argument(
        "--workflow-run-id",
        type=str,
        default="local-pipeline-001",
        help="Synthetic workflow_run_id; used for plan / triggers / snapshot dir names.",
    )
    parser.add_argument(
        "--stage-root",
        type=Path,
        default=None,
        help="Override the staged tmp dir (default: <repo>/local_batch/local_pipeline/<wfid>/stage)",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Override the workspace tmp dir (default: <repo>/local_batch/local_pipeline/<wfid>/work)",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=None,
        help="Write the structured artifact report JSON here (default: <stage>/_report.json)",
    )
    parser.add_argument(
        "--keep-stage",
        action="store_true",
        help="Do not delete the stage_root after the run (useful for inspecting artifacts).",
    )
    parser.add_argument(
        "--per-case-timeout-sec",
        type=int,
        default=300,
        help="BMT_KARDOME_CASE_TIMEOUT_SEC; per-WAV runner timeout safety net (default 300).",
    )
    args = parser.parse_args()

    if not args.src_wav_root.is_dir():
        raise SystemExit(f"--src-wav-root not a directory: {args.src_wav_root}")

    base = args.stage_root or (REPO_ROOT / "local_batch/local_pipeline" / args.workflow_run_id / "stage")
    workspace = args.workspace_root or (REPO_ROOT / "local_batch/local_pipeline" / args.workflow_run_id / "work")
    if base.exists():
        shutil.rmtree(base)
    if workspace.exists():
        shutil.rmtree(workspace)
    base.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    # Park the report next to the run dir, not under stage/, so the post-run cleanup of stage/
    # cannot delete it.
    report_out = args.report_out or (base.parent / "_report.json")

    print(f"stage_root={base}")
    print(f"workspace_root={workspace}")

    _build_stage_root(base)
    fa_links = _link_wavs(base, args.src_wav_root, "false_alarms", DEFAULT_FALSE_ALARMS_RELS)
    fr_links = _link_wavs(base, args.src_wav_root, "false_rejects", DEFAULT_FALSE_REJECTS_RELS)
    print(f"staged false_alarms WAVs ({len(fa_links)}): {[p.name for p in fa_links]}")
    print(f"staged false_rejects WAVs ({len(fr_links)}): {[p.name for p in fr_links]}")

    # Strip env that would route to GitHub or GCS during the run.
    for var in (
        "GITHUB_REPOSITORY",
        "BMT_HEAD_SHA",
        "BMT_HEAD_BRANCH",
        "BMT_PR_NUMBER",
        "GCS_BUCKET",
        "BMT_WORKFLOW_EXECUTION_URL",
    ):
        os.environ.pop(var, None)
    os.environ["BMT_ACCEPTED_PROJECTS_JSON"] = json.dumps(["sk"])
    os.environ["BMT_USE_MOCK_RUNNER"] = "0"
    os.environ["BMT_KARDOME_CASE_TIMEOUT_SEC"] = str(int(args.per_case_timeout_sec))

    # Import after env is set so module-level reads see the right values.
    from runtime.entrypoint import run_local_mode

    rc = run_local_mode(
        workflow_run_id=args.workflow_run_id,
        stage_root=base,
        workspace_root=workspace,
    )
    print(f"run_local_mode exit code: {rc}")

    report = _inspect_artifacts(base, args.workflow_run_id)
    summary = _summarize_pass_fail(report)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(json.dumps({"summary": summary, "detail": report}, indent=2) + "\n", encoding="utf-8")
    print(f"\n=== summary (every_leg_passed={summary['every_leg_passed']}) ===")
    legs_rows = summary["legs"] if isinstance(summary["legs"], list) else []
    for row in legs_rows:
        print(json.dumps(row, indent=2))
    print(f"\nfull report written to: {report_out}")

    if not args.keep_stage:
        # Coordinator's cleanup_ephemeral_triggers already removed the trigger files; we keep
        # the durable snapshot tree by NOT deleting `base/projects/sk/results`. Drop the rest.
        # If the user wants everything, they can pass --keep-stage.
        for child in sorted(base.iterdir()):
            if child.name == "projects":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    # The script itself always exits 0; caller inspects summary.every_leg_passed in the report.
    return 0


if __name__ == "__main__":
    sys.exit(main())
