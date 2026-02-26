# bmt-cloud-dev maintainer commands (run `just` for list)

default:
    @just --list

# Quality gates (no GCS/VM)
test:
    uv sync
    uv run python -m pytest tests/ -v

lint:
    uv sync
    ruff check .
    ruff format --check .
    basedpyright

# Bucket sync / verify
sync-remote:
    uv run python devtools/bucket_sync_remote.py

sync-runtime-seed:
    uv run python devtools/bucket_sync_runtime_seed.py

verify-sync:
    uv run python devtools/bucket_verify_remote_sync.py
    uv run python devtools/bucket_verify_runtime_seed_sync.py

# Layout / policy
validate-layout:
    uv run python devtools/remote_layout_policy.py

validate-repo-layout:
    uv run python devtools/repo_layout_policy.py

check-build-and-test-base:
    uv run python devtools/check_build_and_test_base_parity.py

# Bucket artifact ops
upload-runner:
    uv run python devtools/bucket_upload_runner.py

upload-wavs source_dir dest_prefix="sk/inputs/false_rejects":
    uv run python devtools/bucket_upload_wavs.py --source-dir {{source_dir}} --dest-prefix {{dest_prefix}}

validate-bucket:
    uv run python devtools/bucket_validate_contract.py

# VM control (manual debug/maintenance/testing only)
sync-vm-metadata:
    uv run python .github/scripts/ci_driver.py sync-vm-metadata

start-vm *args:
    uv run python .github/scripts/ci_driver.py start-vm --allow-manual-start {{args}}

wait-handshake workflow_run_id timeout_sec="180":
    #!/usr/bin/env -S bash -eu
    uv run python .github/scripts/ci_driver.py wait-handshake \
      --bucket "${GCS_BUCKET:?Set GCS_BUCKET}" \
      --bucket-prefix "${BMT_BUCKET_PREFIX:-}" \
      --workflow-run-id {{workflow_run_id}} \
      --timeout-sec {{timeout_sec}} \
      --project "${GCP_PROJECT:-}" \
      --zone "${GCP_ZONE:-}" \
      --instance-name "${BMT_VM_NAME:-}"

# Runtime observability
monitor *args:
    uv run python devtools/bmt_monitor.py {{args}}

gcs-trigger run_id:
    #!/usr/bin/env -S bash -eu
    GCS_BUCKET="${GCS_BUCKET:?Set GCS_BUCKET}"
    PARENT="${BMT_BUCKET_PREFIX:-}"
    PARENT="${PARENT#/}"
    PARENT="${PARENT%/}"
    RID="{{run_id}}"
    RUNTIME_PREFIX="runtime"
    [ -n "$PARENT" ] && RUNTIME_PREFIX="$PARENT/runtime"
    ROOT="gs://$GCS_BUCKET/$RUNTIME_PREFIX"
    echo "=== Trigger (workflow wrote this) ==="
    gcloud storage cat "$ROOT/triggers/runs/$RID.json" 2>/dev/null || echo "(not found or failed)"
    echo ""
    echo "=== Ack (VM should write this when it picks up trigger) ==="
    gcloud storage cat "$ROOT/triggers/acks/$RID.json" 2>/dev/null || echo "(not found - VM may not have started or watcher failed)"

vm-serial:
    #!/usr/bin/env -S bash -eu
    VM="${BMT_VM_NAME:?Set BMT_VM_NAME}"
    ZONE="${GCP_ZONE:?Set GCP_ZONE}"
    echo "VM=$VM zone=$ZONE"
    gcloud compute instances get-serial-port-output "$VM" --zone="$ZONE"

check-vm-gcs run_id:
    #!/usr/bin/env -S bash -eu
    just gcs-trigger {{run_id}}
    echo ""
    echo "=== VM serial (last 2KB) ==="
    VM="${BMT_VM_NAME:?Set BMT_VM_NAME}"
    ZONE="${GCP_ZONE:?Set GCP_ZONE}"
    gcloud compute instances get-serial-port-output "$VM" --zone="$ZONE" 2>/dev/null | tail -c 2048 || echo "(failed - check VM name/zone)"

# Config / environment tooling
show-env:
    uv run python devtools/gh_show_env.py

repo-vars-check:
    uv run python devtools/gh_repo_vars.py

repo-vars-apply *args:
    uv run python devtools/gh_repo_vars.py --apply {{args}}

validate-vm-vars *args:
    uv run python devtools/gh_validate_vm_vars.py {{args}}
