from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_preflight_trigger_queue_treats_not_found_delete_as_success(tmp_path: Path) -> None:
    """
    Simulate a race where a stale trigger is listed but is deleted before we rm it.

    Expected behavior: preflight exits 0 and does not fail the workflow.
    """
    repo = _repo_root()

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    state_file = tmp_path / "state.txt"

    # Stub jq: validation should pass (exit 0).
    _write_executable(fake_bin / "jq", "#!/usr/bin/env bash\nexit 0\n")

    # Stub gcloud for the limited commands used by preflight-trigger-queue.
    # - First `storage ls` on the runs prefix returns one stale trigger.
    # - Subsequent `storage ls` calls return nothing (as if it disappeared).
    # - `storage rm` for the stale trigger returns non-zero and prints the well-known not-found message.
    gcloud_stub = f"""#!/usr/bin/env bash
set -euo pipefail

if [[ "${{1:-}}" != "storage" ]]; then
  echo "unexpected gcloud command: $*" >&2
  exit 2
fi

sub="${{2:-}}"
shift 2 || true

case "$sub" in
  ls)
    prefix="${{1:-}}"
    # First list returns a stale trigger; later lists return empty.
    if [[ "$prefix" == *"/runtime/triggers/runs/"* ]]; then
      if [[ ! -f "{state_file}" ]]; then
        echo "gs://test-bucket/runtime/triggers/runs/111.json"
        : > "{state_file}"
      fi
      exit 0
    fi
    # Count-after-cleanup calls for acks/status and other prefixes should succeed with empty output.
    exit 0
    ;;
  cat)
    # Payload doesn't matter because jq is stubbed to succeed.
    echo "{{}}"
    exit 0
    ;;
  rm)
    uri="${{1:-}}"
    if [[ "$uri" == "gs://test-bucket/runtime/triggers/runs/111.json" ]]; then
      echo "One or more URLs matched no objects." >&2
      exit 1
    fi
    # acks/status best-effort deletes: also behave as not-found.
    echo "One or more URLs matched no objects." >&2
    exit 1
    ;;
  *)
    echo "unexpected gcloud storage subcommand: $sub ($*)" >&2
    exit 2
    ;;
esac
"""
    _write_executable(fake_bin / "gcloud", gcloud_stub)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    env["GCS_BUCKET"] = "test-bucket"
    env["GITHUB_RUN_ID"] = "222"
    env["RUN_CONTEXT"] = "dev"
    env["GITHUB_OUTPUT"] = str(tmp_path / "github_output.txt")
    env["GITHUB_STEP_SUMMARY"] = str(tmp_path / "step_summary.md")

    proc = subprocess.run(
        ["bash", "packages/bmt-cli/scripts/bmt_workflow.sh", "preflight-trigger-queue"],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr

    out_text = Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8")
    assert "restart_vm=false" in out_text
    assert "stale_cleanup_count=0" in out_text

