#!/usr/bin/env python3
"""Export current VM configuration to a timestamped JSON snapshot for rollback/auditing.

Required env: GCP_PROJECT, BMT_LIVE_VM.
Optional: BMT_EXPORT_DIR (default: ./backend/scripts/out). Zone is fixed (europe-west4-a).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from whenever import Instant

from backend.config.constants import DEFAULT_GCP_ZONE


def _log(msg: str) -> None:
    ts = Instant.now().format_iso(unit="second")
    print(f"[{ts}] [export_vm_spec] {msg}")


def _log_err(msg: str) -> None:
    ts = Instant.now().format_iso(unit="second")
    print(f"[{ts}] [export_vm_spec] {msg}", file=sys.stderr)


def main() -> int:
    project = os.environ.get("GCP_PROJECT", "").strip()
    zone = DEFAULT_GCP_ZONE
    vm_name = os.environ.get("BMT_LIVE_VM", "").strip()
    export_dir = os.environ.get("BMT_EXPORT_DIR", "").strip() or str(Path(__file__).resolve().parent / "out")

    if not all([project, vm_name]):
        _log_err("::error::Set GCP_PROJECT and BMT_LIVE_VM Zone is fixed (europe-west4-a).")
        return 1

    r = subprocess.run(["which", "jq"], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        _log_err("::error::jq is required for export_vm_spec.")
        return 1

    Path(export_dir).mkdir(parents=True, exist_ok=True)
    ts = Instant.now().format_iso(unit="second", basic=True)
    ts = f"{ts[:8]}T{ts[8:]}Z"
    json_path = Path(export_dir) / f"{vm_name}-spec-{ts}.json"
    summary_path = Path(export_dir) / f"{vm_name}-spec-{ts}.summary.txt"

    _log(f"Exporting VM spec for {vm_name} ({project}/{zone})...")
    r = subprocess.run(
        ["gcloud", "compute", "instances", "describe", vm_name, "--project", project, "--zone", zone, "--format=json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        _log_err(r.stderr or r.stdout or "gcloud describe failed")
        return 1
    data = json.loads(r.stdout)
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    meta = {item["key"]: item["value"] for item in data.get("metadata", {}).get("items", [])}
    machine = (data.get("machineType") or "").split("/")[-1]
    sa = (data.get("serviceAccounts") or [{}])[0].get("email", "")
    net = (data.get("networkInterfaces") or [{}])[0].get("network", "").split("/")[-1]
    sub = (data.get("networkInterfaces") or [{}])[0].get("subnetwork", "").split("/")[-1]
    tags = ",".join((data.get("tags") or {}).get("items", []))

    lines = [
        f"name={data.get('name', '')}",
        f"machineType={machine}",
        f"status={data.get('status', '')}",
        f"serviceAccount={sa}",
        f"network={net}",
        f"subnetwork={sub}",
        f"tags={tags}",
        f"gcs_bucket={meta.get('GCS_BUCKET', '')}",
        f"bmt_repo_root={meta.get('BMT_REPO_ROOT', '')}",
        f"startup_script_url_set={bool(meta.get('startup-script-url', ''))}",
    ]
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    _log(f"Wrote VM spec JSON: {json_path}")
    _log(f"Wrote VM summary : {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
