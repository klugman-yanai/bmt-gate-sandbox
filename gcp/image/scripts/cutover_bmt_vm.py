#!/usr/bin/env python3
"""Cut over a GitHub repo to a new BMT VM by updating repository variable BMT_LIVE_VM.

Required env: TARGET_REPO, BMT_GREEN_VM_NAME (or BMT_LIVE_VM for default <base>-green).
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    target_repo = os.environ.get("TARGET_REPO", "").strip()
    vm_name = os.environ.get("BMT_LIVE_VM", "").strip()
    green_vm = os.environ.get("BMT_GREEN_VM_NAME", "").strip() or (
        (f"{vm_name.removesuffix('-blue')}-green" if vm_name.endswith("-blue") else f"{vm_name}-green") if vm_name else ""
    )

    if not target_repo or not green_vm:
        print("Set TARGET_REPO and BMT_GREEN_VM_NAME (or BMT_LIVE_VM).", file=sys.stderr)
        return 1

    r = subprocess.run(["gh", "variable", "get", "BMT_LIVE_VM", "-R", target_repo, "--json", "value", "-q", ".value"],
                      capture_output=True, text=True, check=False)
    current_vm = (r.stdout or "").strip() if r.returncode == 0 else vm_name

    print(f"Cutover target repo: {target_repo}")
    print(f"Current BMT_LIVE_VM: {current_vm or '<unset>'}")
    print(f"New BMT_LIVE_VM:     {green_vm}")

    r = subprocess.run(
        ["gh", "variable", "set", "BMT_LIVE_VM", "--repo", target_repo, "--body", green_vm],
        check=False,
    )
    if r.returncode != 0:
        return 1
    r = subprocess.run(["gh", "variable", "get", "BMT_LIVE_VM", "-R", target_repo, "--json", "value", "-q", ".value"],
                      capture_output=True, text=True, check=False)
    updated = (r.stdout or "").strip()
    print(f"Updated BMT_LIVE_VM: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
