#!/usr/bin/env python3
"""Roll back a GitHub repo to the previous/blue BMT VM by setting BMT_LIVE_VM.

Required env: TARGET_REPO, BMT_ROLLBACK_VM_NAME (or BMT_LIVE_VM). If BMT_LIVE_VM ends with -green,
rollback defaults to <base>-blue.
"""

from __future__ import annotations

import os
import subprocess


def main() -> int:
    target_repo = os.environ.get("TARGET_REPO", "").strip()
    current_vm = os.environ.get("BMT_LIVE_VM", "").strip()
    rollback_vm = os.environ.get("BMT_ROLLBACK_VM_NAME", "").strip()
    if not rollback_vm and current_vm and current_vm.endswith("-green"):
        rollback_vm = f"{current_vm.removesuffix('-green')}-blue"
    if not rollback_vm:
        rollback_vm = current_vm

    if not target_repo or not rollback_vm:
        return 1

    r = subprocess.run(["which", "gh"], capture_output=True, check=False)
    if r.returncode != 0:
        return 1

    r = subprocess.run(
        ["gh", "variable", "get", "BMT_LIVE_VM", "-R", target_repo, "--json", "value", "-q", ".value"],
        capture_output=True,
        text=True,
        check=False,
    )
    current_vm = (r.stdout or "").strip()

    r = subprocess.run(
        ["gh", "variable", "set", "BMT_LIVE_VM", "--repo", target_repo, "--body", rollback_vm],
        check=False,
    )
    if r.returncode != 0:
        return 1
    r = subprocess.run(
        ["gh", "variable", "get", "BMT_LIVE_VM", "-R", target_repo, "--json", "value", "-q", ".value"],
        capture_output=True,
        text=True,
        check=False,
    )
    (r.stdout or "").strip()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
