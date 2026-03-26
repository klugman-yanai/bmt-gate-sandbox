#!/usr/bin/env python3
"""Install VM dependencies for vm_watcher into REPO_ROOT/.venv.

Usage: install_deps.py REPO_ROOT
Or: python -m backend.scripts.install_deps REPO_ROOT
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from backend.path_utils import DEFAULT_BMT_REPO_ROOT


def _log(msg: str) -> None:
    print(f"[install_deps] {msg}", flush=True)


def _log_err(msg: str) -> None:
    print(f"[install_deps] {msg}", file=sys.stderr, flush=True)


def _compute_dep_fingerprint(repo_root: Path) -> str | None:
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    h = hashlib.sha256()
    with pyproject.open("rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main() -> int:
    if len(sys.argv) < 2:
        repo_root_str = os.environ.get("REPO_ROOT", "").strip() or DEFAULT_BMT_REPO_ROOT
        repo_root = Path(repo_root_str)
    else:
        repo_root = Path(sys.argv[1])

    if not repo_root.is_dir():
        _log_err("Usage: install_deps.py REPO_ROOT")
        return 1

    _log(f"REPO_ROOT={repo_root}")

    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        _log_err(f"::error::Missing pyproject.toml at {pyproject}; cannot install dependencies.")
        return 1

    venv = repo_root / ".venv"
    dep_stamp = venv / ".bmt_dep_fingerprint"

    python3_bin = subprocess.run(
        ["which", "python3"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip() if sys.platform != "win32" else None
    if not python3_bin or not os.path.isfile(python3_bin) or not os.access(python3_bin, os.X_OK):
        _log_err("::error::python3 not found; cannot install dependencies.")
        return 1

    if not venv.is_dir():
        _log(f"Creating venv at {venv}")
        subprocess.run([python3_bin, "-m", "venv", str(venv)], check=True)

    pip = venv / "bin" / "pip"
    if not pip.is_file():
        _log_err("::error::venv pip not found.")
        return 1

    _log(f"Installing package (editable) with [vm] extra from {repo_root}...")
    subprocess.run([str(venv / "bin" / "python"), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)
    subprocess.run([str(pip), "install", "--quiet", "-e", f"{repo_root}[vm]"], check=True)
    _log("pip install complete.")

    fingerprint = _compute_dep_fingerprint(repo_root)
    if fingerprint:
        dep_stamp.parent.mkdir(parents=True, exist_ok=True)
        dep_stamp.write_text(fingerprint + "\n")
        _log(f"Dependency fingerprint: {fingerprint}")

    python_bin = venv / "bin" / "python"
    if python_bin.is_file() and os.access(python_bin, os.X_OK):
        r = subprocess.run(
            [
                str(python_bin), "-c",
                "import config.bmt_config; import jwt; import cryptography; import httpx; import google.cloud.storage; print('OK')",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            check=False,
        )
        if r.returncode != 0:
            _log_err("::error::Dependency import check failed; watcher would be broken. Fix pyproject or environment.")
            return 1
        _log("Import check passed.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
