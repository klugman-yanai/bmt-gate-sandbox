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

# Local BMT batch (no cloud; dataset_root defaults to data/{project_id}/inputs/{bmt_id})
run-local-bmt bmt_id="false_reject_namuh" project_id="sk" dataset_root="":
    #!/usr/bin/env -S bash -eu
    DS_ROOT="{{dataset_root}}"
    [ -z "$DS_ROOT" ] && DS_ROOT="data/{{project_id}}/inputs/{{bmt_id}}"
    python3 devtools/run_sk_bmt_batch.py \
      --bmt-id {{bmt_id}} \
      --jobs-config remote/{{project_id}}/config/bmt_jobs.json \
      --runner remote/{{project_id}}/runners/kardome_runner \
      --dataset-root "$DS_ROOT" \
      --workers 4

# Run manager once against GCS (set BUCKET; optional BMT_BUCKET_PREFIX)
# Usage: just run-manager-gcs my-bucket   (run_id defaults to 'test-local')
#        just run-manager-gcs my-bucket my-run-id
#        just run-manager-gcs my-bucket my-run-id sk false_reject_namuh
# Writes to snapshots/<run_id>/ under results_prefix
run-manager-gcs bucket run_id="test-local" project_id="sk" bmt_id="false_reject_namuh":
    #!/usr/bin/env -S bash -eu
    BUCKET="{{bucket}}"
    RUN_ID="{{run_id}}"
    uv run python remote/{{project_id}}/bmt_manager.py \
      --bucket "$BUCKET" \
      --bucket-prefix "${BMT_BUCKET_PREFIX:-}" \
      --project-id {{project_id}} \
      --bmt-id {{bmt_id}} \
      --jobs-config remote/{{project_id}}/config/bmt_jobs.json \
      --workspace-root ./local_batch \
      --run-context dev \
      --run-id "$RUN_ID" \
      --summary-out ./local_batch/manager_summary.json
    echo "Summary: ./local_batch/manager_summary.json"
    echo "GCS: gs://$BUCKET/{{project_id}}/results/false_rejects/snapshots/$RUN_ID/"

# Sync remote/ to GCS (set BUCKET or GCS_BUCKET; optional BMT_BUCKET_PREFIX)
sync-remote:
    python3 devtools/sync_remote_to_bucket.py

# Sync remote/ to GCS with --delete (full mirror; removes bucket objects not in local remote/)
sync-remote-delete:
    python3 devtools/sync_remote_to_bucket.py --delete

# show-env: lists env used by CI, VM, and devtools. Where each is used:
#   GitHub vars: ci.yml (workflow env), start_vm.py (GCP_*), run_trigger.py (BMT_STATUS_*, BMT_DESCRIPTION_*),
#     job_matrix.py (BMT_PROJECTS), wait_verdicts (GCS_BUCKET, BMT_BUCKET_PREFIX); VM bootstrap scripts
#     (setup_vm_startup, audit_vm_and_bucket, ssh_install, startup_example) read same vars from env.
#   GITHUB_STATUS_TOKEN: repo secret/variable; only consumed on VM by vm_watcher.py to post commit status.
#   gcloud: audit_vm_and_bucket, start_vm fallback, ssh_install, setup_vm_startup.
#   Local BUCKET/GCS_BUCKET/BMT_BUCKET_PREFIX: devtools (sync_remote, upload_*, validate_bucket_contract, bucket_env).
show-env:
    python3 devtools/show_env.py
