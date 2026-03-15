#!/usr/bin/env python3
"""Scaffold a new BMT project under gcp/image/<project>/ (generic template).

Creates:
  gcp/image/projects/<project>/bmt_manager.py
  gcp/image/projects/<project>/bmt_jobs.json

The template is shared: all projects use projects/shared/input_template.json (no per-project input_template.json).

The first BMT in bmt_jobs.json is given a generated UUID as its id.
Parsing, gate, and runner are config-driven; no project-specific defaults (e.g. no NAMUH).
Use --dry-run to print paths without writing.
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from pathlib import Path


def _repo_root() -> Path:
    root = Path(__file__).resolve().parent.parent.parent
    if not (root / "gcp" / "image").is_dir():
        raise SystemExit("Expected repo root with gcp/image/")
    return root


def _template_manager(project: str, project_class: str) -> str:
    return f'''#!/usr/bin/env python3
"""{project} project BMT manager (scaffolded generic template).

Implements base contract: paths, runner, template, and gate from bmt_jobs.json.
Parsing (score extraction from runner output) is fully config-driven via bmt_cfg["parsing"].
Override _evaluate_gate and run_file for custom gate or runner behaviour.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Any

from gcp.image.config.constants import EXECUTABLE_MODE
from gcp.image.projects.shared.bmt_manager_base import (
    BmtManagerBase,
    _gate_result,
    _gcloud_cp,
    _gcloud_rsync,
    _load_json,
    _normalize_comparison,
    _write_runner_config,
    parse_args as _base_parse_args,
)
from gcp.image.utils import _bucket_uri, _runtime_bucket_root


def _score_regex(parsing: dict[str, Any]) -> re.Pattern[str] | None:
    """Build regex from bmt_cfg parsing; return None if no pattern (caller must handle)."""
    pattern = str(parsing.get("counter_pattern", "") or parsing.get("score_pattern", "")).strip()
    if pattern:
        return re.compile(pattern)
    return None


def _score_key(parsing: dict[str, Any]) -> str:
    """Key in file result dict for the numeric score (e.g. score, counter, namuh_count)."""
    return str(parsing.get("score_key", "score")).strip() or "score"


class {project_class}(BmtManagerBase):
    """Generic BMT manager for {project}: runner + template from GCS, gate and parsing from config."""

    def __init__(self, args: argparse.Namespace, bmt_cfg: dict[str, Any]) -> None:
        super().__init__(args, bmt_cfg)
        paths = bmt_cfg.get("paths", {{}}) or {{}}
        self._dataset_prefix = str(paths.get("dataset_prefix", "{project}/inputs/default")).rstrip("/")
        runner_cfg = bmt_cfg.get("runner", {{}}) or {{}}
        self._runner_uri = _bucket_uri(
            _runtime_bucket_root(args.bucket),
            str(runner_cfg.get("uri", "{project}/runners/{project}_gcc_release/runner")).strip(),
        )
        self._inputs_root = None
        self._runner_path = None
        parsing = bmt_cfg.get("parsing", {{}}) or {{}}
        self._score_re = _score_regex(parsing)
        self._score_key = _score_key(parsing)

    def setup_assets(self) -> None:
        runtime_root = _runtime_bucket_root(self.bucket)
        staging = self.staging_dir
        staging.mkdir(parents=True, exist_ok=True)
        inputs_dir = staging / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        dataset_uri = _bucket_uri(runtime_root, f"{{self._dataset_prefix}}/")
        try:
            _gcloud_rsync(dataset_uri, inputs_dir)
        except Exception:
            pass
        self._inputs_root = inputs_dir
        runner_dir = self.run_root / "runner"
        runner_dir.mkdir(parents=True, exist_ok=True)
        runner_basename = Path(self._runner_uri).name
        runner_dest = runner_dir / runner_basename
        if not runner_dest.exists():
            _gcloud_cp(self._runner_uri, runner_dest)
        runner_dest.chmod(runner_dest.stat().st_mode | EXECUTABLE_MODE)
        self._runner_path = runner_dest

    def collect_input_files(self, inputs_root: Path) -> list[Path]:
        return sorted(inputs_root.rglob("*.wav"))

    def run_file(self, input_file: Path, inputs_root: Path) -> dict[str, Any]:
        out_dir = self.outputs_dir / input_file.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = out_dir / "config.json"
        cfg = {{"input": str(input_file), "output": str(out_dir / "out.wav")}}
        _write_runner_config(cfg_path, cfg)
        cmd = [str(self._runner_path), str(input_file), str(cfg_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(self.run_root))
        stdout = proc.stdout or ""
        score_val = 0
        if self._score_re:
            match = self._score_re.search(stdout)
            if match:
                score_val = int(match.group(1))
        result = {{
            "file": input_file.name,
            "exit_code": proc.returncode,
            "status": "ok" if proc.returncode == 0 else "failed",
            "error": (proc.stderr or "").strip(),
        }}
        result[self._score_key] = score_val
        return result

    def compute_score(self, file_results: list[dict[str, Any]]) -> float:
        if not file_results:
            return 0.0
        key = self._score_key
        total = sum(
            int(r.get(key, 0)) for r in file_results if int(r.get("exit_code", 1)) == 0
        )
        return total / len(file_results)

    def get_runner_identity(self) -> dict[str, Any]:
        return {{"name": Path(self._runner_uri).name, "source": "{project}"}}

    def _evaluate_gate(
        self,
        aggregate_score: float,
        last_score: float | None,
        failed_count: int,
        file_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Baseline gte/lte from bmt_cfg gate; override for custom logic."""
        gate_cfg = self.bmt_cfg.get("gate", {{}}) or {{}}
        comparison = _normalize_comparison(str(gate_cfg.get("comparison", "gte")))
        tolerance_abs = float(gate_cfg.get("tolerance_abs", 0.0) or 0.0)
        return _gate_result(
            comparison, aggregate_score, last_score, failed_count, self.run_context, tolerance_abs
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="{project} BMT manager")
    _base_parse_args(parser)
    _ = parser.add_argument("--jobs-config", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    jobs_cfg = _load_json(Path(args.jobs_config))
    bmts = jobs_cfg.get("bmts", {{}})
    bmt_cfg = bmts.get(args.bmt_id)
    if not isinstance(bmt_cfg, dict):
        raise SystemExit(2)
    if not bmt_cfg.get("enabled", True):
        raise SystemExit(2)
    manager = {project_class}(args, bmt_cfg)
    return manager.run()


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _template_bmt_jobs(project: str, bmt_id: str) -> str:
    return f'''{{
  "$schema": "../../../../schemas/bmt_jobs.schema.json",
  "_comment": "Gate and parsing are project-specific; set comparison, tolerance_abs, score_key, counter_pattern for your runner output.",
  "bmts": {{
    "{bmt_id}": {{
      "enabled": true,
      "runner": {{
        "uri": "{project}/runners/{project}_gcc_release/runner",
        "deps_prefix": ""
      }},
      "template_uri": "projects/shared/input_template.json",
      "paths": {{
        "dataset_prefix": "{project}/inputs/default",
        "outputs_prefix": "{project}/outputs/default",
        "results_prefix": "{project}/results/default",
        "logs_prefix": "{project}/results/logs/default"
      }},
      "runtime": {{
        "cache": {{ "enabled": true, "root": "./cache", "dataset_ttl_sec": 300 }}
      }},
      "gate": {{
        "comparison": "gte",
        "tolerance_abs": 0.0
      }},
      "warning_policy": {{ "bootstrap_without_baseline": true }},
      "parsing": {{
        "score_key": "score",
        "counter_pattern": ""
      }}
    }}
  }}
}}
'''


def _validate_project_name(name: str) -> None:
    if not name or not re.match(r"^[a-z][a-z0-9_]*$", name):
        raise SystemExit("Project name must be non-empty, start with a letter, and use only [a-z0-9_].")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a new BMT project under gcp/image/<project>/ (generic template)."
    )
    parser.add_argument("project", help="Project name (e.g. skyworth, myproject)")
    parser.add_argument("--dry-run", action="store_true", help="Print paths only, do not write")
    args = parser.parse_args()

    _validate_project_name(args.project)
    bmt_id = str(uuid.uuid4())

    root = _repo_root()
    code_root = root / "gcp" / "image"
    project_dir = code_root / "projects" / args.project

    if project_dir.exists() and any(project_dir.iterdir()):
        print(f"::error::Project directory already exists and is non-empty: {project_dir}", file=sys.stderr)
        raise SystemExit(1)

    project_class = "".join(w.capitalize() for w in args.project.split("_")) + "BmtManager"

    files = {
        project_dir / "bmt_manager.py": _template_manager(args.project, project_class),
        project_dir / "bmt_jobs.json": _template_bmt_jobs(args.project, bmt_id),
    }

    if args.dry_run:
        for p in sorted(files):
            print(p.relative_to(root))
        return 0

    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"Wrote {path.relative_to(root)}")

    print("\nNext steps:")
    print(f"  1. Edit gcp/image/projects/{args.project}/bmt_jobs.json (paths, gate, runner URI).")
    print("  2. Run: just sync-gcp  (with GCS_BUCKET set) to push to the bucket.")
    print(f"  3. In the app repo: add CMake preset and runner upload for project={args.project}.")
    print("  4. See docs/adding-a-new-project.md for the full checklist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
