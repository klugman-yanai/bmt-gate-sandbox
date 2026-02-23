# bmt-cloud-dev — common commands (just run `just` for list)

default:
    @just --list

# Install deps and run all unit tests (no GCS/VM)
test:
    uv sync
    uv run python -m pytest tests/ -v

# Lint and type-check (see CLAUDE.md)
lint:
    uv sync
    ruff check .
    ruff format --check .
    basedpyright

# =============================================================================
# BMT Execution
# =============================================================================

# Local BMT batch (no cloud; dataset_root defaults to data/{project_id}/inputs/{bmt_id})
run-local-bmt bmt_id="false_reject_namuh" project_id="sk" dataset_root="":
    #!/usr/bin/env -S bash -eu
    DS_ROOT="{{dataset_root}}"
    [ -z "$DS_ROOT" ] && DS_ROOT="data/{{project_id}}/inputs/{{bmt_id}}"
    uv run python devtools/bmt_run_local.py \
      --bmt-id {{bmt_id}} \
      --jobs-config remote/{{project_id}}/config/bmt_jobs.json \
      --runner remote/{{project_id}}/runners/kardome_runner \
      --dataset-root "$DS_ROOT" \
      --workers 4

# Run manager once against GCS (bucket arg required; optional BMT_BUCKET_PREFIX env)
run-manager-gcs bucket run_id="test-local" project_id="sk" bmt_id="false_reject_namuh":
    #!/usr/bin/env -S bash -eu
    GCS_BUCKET_ARG="{{bucket}}"
    RUN_ID="{{run_id}}"
    uv run python remote/{{project_id}}/bmt_manager.py \
      --bucket "$GCS_BUCKET_ARG" \
      --bucket-prefix "${BMT_BUCKET_PREFIX:-}" \
      --project-id {{project_id}} \
      --bmt-id {{bmt_id}} \
      --jobs-config remote/{{project_id}}/config/bmt_jobs.json \
      --workspace-root ./local_batch \
      --run-context dev \
      --run-id "$RUN_ID" \
      --summary-out ./local_batch/manager_summary.json
    echo "Summary: ./local_batch/manager_summary.json"
    echo "GCS: gs://$GCS_BUCKET_ARG/{{project_id}}/results/false_rejects/snapshots/$RUN_ID/"

# Live TUI monitor for BMT runs (use --auto for auto-detect, --prod for production repo)
monitor *args:
    uv run python devtools/bmt_monitor.py {{args}}

# =============================================================================
# GCS Bucket Operations
# =============================================================================

# Sync remote/ to GCS (bucket from GCS_BUCKET env).
# Runtime-generated paths are excluded by default (triggers/inputs/outputs/results).
sync-remote:
    uv run python devtools/bucket_sync_remote.py

# Sync remote/ to GCS with --delete (full mirror; removes bucket objects not in local remote/)
sync-remote-delete:
    uv run python devtools/bucket_sync_remote.py --delete

# Sync remote/ including runtime-generated paths (for rare debugging only)
sync-remote-runtime:
    uv run python devtools/bucket_sync_remote.py --include-runtime-artifacts

# Upload runner binary to bucket (bucket from GCS_BUCKET env)
upload-runner:
    uv run python devtools/bucket_upload_runner.py

# Upload wav dataset to bucket (bucket from GCS_BUCKET env)
upload-wavs:
    uv run python devtools/bucket_upload_wavs.py

# Validate bucket contract (bucket from GCS_BUCKET env)
validate-bucket:
    uv run python devtools/bucket_validate_contract.py

# =============================================================================
# Debug / Utilities
# =============================================================================

# Show env vars used by CI, VM, and devtools
show-env:
    uv run python devtools/gh_show_env.py

# Check GitHub repo vars against contract + optional declarative overrides
repo-vars-check:
    uv run python devtools/gh_repo_vars.py

# Apply contract/default-backed repo vars (plus optional declarative overrides) to GitHub
repo-vars-apply *args:
    uv run python devtools/gh_repo_vars.py --apply {{args}}

# Report config variable surface and reduction opportunities
env-surface:
    uv run python devtools/env_surface_report.py

# Validate required repo vars match VM metadata (set BMT_VM_NAME, GCP_ZONE, GCP_PROJECT or pass flags)
validate-vm-vars *args:
    uv run python devtools/gh_validate_vm_vars.py {{args}}

# Fetch GitHub App permissions (requires --app-id and private key path)
gh-app-perms *args:
    uv run python devtools/gh_app_perms.py {{args}}

# Check GCS trigger and ack for a workflow run (requires GCS_BUCKET env)
# Use after handshake timeout: see if trigger was written and if VM wrote ack
gcs-trigger run_id:
    #!/usr/bin/env -S bash -eu
    GCS_BUCKET="${GCS_BUCKET:?Set GCS_BUCKET}"
    PREFIX="${BMT_BUCKET_PREFIX:-}"
    RID="{{run_id}}"
    ROOT="gs://$GCS_BUCKET"; [ -n "$PREFIX" ] && ROOT="$ROOT/$PREFIX"
    echo "=== Trigger (workflow wrote this) ==="
    gcloud storage cat "$ROOT/triggers/runs/$RID.json" 2>/dev/null || echo "(not found or failed)"
    echo ""
    echo "=== Ack (VM should write this when it picks up trigger) ==="
    gcloud storage cat "$ROOT/triggers/acks/$RID.json" 2>/dev/null || echo "(not found - VM may not have started or watcher failed)"

# Stream VM serial port output (requires BMT_VM_NAME, GCP_ZONE)
vm-serial:
    #!/usr/bin/env -S bash -eu
    VM="${BMT_VM_NAME:?Set BMT_VM_NAME}"
    ZONE="${GCP_ZONE:?Set GCP_ZONE}"
    echo "VM=$VM zone=$ZONE"
    gcloud compute instances get-serial-port-output "$VM" --zone="$ZONE"

# One-shot: show GCS trigger/ack and tail VM serial (requires run_id, BMT_VM_NAME, GCP_ZONE, GCS_BUCKET)
check-vm-gcs run_id:
    #!/usr/bin/env -S bash -eu
    just gcs-trigger {{run_id}}
    echo ""
    echo "=== VM serial (last 2KB) ==="
    VM="${BMT_VM_NAME:?Set BMT_VM_NAME}"
    ZONE="${GCP_ZONE:?Set GCP_ZONE}"
    gcloud compute instances get-serial-port-output "$VM" --zone="$ZONE" 2>/dev/null | tail -c 2048 || echo "(failed - check VM name/zone)"
