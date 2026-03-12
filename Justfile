# bmt-gcloud maintainer commands (run `just` for list)

default:
    @just --list

# -----------------------------------------------------------------------------
# Pre-push: tests, lint, and layout policies
# -----------------------------------------------------------------------------

test:
    uv sync
    uv run python -m pytest tests/ -v
    ruff check .
    ruff format --check .
    basedpyright
    command -v shellcheck >/dev/null 2>&1 || (echo "Install shellcheck (e.g. apt install shellcheck)" >&2; exit 1)
    shellcheck --severity=warning gcp/code/vm/*.sh .github/bmt/cli/resources/startup_entrypoint.sh tools/scripts/hooks/*.sh
    uv run python -m tools.repo.gcp_layout_policy
    uv run python -m tools.repo.repo_layout_policy

# -----------------------------------------------------------------------------
# Deploy: sync local gcp/ to bucket and verify (run after changing gcp/ code)
# -----------------------------------------------------------------------------

# Sync gcp/code to bucket (set GCS_BUCKET)
sync-gcp:
    uv run python -m tools.remote.bucket_sync_gcp

# Verify code + runtime seed sync (set GCS_BUCKET)
verify-sync:
    uv run python -m tools.remote.bucket_verify_gcp_sync
    uv run python -m tools.remote.bucket_verify_runtime_seed_sync

deploy:
    uv run python -m tools.remote.bucket_sync_gcp
    uv run python -m tools.remote.bucket_verify_gcp_sync
    uv run python -m tools.remote.bucket_verify_runtime_seed_sync

# -----------------------------------------------------------------------------
# VM and runtime observability
# -----------------------------------------------------------------------------

# Live TUI: trigger, ack, status, VM/GCS state (GCS_BUCKET, BMT_VM_NAME, GCP_ZONE)
monitor:
    uv run python -m tools.bmt.bmt_monitor

# -----------------------------------------------------------------------------
# Repo vars and Terraform export (see docs/configuration.md)
# -----------------------------------------------------------------------------

# Print Terraform-sourced repo vars (key=value)
terraform-export-vars:
    uv run python -m tools.terraform.terraform_repo_vars

# Apply Terraform-sourced repo vars to GitHub (set BMT_APPLY=1)
terraform-export-vars-apply:
    BMT_APPLY=1 uv run python -m tools.terraform.terraform_repo_vars

# Check repo vars against Terraform/contract
repo-vars-check:
    uv run python -m tools.repo.gh_repo_vars

# Apply repo vars to GitHub (BMT_APPLY=1, optional BMT_CONFIG, BMT_CONTRACT)
repo-vars-apply:
    BMT_APPLY=1 uv run python -m tools.repo.gh_repo_vars

# Print env var names used by CI, VM, tools
show-env:
    uv run python -m tools.repo.gh_show_env

# Validate repo vars match VM metadata (GCP_PROJECT, GCP_ZONE, BMT_VM_NAME)
validate-vm-vars:
    uv run python -m tools.repo.gh_validate_vm_vars

# Remove Python/uv bloat from GCS (GCS_BUCKET; default dry-run, BMT_EXECUTE=1 to run)
clean-bloat:
    uv run python -m tools.remote.bucket_clean_bloat

# Symlink gcp/bmt/dependencies/* into each project's gcp/bmt/<project>/lib/
# so libKardome.so finds them without copying. Idempotent; use --dry-run to preview.
symlink-deps:
    uv run python tools/scripts/symlink_bmt_deps.py

# -----------------------------------------------------------------------------
# Image build
# -----------------------------------------------------------------------------

# Validate Packer template only (no GCP resources created)
packer-validate:
    packer validate \
      -var 'gcp_project=dry-run' \
      -var 'gcp_zone=europe-west4-a' \
      -var 'gcs_bucket=dry-run' \
      infra/packer/bmt-runtime.pkr.hcl

# Dispatch Packer build workflow (branch defaults to current)
build-image branch="":
    #!/usr/bin/env -S bash -eu
    B="{{ branch }}"
    if [[ -z "$B" ]]; then B="$(git rev-parse --abbrev-ref HEAD)"; fi
    REPO="$(git remote get-url origin | sed 's|.*github.com[:/]\(.*\)\.git|\1|;s|.*github.com[:/]\(.*\)|\1|')"
    echo "Dispatching bmt-image-build.yml on branch: $B (repo: $REPO)"
    gh workflow run bmt-image-build.yml --repo "$REPO" --ref "$B"
