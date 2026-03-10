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

# Bucket sync / verify (safe to re-run: skip when already in sync; use --force to re-sync)
sync-remote:
    uv run python tools/bucket_sync_remote.py

# Pull bucket content into deploy/ so local is 1:1 with bucket (code + runtime, excluding ephemeral paths)
pull-remote:
    uv run python tools/bucket_pull_remote.py

sync-runtime-seed:
    uv run python tools/bucket_sync_runtime_seed.py

verify-sync:
    uv run python tools/bucket_verify_remote_sync.py
    uv run python tools/bucket_verify_runtime_seed_sync.py

# Single deploy entrypoint: sync deploy surface to bucket and verify
deploy:
    just sync-remote
    just verify-sync

# Remove Python/uv bloat from GCS (dry-run by default; use --execute to delete)
clean-bloat *args:
    uv run python tools/bucket_clean_bloat.py {{args}}

# Layout / policy
validate-layout:
    uv run python tools/deploy_layout_policy.py

validate-repo-layout:
    uv run python tools/repo_layout_policy.py

# Bucket artifact ops (safe to re-run: skip when already in sync; use --force to re-upload)
upload-runner:
    uv run python tools/bucket_upload_runner.py

upload-wavs source_dir dest_prefix="sk/inputs/false_rejects":
    uv run python tools/bucket_upload_wavs.py --source-dir {{source_dir}} --dest-prefix {{dest_prefix}}

validate-bucket:
    uv run python tools/bucket_validate_contract.py

# VM control (manual debug/maintenance/testing only; sync-vm-metadata: skip when in sync, use --force to re-sync)
sync-vm-metadata:
    uv run --project packages/bmt-cli bmt sync-vm-metadata

start-vm *args:
    uv run --project packages/bmt-cli bmt start-vm --allow-manual-start {{args}}

wait-handshake workflow_run_id timeout_sec="180":
    #!/usr/bin/env -S bash -eu
    export GCS_BUCKET="${GCS_BUCKET:?Set GCS_BUCKET}"
    export GITHUB_RUN_ID="{{workflow_run_id}}"
    export GITHUB_OUTPUT="${PWD}/.local/wait-handshake.out"
    export BMT_HANDSHAKE_TIMEOUT_SEC="{{timeout_sec}}"
    export GCP_PROJECT="${GCP_PROJECT:-}"
    export GCP_ZONE="${GCP_ZONE:-}"
    export BMT_VM_NAME="${BMT_VM_NAME:-}"
    mkdir -p .local
    uv run --project packages/bmt-cli bmt wait-handshake

# Runtime observability
monitor *args:
    uv run python tools/bmt_monitor.py {{args}}

gcs-trigger run_id:
    #!/usr/bin/env -S bash -eu
    GCS_BUCKET="$(gh variable get GCS_BUCKET)"
    RID="{{run_id}}"
    ROOT="gs://$GCS_BUCKET/runtime"
    echo "=== Trigger (workflow wrote this) ==="
    gcloud storage cat "$ROOT/triggers/runs/$RID.json" 2>/dev/null || echo "(not found or failed)"
    echo ""
    echo "=== Ack (VM should write this when it picks up trigger) ==="
    gcloud storage cat "$ROOT/triggers/acks/$RID.json" 2>/dev/null || echo "(not found - VM may not have started or watcher failed)"

vm-serial:
    #!/usr/bin/env -S bash -eu
    VM="$(gh variable get BMT_VM_NAME)"
    ZONE="$(gh variable get GCP_ZONE)"
    PROJECT="$(gh variable get GCP_PROJECT)"
    echo "VM=$VM zone=$ZONE"
    gcloud compute instances get-serial-port-output "$VM" --zone="$ZONE" --project="$PROJECT"

check-vm-gcs run_id:
    #!/usr/bin/env -S bash -eu
    just gcs-trigger {{run_id}}
    echo ""
    echo "=== VM serial (last 2KB) ==="
    VM="$(gh variable get BMT_VM_NAME)"
    ZONE="$(gh variable get GCP_ZONE)"
    PROJECT="$(gh variable get GCP_PROJECT)"
    gcloud compute instances get-serial-port-output "$VM" --zone="$ZONE" --project="$PROJECT" 2>/dev/null | tail -c 2048 || echo "(failed - check VM name/zone/project)"

# Config / environment tooling (repo-vars-apply: skip when vars match; use --force to re-set all)
show-env:
    uv run python tools/gh_show_env.py

diff-core-main:
    uv run python tools/diff_github_core_main.py

repo-vars-check:
    uv run python tools/gh_repo_vars.py

repo-vars-apply *args:
    uv run python tools/gh_repo_vars.py --apply {{args}}

validate-vm-vars *args:
    uv run python tools/gh_validate_vm_vars.py {{args}}
