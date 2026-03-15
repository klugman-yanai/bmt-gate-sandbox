#!/usr/bin/env python3
"""Import existing Pub/Sub topics into Terraform state (fix 409 "already exists").

Run when bmt-triggers / bmt-triggers-dlq exist in GCP but are not in state.
Then run: just terraform
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.terraform.terraform_apply import (
    BACKEND_PREFIX,
    CONFIG_FILENAME,
    _load_config,
    _terraform_dir,
)


def main() -> int:
    tf_dir = _terraform_dir()
    if not tf_dir.is_dir():
        print(f"::error::Terraform dir not found: {tf_dir}", file=sys.stderr)
        return 1
    try:
        config = _load_config()
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1

    project = str(config["gcp_project"]).strip()
    bucket = str(config["gcs_bucket"]).strip()
    tf_dir_str = str(tf_dir)
    var_file = tf_dir / CONFIG_FILENAME

    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    init_cmd = [
        "terraform", "-chdir=" + tf_dir_str,
        "init", "-reconfigure",
        "-backend-config=bucket=" + bucket,
        "-backend-config=prefix=" + BACKEND_PREFIX,
    ]
    if not verbose:
        r = subprocess.run(init_cmd, capture_output=True, text=True, check=False)
        if r.returncode != 0:
            print(r.stderr or r.stdout or "init failed", file=sys.stderr)
            return 1
    elif subprocess.run(init_cmd, check=False).returncode != 0:
        return 1

    imports = [
        ("google_pubsub_topic.bmt_triggers", f"projects/{project}/topics/bmt-triggers"),
        ("google_pubsub_topic.bmt_triggers_dlq", f"projects/{project}/topics/bmt-triggers-dlq"),
    ]
    var_file_flag = "-var-file=" + str(var_file)
    for res, id in imports:
        r = subprocess.run(
            ["terraform", "-chdir=" + tf_dir_str, "import", "-input=false", var_file_flag, res, id],
            check=False,
        )
        if r.returncode != 0:
            print(f"::error::Import failed: {res}", file=sys.stderr)
            return 1
    if verbose:
        print("Imported topics. Run: just terraform")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
