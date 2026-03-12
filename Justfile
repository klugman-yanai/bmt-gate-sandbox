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
sync-gcp:
    uv run python tools/bucket_sync_gcp.py

# Pull bucket content into gcp/ (requires tools/bucket_pull_gcp.py; use sync-gcp for push)
pull-gcp:
    @echo "pull-gcp not implemented; use sync-gcp to push gcp/ to bucket"

sync-runtime-seed:
    uv run python tools/bucket_sync_runtime_seed.py

verify-sync:
    uv run python tools/bucket_verify_gcp_sync.py
    uv run python tools/bucket_verify_runtime_seed_sync.py

# Single deploy entrypoint: sync gcp surface to bucket and verify
deploy:
    just sync-gcp
    just verify-sync

# Remove Python/uv bloat from GCS (dry-run by default; use --execute to delete)
clean-bloat *args:
    uv run python tools/bucket_clean_bloat.py {{ args }}

# Layout / policy
validate-layout:
    uv run python tools/gcp_layout_policy.py

validate-repo-layout:
    uv run python tools/repo_layout_policy.py

# Bucket artifact ops (safe to re-run: skip when already in sync; use --force to re-upload)
upload-runner:
    uv run python tools/bucket_upload_runner.py

upload-wavs source_dir dest_prefix="sk/inputs/false_rejects":
    uv run python tools/bucket_upload_wavs.py --source-dir {{ source_dir }} --dest-prefix {{ dest_prefix }}

validate-bucket:
    uv run python tools/bucket_validate_contract.py

# Build VM image via Packer (dispatches bmt-image-build.yml; pass branch name or defaults to current)
build-image branch="":
    #!/usr/bin/env -S bash -eu
    B="{{ branch }}"
    if [[ -z "$B" ]]; then B="$(git rev-parse --abbrev-ref HEAD)"; fi
    REPO="$(git remote get-url origin | sed 's|.*github.com[:/]\(.*\)\.git|\1|;s|.*github.com[:/]\(.*\)|\1|')"
    echo "Dispatching bmt-image-build.yml on branch: $B (repo: $REPO)"
    gh workflow run bmt-image-build.yml --repo "$REPO" --ref "$B"

# VM control (manual debug/maintenance/testing only; sync-vm-metadata: skip when in sync, use --force to re-sync)
sync-vm-metadata:
    uv run --project .github/bmt bmt sync-vm-metadata

start-vm *args:
    uv run --project .github/bmt bmt start-vm --allow-manual-start {{ args }}

# Default matches .github/bmt/cli/shared/defaults.py DEFAULT_HANDSHAKE_TIMEOUT_SEC
wait-handshake workflow_run_id timeout_sec="420":
    #!/usr/bin/env -S bash -eu
    export GCS_BUCKET="${GCS_BUCKET:?Set GCS_BUCKET}"
    export GITHUB_RUN_ID="{{ workflow_run_id }}"
    export GITHUB_OUTPUT="${PWD}/.local/wait-handshake.out"
    export BMT_HANDSHAKE_TIMEOUT_SEC="{{ timeout_sec }}"
    export GCP_PROJECT="${GCP_PROJECT:-}"
    export GCP_ZONE="${GCP_ZONE:-}"
    export BMT_VM_NAME="${BMT_VM_NAME:-}"
    mkdir -p .local
    uv run --project .github/bmt bmt wait-handshake

# Runtime observability
monitor *args:
    uv run python tools/bmt_monitor.py {{ args }}

gcs-trigger run_id:
    #!/usr/bin/env -S bash -eu
    GCS_BUCKET="$(gh variable get GCS_BUCKET)"
    RID="{{ run_id }}"
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
    just gcs-trigger {{ run_id }}
    echo ""
    echo "=== VM serial (last 2KB) ==="
    VM="$(gh variable get BMT_VM_NAME)"
    ZONE="$(gh variable get GCP_ZONE)"
    PROJECT="$(gh variable get GCP_PROJECT)"
    gcloud compute instances get-serial-port-output "$VM" --zone="$ZONE" --project="$PROJECT" 2>/dev/null | tail -c 2048 || echo "(failed - check VM name/zone/project)"

# Full production CI sequence locally (sync → matrix → trigger → sync-vm-metadata → start-vm → wait-handshake).
# Requires: GCS_BUCKET, GCP_PROJECT, GCP_ZONE, BMT_VM_NAME (and gcloud auth). Optional: BMT_PUBSUB_TOPIC for Pub/Sub.

# Run from repo root. Saves run id to .local/prod-ci-run-id.txt for just gcs-trigger / just wait-handshake.
prod-ci-local:
    #!/usr/bin/env -S bash -eu
    export GCS_BUCKET="${GCS_BUCKET:?Set GCS_BUCKET}"
    export GCP_PROJECT="${GCP_PROJECT:-$(gh variable get GCP_PROJECT 2>/dev/null)}"
    export GCP_ZONE="${GCP_ZONE:-$(gh variable get GCP_ZONE 2>/dev/null)}"
    export BMT_VM_NAME="${BMT_VM_NAME:-$(gh variable get BMT_VM_NAME 2>/dev/null)}"
    export BMT_PUBSUB_TOPIC="${BMT_PUBSUB_TOPIC:-$(gh variable get BMT_PUBSUB_TOPIC 2>/dev/null || true)}"
    mkdir -p .local
    just sync-gcp
    just verify-sync
    export GITHUB_OUTPUT="$(pwd)/.local/prod-ci-matrix.out"
    BMT_CONFIG_ROOT=gcp/code uv run --project .github/bmt bmt matrix
    RUN_ID="local-$(date +%s)"
    echo "$RUN_ID" > .local/prod-ci-run-id.txt
    export GITHUB_RUN_ID="$RUN_ID"
    export GITHUB_OUTPUT="$(pwd)/.local/prod-ci-trigger.out"
    export FILTERED_MATRIX_JSON="$(grep '^matrix=' .local/prod-ci-matrix.out | cut -d= -f2-)"
    export RUN_CONTEXT=dev
    export GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
    uv run --project .github/bmt bmt write-run-trigger
    just sync-vm-metadata
    BMT_ALLOW_MANUAL_VM_START=1 just start-vm
    just wait-handshake "$RUN_ID"
    echo "Run id: $RUN_ID — use: just gcs-trigger $RUN_ID  or  just monitor --run-id $RUN_ID"

# Config / environment tooling (Terraform is source of truth; repo-vars from terraform output)
terraform-export-vars:
    uv run python tools/terraform_repo_vars.py

terraform-export-vars-apply:
    uv run python tools/terraform_repo_vars.py --apply

show-env:
    uv run python tools/gh_show_env.py

diff-core-main:
    uv run python tools/diff_github_core_main.py

repo-vars-check:
    uv run python tools/gh_repo_vars.py

repo-vars-apply *args:
    uv run python tools/gh_repo_vars.py --apply {{ args }}

validate-vm-vars *args:
    uv run python tools/gh_validate_vm_vars.py {{ args }}
