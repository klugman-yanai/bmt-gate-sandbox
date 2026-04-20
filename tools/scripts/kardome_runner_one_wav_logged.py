#!/usr/bin/env python3
"""Run ``kardome_runner`` once with production-style JSON (``legacy_kardome`` path rewrite).

Writes the expanded JSON next to the stdout log for diffing / parser work. Stdout+stderr
are captured in the log file (same as Cloud Run legacy mode).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from runtime.legacy_kardome import (
    _rewrite_json_paths_for_wav,
    _set_dotted,
)
from runtime.stdout_counter_parse import (
    StdoutCounterParseConfig,
    counter_pattern_from_parsing_dict,
    read_counter_from_log,
)

# #region agent log
_AGENT_DEBUG_LOG = Path("/home/yanai/dev/projects/bmt-gcloud/.cursor/debug-fef99c.log")


def _agent_dbg(
    *,
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "sessionId": "fef99c",
        "timestamp": int(time.time() * 1000),
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
    }
    try:
        with _AGENT_DEBUG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


# #endregion


def _load_plugin_cfg(manifest_path: Path) -> dict[str, object]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw = data.get("plugin_config")
    if not isinstance(raw, dict):
        raise SystemExit(f"{manifest_path}: plugin_config must be an object")
    return raw


def _stage_runner(repo_root: Path, sk_dir: Path) -> tuple[Path, Path]:
    """Return (runner_path, cleanup_tmp_dir). Copies runner + lib like integration tests."""
    tmp = Path(tempfile.mkdtemp(prefix="bmt-kardome-one-"))
    runner = tmp / "kardome_runner"
    shutil.copy2(sk_dir / "kardome_runner", runner)
    runner.chmod(0o755)
    lib_dir = tmp / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sk_dir / "libKardome.so", lib_dir / "libKardome.so")
    return runner, tmp


def _runner_env(runner_path: Path, prev_ld: str | None) -> dict[str, str]:
    env = dict(os.environ)
    root = runner_path.parent.resolve()
    lib = root / "lib"
    parts = [str(root), str(lib)] if lib.is_dir() else [str(root)]
    if prev_ld:
        parts.append(prev_ld)
    env["LD_LIBRARY_PATH"] = ":".join(parts)
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", type=Path, required=True, help="Input .wav path.")
    parser.add_argument(
        "--bmt-manifest",
        type=Path,
        required=True,
        help="e.g. plugins/projects/sk/false_alarms.json (for plugin_config).",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=None,
        help="Default: <repo>/runtime/assets/kardome_input_template.json",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="Directory for <stem>.input.json, <stem>.stdout.log, <stem>.summary.json",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=0,
        help="subprocess timeout (0 = none).",
    )
    args = parser.parse_args()

    wav_path = args.wav.expanduser().resolve()
    if not wav_path.is_file():
        raise SystemExit(f"WAV not found: {wav_path}")

    # #region agent log
    try:
        _sz = wav_path.stat().st_size
    except OSError:
        _sz = -1
    _agent_dbg(
        hypothesis_id="H3",
        location="kardome_runner_one_wav_logged.py:main",
        message="run_start",
        data={
            "wav": str(wav_path),
            "size_bytes": _sz,
            "bmt_manifest": str(args.bmt_manifest),
        },
    )
    # #endregion

    repo_root = Path(__file__).resolve().parents[2]
    template_path = args.template or (repo_root / "runtime/assets/kardome_input_template.json")
    sk_dir = repo_root / "plugins/projects/sk"

    plugin_cfg = _load_plugin_cfg(args.bmt_manifest.expanduser().resolve())
    parsing = StdoutCounterParseConfig.model_validate(plugin_cfg).model_dump(mode="python", exclude_none=True)
    counter_re = counter_pattern_from_parsing_dict(parsing)
    enable_overrides = plugin_cfg.get("enable_overrides")
    if not isinstance(enable_overrides, dict):
        enable_overrides = {}
    num_raw = plugin_cfg.get("num_source_test")
    num_source_test = int(num_raw) if isinstance(num_raw, (int, str)) else None

    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = wav_path.stem.replace(" ", "_")
    input_json_path = out_dir / f"{stem}.input.json"
    log_path = out_dir / f"{stem}.stdout.log"
    summary_path = out_dir / f"{stem}.summary.json"

    runtime_cwd = out_dir / "_runtime_cwd"
    runtime_cwd.mkdir(parents=True, exist_ok=True)
    outputs_dir = out_dir / "_outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    output_wav = outputs_dir / f"{stem}_kardome_out.wav"

    template = json.loads(template_path.read_text(encoding="utf-8"))
    cfg = copy.deepcopy(template)
    _rewrite_json_paths_for_wav(cfg, wav_path, output_wav)
    if num_source_test is not None:
        cfg["NUM_SOURCE_TEST"] = int(num_source_test)
    for dotted_key, value in enable_overrides.items():
        if isinstance(dotted_key, str):
            _set_dotted(cfg, dotted_key, value)

    input_json_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    runner_path, cleanup = _stage_runner(repo_root, sk_dir)
    prev_ld = os.environ.get("LD_LIBRARY_PATH")
    env = _runner_env(runner_path, prev_ld)
    timeout = float(args.timeout_sec) if args.timeout_sec and args.timeout_sec > 0 else None
    _t0 = time.monotonic()
    proc: subprocess.CompletedProcess[bytes] | None = None
    timed_out = False
    try:
        with log_path.open("w", encoding="utf-8") as log_stream:
            try:
                proc = subprocess.run(
                    [str(runner_path), str(input_json_path)],
                    cwd=str(runtime_cwd.resolve()),
                    env=env,
                    stdout=log_stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                proc = None
    finally:
        shutil.rmtree(cleanup, ignore_errors=True)

    _dur = round(time.monotonic() - _t0, 3)
    if proc is None:
        proc = subprocess.CompletedProcess(args=[], returncode=-1, stdout=b"", stderr=b"")
        if timed_out:
            proc.returncode = -124  # convention: timeout
    # #region agent log
    _log_sz = log_path.stat().st_size if log_path.is_file() else 0
    _tail = ""
    try:
        _raw = log_path.read_bytes()
        _tail = _raw[-400:].decode("utf-8", errors="replace")
    except OSError:
        pass
    _agent_dbg(
        hypothesis_id="H1",
        location="kardome_runner_one_wav_logged.py:after_subprocess",
        message="subprocess_finished",
        data={
            "exit_code": proc.returncode,
            "duration_sec": _dur,
            "stdout_log_bytes": _log_sz,
            "tail_has_corrupted": "corrupted size vs. prev_size" in _tail,
            "tail_has_counter_line": "Hi NAMUH counter" in _tail,
        },
    )
    # #endregion

    parsed = read_counter_from_log(log_path, counter_re)
    summary = {
        "wav": str(wav_path),
        "bmt_manifest": str(args.bmt_manifest.resolve()),
        "exit_code": proc.returncode,
        "namuh_count_parsed": parsed,
        "counter_pattern": counter_re.pattern,
        "stdout_log": str(log_path),
        "input_json": str(input_json_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    # #region agent log
    _agent_dbg(
        hypothesis_id="H2",
        location="kardome_runner_one_wav_logged.py:after_parse",
        message="parse_result",
        data={
            "namuh_count_parsed": parsed,
            "parse_failed": parsed is None,
            "exit_code": proc.returncode,
        },
    )
    # #endregion

    print(json.dumps(summary, indent=2))
    if proc.returncode != 0:
        return proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
