#!/usr/bin/env python3
"""Cut over a GitHub repo to a new BMT VM by updating repository variable BMT_LIVE_VM.

Required env: TARGET_REPO, BMT_GREEN_VM_NAME (or BMT_LIVE_VM for default <base>-green).
"""

from __future__ import annotations

import os
import subprocess


def main() -> int:
    target_repo = os.environ.get("TARGET_REPO", "").strip()
    vm_name = os.environ.get("BMT_LIVE_VM", "").strip()
    green_vm = os.environ.get("BMT_GREEN_VM_NAME", "").strip() or (
        (f"{vm_name.removesuffix('-blue')}-green" if vm_name.endswith("-blue") else f"{vm_name}-green")
        if vm_name
        else ""
    )

    if not target_repo or not green_vm:
        return 1

    r = subprocess.run(
        ["gh", "variable", "get", "BMT_LIVE_VM", "-R", target_repo, "--json", "value", "-q", ".value"],
        capture_output=True,
        text=True,
        check=False,
    )
    (r.stdout or "").strip() if r.returncode == 0 else vm_name

    r = subprocess.run(
        ["gh", "variable", "set", "BMT_LIVE_VM", "--repo", target_repo, "--body", green_vm],
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
