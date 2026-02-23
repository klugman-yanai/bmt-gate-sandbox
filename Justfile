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

# Local BMT batch (no cloud; needs data/sk/inputs and runner)
run-local-bmt bmt_id="false_reject_namuh":
    python3 devtools/run_sk_bmt_batch.py \
      --bmt-id {{bmt_id}} \
      --jobs-config remote/sk/config/bmt_jobs.json \
      --runner remote/sk/runners/kardome_runner \
      --dataset-root data/sk/inputs/false_rejects \
      --workers 4

# Run manager once against GCS (set BUCKET; optional BMT_BUCKET_PREFIX)
# Usage: just run-manager-gcs my-bucket   (run_id defaults to 'test-local')
#        just run-manager-gcs my-bucket my-run-id
# Writes to snapshots/<run_id>/ under results_prefix
run-manager-gcs bucket run_id="test-local":
    #!/usr/bin/env -S bash -eu
    BUCKET="{{bucket}}"
    RUN_ID="{{run_id}}"
    uv run python remote/sk/bmt_manager.py \
      --bucket "$BUCKET" \
      --bucket-prefix "${BMT_BUCKET_PREFIX:-}" \
      --project-id sk \
      --bmt-id false_reject_namuh \
      --jobs-config remote/sk/config/bmt_jobs.json \
      --workspace-root ./local_batch \
      --run-context dev \
      --run-id "$RUN_ID" \
      --summary-out ./local_batch/manager_summary.json
    echo "Summary: ./local_batch/manager_summary.json"
    echo "GCS: gs://$BUCKET/sk/results/false_rejects/snapshots/$RUN_ID/"

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
# Print relevant env: GitHub (gh) repo variables (with defaults), gcloud config, optional VM env.
show-env:
    #!/usr/bin/env -S bash -e
    _gh_var() { local v; v=$(gh variable get "$1" 2>/dev/null) || true; if [ -n "$v" ]; then echo "  $1=$v"; else echo "  $1=(unset)"; fi; }
    _gh_var_default() { local v d; v=$(gh variable get "$1" 2>/dev/null) || true; d="$2"; if [ -n "$v" ]; then echo "  $1=$v"; elif [ -n "$d" ]; then echo "  $1=$d (default)"; else echo "  $1=(unset)"; fi; }
    _gh_var_default_empty() { local v; v=$(gh variable get "$1" 2>/dev/null) || true; if [ -n "$v" ]; then echo "  $1=$v"; else echo "  $1=\"\" (default)"; fi; }
    _gh_secret_set() { gh secret list --json name -q '.[].name' 2>/dev/null | grep -qx "$1"; }
    _env_var() { if [ -n "${!1:-}" ]; then echo "  $1=${!1}"; else echo "  $1=(unset)"; fi; }
    echo "GitHub (gh) — used by: ci.yml, start_vm, run_trigger, job_matrix, wait; VM bootstrap scripts. Unset = CI uses default below."
    if command -v gh >/dev/null 2>&1; then
      _gh_var GCS_BUCKET
      _gh_var GCP_WIF_PROVIDER
      _gh_var GCP_SA_EMAIL
      _gh_var GCP_ZONE
      _gh_var BMT_VM_NAME
      SA_EMAIL=$(gh variable get GCP_SA_EMAIL 2>/dev/null) || true
      PROJ_V=$(gh variable get GCP_PROJECT 2>/dev/null) || true
      if [ -n "$PROJ_V" ]; then echo "  GCP_PROJECT=$PROJ_V"; elif [ -n "$SA_EMAIL" ] && [[ "$SA_EMAIL" =~ @([^.]+)\.iam\.gserviceaccount\.com ]]; then echo "  GCP_PROJECT=${BASH_REMATCH[1]} (default, from SA)"; else echo "  GCP_PROJECT=(unset)"; fi
      _gh_var_default_empty BMT_BUCKET_PREFIX
      _gh_var_default_empty BMT_PROJECTS
      _gh_var_default BMT_STATUS_CONTEXT "BMT Gate"
      _gh_var_default BMT_DESCRIPTION_PENDING "BMT running on VM; status will update when complete."
      if _gh_secret_set GITHUB_STATUS_TOKEN || gh variable get GITHUB_STATUS_TOKEN >/dev/null 2>&1; then echo "  GITHUB_STATUS_TOKEN=*** (repo)"; else echo "  GITHUB_STATUS_TOKEN=(unset in repo)"; fi
    else
      echo "  (gh not available; run 'gh auth login' in repo to list GitHub vars)"
    fi
    echo ""
    echo "gcloud — used by: audit_vm_and_bucket, ssh_install, setup_vm_startup; start_vm uses gh vars, falls back to gcloud project."
    if command -v gcloud >/dev/null 2>&1; then
      echo "  project=$(gcloud config get-value project 2>/dev/null || echo '(unset)')"
      echo "  account=$(gcloud config get-value account 2>/dev/null || echo '(unset)')"
      echo "  compute/zone=$(gcloud config get-value compute/zone 2>/dev/null || echo '(unset)')"
    else
      echo "  (gcloud not available)"
    fi
    echo ""
    echo "VM env — used by: vm_watcher.py only (posts commit status). VM must be running to read."
    if command -v gcloud >/dev/null 2>&1 && command -v gh >/dev/null 2>&1; then
      VM_PROJECT=$(gh variable get GCP_PROJECT 2>/dev/null) || true
      [ -z "$VM_PROJECT" ] && [ -n "$SA_EMAIL" ] && [[ "$SA_EMAIL" =~ @([^.]+)\.iam\.gserviceaccount\.com ]] && VM_PROJECT="${BASH_REMATCH[1]}"
      [ -z "$VM_PROJECT" ] && VM_PROJECT=$(gcloud config get-value project 2>/dev/null) || true
      VM_ZONE=$(gh variable get GCP_ZONE 2>/dev/null) || true
      VM_NAME=$(gh variable get BMT_VM_NAME 2>/dev/null) || true
      if [ -n "$VM_PROJECT" ] && [ -n "$VM_ZONE" ] && [ -n "$VM_NAME" ]; then
        VM_STATUS=$(gcloud compute instances describe "$VM_NAME" --zone="$VM_ZONE" --project="$VM_PROJECT" --format='value(status)' 2>/dev/null) || true
        if [ "$VM_STATUS" = "RUNNING" ]; then
          TOKEN_STATUS=$(gcloud compute ssh "$VM_NAME" --zone="$VM_ZONE" --project="$VM_PROJECT" --command='[ -n "${GITHUB_STATUS_TOKEN:-}" ] && echo set || echo unset' 2>/dev/null) || true
          if [ "$TOKEN_STATUS" = "set" ]; then echo "  GITHUB_STATUS_TOKEN=*** (set on VM)"; elif [ -n "$TOKEN_STATUS" ]; then echo "  GITHUB_STATUS_TOKEN=(unset on VM)"; else echo "  (VM unreachable or ssh failed)"; fi
        else
          echo "  (VM $VM_NAME not RUNNING; start VM to see VM env)"
        fi
      else
        echo "  (need GCP_PROJECT/GCP_SA_EMAIL, GCP_ZONE, BMT_VM_NAME from gh to connect)"
      fi
    else
      echo "  (need gh and gcloud to read VM env)"
    fi
    echo ""
    echo "Local env — used by: sync_remote, upload_*, validate_bucket_contract, run-manager-gcs (BUCKET or GCS_BUCKET)."
    _env_var BUCKET
    _env_var GCS_BUCKET
    _env_var BMT_BUCKET_PREFIX
    EFF_BUCKET="${BUCKET:-${GCS_BUCKET:-}}"
    if [ -n "$EFF_BUCKET" ]; then
      echo "  effective bucket (devtools use this): $EFF_BUCKET"
    elif command -v gh >/dev/null 2>&1; then
      GH_BUCKET=$(gh variable get GCS_BUCKET 2>/dev/null) || true
      if [ -n "$GH_BUCKET" ]; then echo "  effective bucket: (none in shell); GitHub GCS_BUCKET=$GH_BUCKET — export GCS_BUCKET to use for devtools"; else echo "  effective bucket: (none)"; fi
    else
      echo "  effective bucket: (none — set BUCKET or GCS_BUCKET)"
    fi
