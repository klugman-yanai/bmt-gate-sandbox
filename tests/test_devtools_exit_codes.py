from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_script(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, script, *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_bucket_sync_remote_exit_code_on_missing_src(tmp_path: Path) -> None:
    missing = tmp_path / "missing-src"
    proc = _run_script("devtools/bucket_sync_remote.py", "--bucket", "dummy", "--src-dir", str(missing))

    assert proc.returncode == 1
    assert "Missing source directory" in (proc.stdout + proc.stderr)


def test_bucket_verify_remote_sync_exit_code_on_missing_src(tmp_path: Path) -> None:
    missing = tmp_path / "missing-src"
    proc = _run_script("devtools/bucket_verify_remote_sync.py", "--bucket", "dummy", "--src-dir", str(missing))

    assert proc.returncode == 1
    assert "Missing source directory" in (proc.stdout + proc.stderr)
