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
    #!/usr/bin/env -S bash -eu
    bucket="$(gh variable get GCS_BUCKET)"
    uv_tool="${BMT_UV_TOOL_PATH:-}"
    if [[ -z "$uv_tool" ]]; then
      mkdir -p .local
      if gcloud storage cp "gs://$bucket/code/_tools/uv/linux-x86_64/uv" .local/pinned-uv >/dev/null 2>&1; then
        chmod +x .local/pinned-uv 2>/dev/null || true
        uv_tool=".local/pinned-uv"
      fi
    fi
    if [[ -n "$uv_tool" ]]; then
      BMT_UV_TOOL_PATH="$uv_tool" uv run python devtools/bucket_sync_remote.py --bucket "$bucket"
    else
      uv run python devtools/bucket_sync_remote.py --bucket "$bucket"
    fi

sync-runtime-seed:
    #!/usr/bin/env -S bash -eu
    bucket="$(gh variable get GCS_BUCKET)"
    uv run python devtools/bucket_sync_runtime_seed.py --bucket "$bucket"

verify-sync:
    #!/usr/bin/env -S bash -eu
    bucket="$(gh variable get GCS_BUCKET)"
    uv run python devtools/bucket_verify_remote_sync.py --bucket "$bucket"
    uv run python devtools/bucket_verify_runtime_seed_sync.py --bucket "$bucket"

# Remove Python/uv bloat from GCS (dry-run by default; use --execute to delete)
clean-bloat *args:
    #!/usr/bin/env -S bash -eu
    bucket="$(gh variable get GCS_BUCKET)"
    uv run python devtools/bucket_clean_bloat.py --bucket "$bucket" {{args}}

# Layout / policy
validate-layout:
    uv run python devtools/remote_layout_policy.py

validate-repo-layout:
    uv run python devtools/repo_layout_policy.py

# Bucket artifact ops (safe to re-run: skip when already in sync; use --force to re-upload)
upload-runner:
    #!/usr/bin/env -S bash -eu
    bucket="$(gh variable get GCS_BUCKET)"
    GCS_BUCKET="$bucket" uv run python devtools/bucket_upload_runner.py

upload-wavs source_dir dest_prefix="sk/inputs/false_rejects":
    #!/usr/bin/env -S bash -eu
    bucket="$(gh variable get GCS_BUCKET)"
    uv run python devtools/bucket_upload_wavs.py --bucket "$bucket" --source-dir {{source_dir}} --dest-prefix {{dest_prefix}}

validate-bucket:
    #!/usr/bin/env -S bash -eu
    bucket="$(gh variable get GCS_BUCKET)"
    uv run python devtools/bucket_validate_contract.py --bucket "$bucket"

# VM control (manual debug/maintenance/testing only; sync-vm-metadata: skip when in sync, use --force to re-sync)
sync-vm-metadata:
    #!/usr/bin/env -S bash -eu
    GCS_BUCKET="$(gh variable get GCS_BUCKET)" \
    GCP_PROJECT="$(gh variable get GCP_PROJECT)" \
    GCP_ZONE="$(gh variable get GCP_ZONE)" \
    BMT_VM_NAME="$(gh variable get BMT_VM_NAME)" \
    uv run bmt sync-vm-metadata

start-vm *args:
    #!/usr/bin/env -S bash -eu
    BMT_ALLOW_MANUAL_VM_START=1 \
    GCP_PROJECT="$(gh variable get GCP_PROJECT)" \
    GCP_ZONE="$(gh variable get GCP_ZONE)" \
    BMT_VM_NAME="$(gh variable get BMT_VM_NAME)" \
    uv run bmt start-vm {{args}}

wait-handshake workflow_run_id timeout_sec="180":
    #!/usr/bin/env -S bash -eu
    GCS_BUCKET="$(gh variable get GCS_BUCKET)" \
    GCP_PROJECT="$(gh variable get GCP_PROJECT)" \
    GCP_ZONE="$(gh variable get GCP_ZONE)" \
    BMT_VM_NAME="$(gh variable get BMT_VM_NAME)" \
    GITHUB_RUN_ID="{{workflow_run_id}}" \
    BMT_HANDSHAKE_TIMEOUT_SEC="{{timeout_sec}}" \
    GITHUB_OUTPUT="${PWD}/.local/handshake-{{workflow_run_id}}.out" \
    uv run bmt wait-handshake

# Runtime observability
monitor *args:
    uv run python devtools/bmt_monitor.py {{args}}

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
    uv run python devtools/gh_show_env.py

repo-vars-check:
    uv run python devtools/gh_repo_vars.py

repo-vars-apply *args:
    uv run python devtools/gh_repo_vars.py --apply {{args}}

validate-vm-vars *args:
    #!/usr/bin/env -S bash -eu
    uv run python devtools/gh_validate_vm_vars.py \
      --vm-name "$(gh variable get BMT_VM_NAME)" \
      --zone "$(gh variable get GCP_ZONE)" \
      --project "$(gh variable get GCP_PROJECT)" \
      {{args}}
