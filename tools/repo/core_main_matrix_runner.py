from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from pathlib import Path

from tools.shared.core_main_ci_matrix import classify_build_presets, iter_all_matrix_entries, load_presets


def _count_warning_error_lines(log_text: str) -> tuple[int, int]:
    return log_text.count("warning:"), log_text.count("error:")


def _configure_argv(configure: str, build: str) -> list[str]:
    pair = f"{configure}-{build}"
    if "webos" in pair.lower():
        return [
            "cmake",
            "--preset",
            configure,
            "-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY",
            "-DCMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF",
        ]
    return ["cmake", "--preset", configure]


def _run(argv: list[str], *, cwd: Path) -> int:
    print("+ " + " ".join(argv), flush=True)
    return subprocess.run(argv, cwd=cwd, check=False).returncode


def run_matrix(
    core_main: Path,
    *,
    build: bool,
    strict_only: bool,
    max_builds: int | None,
) -> int:
    doc = load_presets(core_main)
    rb, rnb, nr = classify_build_presets(doc, core_main)
    entries = iter_all_matrix_entries(rb, rnb, nr)
    if strict_only:
        entries = [e for e in entries if not e["soft_fail"]]
    if max_builds is not None:
        entries = entries[:max_builds]

    print(
        f"Matrix: release_bmt={len(rb)} release_no_bmt={len(rnb)} nonrelease={len(nr)} "
        f"→ running {len(entries)} entries (strict_only={strict_only})",
        flush=True,
    )
    if not build:
        for e in entries:
            print(f"  {e['short']}\tconfigure={e['configure']}\tbuild={e['build']}\tsoft_fail={e['soft_fail']}")
        return 0

    strict_failures = 0
    for e in entries:
        soft = bool(e["soft_fail"])
        label = e["short"]
        cfg = str(e["configure"])
        bpreset = str(e["build"])
        argv_cfg = _configure_argv(cfg, bpreset)
        rc = _run(argv_cfg, cwd=core_main)
        if rc != 0:
            msg = f"configure failed ({rc}): {label}"
            if soft:
                print(f"WARNING (soft_fail): {msg}", file=sys.stderr, flush=True)
            else:
                print(f"ERROR: {msg}", file=sys.stderr, flush=True)
                strict_failures += 1
            continue

        log_path = core_main / "build.log"
        with log_path.open("w", encoding="utf-8", errors="replace") as log_f:
            print("+ cmake --build --preset", bpreset, flush=True)
            brc = subprocess.run(
                ["cmake", "--build", "--preset", bpreset],
                cwd=core_main,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                check=False,
            ).returncode
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        warnings, errors = _count_warning_error_lines(log_text)
        with contextlib.suppress(OSError):
            log_path.unlink(missing_ok=True)

        if brc != 0:
            msg = f"build failed ({brc}): {label}"
            if soft:
                print(f"WARNING (soft_fail): {msg}", file=sys.stderr, flush=True)
            else:
                print(f"ERROR: {msg}", file=sys.stderr, flush=True)
                strict_failures += 1
            continue

        if warnings > 0 or errors > 0:
            msg = f"log check: {label} warnings={warnings} errors={errors}"
            if soft:
                print(f"WARNING (soft_fail): {msg}", file=sys.stderr, flush=True)
            else:
                print(f"ERROR: {msg}", file=sys.stderr, flush=True)
                strict_failures += 1

    return 1 if strict_failures else 0


def print_matrix_json(core_main: Path) -> None:
    doc = load_presets(core_main)
    rb, rnb, nr = classify_build_presets(doc, core_main)
    print(json.dumps({"presets_release_bmt": rb, "presets_release_no_bmt": rnb, "presets_nonrelease": nr}, indent=2))


def count_entries(core_main: Path) -> tuple[int, int, int, int]:
    doc = load_presets(core_main)
    rb, rnb, nr = classify_build_presets(doc, core_main)
    return len(rb), len(rnb), len(nr), len(iter_all_matrix_entries(rb, rnb, nr))
