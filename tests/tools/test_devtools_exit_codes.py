from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _run_script(script: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, script, *args],
        check=False,
        capture_output=True,
        text=True,
        env=run_env,
    )


def test_bucket_sync_runtime_seed_exit_code_on_missing_src(tmp_path: Path) -> None:
    missing = tmp_path / "missing-src"
    proc = _run_script(
        "tools/remote/bucket_sync_runtime_seed.py",
        env={"GCS_BUCKET": "dummy", "BMT_SRC_DIR": str(missing)},
    )

    assert proc.returncode == 1
    assert "Missing source directory" in (proc.stdout + proc.stderr)
