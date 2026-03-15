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
    shellcheck --severity=warning gcp/image/scripts/*.sh .github/bmt/ci/resources/startup_entrypoint.sh tools/scripts/hooks/*.sh
    uv run python -m tools.repo.gcp_layout_policy
    uv run python -m tools.repo.repo_layout_policy

# -----------------------------------------------------------------------------
# Release package: refresh .github-release/bmt/ after editing .github/bmt/ Python
# -----------------------------------------------------------------------------

# Copy .github/bmt/ (ci, config, pyproject.toml, uv.lock) into .github-release/bmt/.
# Run after editing .github/bmt/ code so the release package stays in sync.
release-package:
    rm -rf .github-release/bmt/ci .github-release/bmt/config .github-release/bmt/pyproject.toml .github-release/bmt/uv.lock
    cp -r .github/bmt/ci .github/bmt/config .github/bmt/pyproject.toml .github/bmt/uv.lock .github-release/bmt/
    @echo "Updated .github-release/bmt/ from .github/bmt/ (ci, config, pyproject.toml, uv.lock)"

# -----------------------------------------------------------------------------
# Deploy: sync local gcp/ to bucket and verify (run after changing gcp/ code)
# -----------------------------------------------------------------------------

# Sync gcp/image to bucket (GCS_BUCKET from env or gh variable get GCS_BUCKET)
sync-gcp:
    uv run python -m tools.remote.bucket_sync_gcp

# Verify code + runtime seed sync (GCS_BUCKET from env or gh variable get GCS_BUCKET)
verify-sync:
    uv run python -m tools.remote.bucket_verify_gcp_sync
    uv run python -m tools.remote.bucket_verify_runtime_seed_sync

# Pre-flight: check bucket contents and diff code/ vs gcp/image.
# Uses GCS_BUCKET from env, or from gh variable (gh variable get GCS_BUCKET).
# Saves report to .local/preflight-bucket-*.txt. See docs/preflight-bucket-remote.md.
preflight-bucket:
    tools/scripts/run_preflight_bucket.sh

deploy:
    uv run python -m tools.remote.bucket_sync_gcp
    uv run python -m tools.remote.bucket_verify_gcp_sync
    uv run python -m tools.remote.bucket_verify_runtime_seed_sync

# -----------------------------------------------------------------------------
# VM and runtime observability
# -----------------------------------------------------------------------------

# Live TUI: trigger, ack, status, VM/GCS state (GCS_BUCKET, BMT_LIVE_VM, GCP_ZONE)
monitor:
    uv run python -m tools.bmt.bmt_monitor

# -----------------------------------------------------------------------------
# Repo vars and Terraform export (see docs/configuration.md)
# -----------------------------------------------------------------------------

# Run Terraform declaratively: init + apply using GitHub repo variables (no prompts), then push outputs to GitHub.
terraform:
    uv run python -m tools.terraform.terraform_apply
    BMT_APPLY=1 uv run python -m tools.terraform.terraform_repo_vars

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

# Validate repo vars match VM metadata (GCP_PROJECT, GCP_ZONE, BMT_LIVE_VM)
validate-vm-vars:
    uv run python -m tools.repo.gh_validate_vm_vars

# Remove Python/uv bloat from GCS (GCS_BUCKET; default dry-run, BMT_EXECUTE=1 to run)
clean-bloat:
    uv run python -m tools.remote.bucket_clean_bloat

# Symlink gcp/local/dependencies/* into each project's gcp/local/<project>/lib/
# so libKardome.so finds them without copying. Idempotent; use --dry-run to preview.
symlink-deps:
    uv run python tools/scripts/symlink_bmt_deps.py

# Scaffold a new BMT project (generic template; set parsing/gate in bmt_jobs.json).
# First BMT gets a generated UUID. Usage: just add-project myproject
add-project project:
    uv run python tools/scripts/add_bmt_project.py "{{ project }}"

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

# Dispatch Packer build workflow (branch defaults to current); does not wait.
build-image branch="":
    #!/usr/bin/env -S bash -eu
    B="{{ branch }}"
    if [[ -z "$B" ]]; then B="$(git rev-parse --abbrev-ref HEAD)"; fi
    REPO="$(git remote get-url origin | sed 's|.*github.com[:/]\(.*\)\.git|\1|;s|.*github.com[:/]\(.*\)|\1|')"
    echo "Dispatching image build from branch: $B (repo: $REPO)"
    gh workflow run trigger-image-build.yml --repo "$REPO" -f branch="$B"

# Rebuild VM image using the workflow file from your current branch (via trigger-image-build), then wait. Set BMT_SKIP_IMAGE_BUILD=1 to skip.
build branch="":
    #!/usr/bin/env -S bash -eu
    if [[ -n "${BMT_SKIP_IMAGE_BUILD:-}" ]]; then
      echo "Skipping image build (BMT_SKIP_IMAGE_BUILD is set). Run 'just terraform' to apply infra only."
      exit 0
    fi
    B="{{ branch }}"
    if [[ -z "$B" ]]; then B="$(git rev-parse --abbrev-ref HEAD)"; fi
    REPO="$(git remote get-url origin | sed 's|.*github.com[:/]\(.*\)\.git|\1|;s|.*github.com[:/]\(.*\)|\1|')"
    echo "Dispatching image build from branch: $B (repo: $REPO)"
    if ! gh workflow run trigger-image-build.yml --repo "$REPO" -f branch="$B" 2>&1; then
      echo ""
      echo "::warning::Trigger workflow (trigger-image-build.yml) must exist on the repo's *default* branch. Merge it once, or run: BMT_SKIP_IMAGE_BUILD=1 just build-terraform"
      exit 1
    fi
    echo "Waiting for image build to complete..."
    sleep 5
    RUN_ID="$(gh run list --workflow=trigger-image-build.yml --repo "$REPO" --limit 1 --json databaseId -q '.[0].databaseId')"
    gh run watch "$RUN_ID" --repo "$REPO" --exit-status

# Rebuild image then Terraform (init + apply + export). Use after image or infra changes.
# If the image-build workflow is not on the default branch, use: BMT_SKIP_IMAGE_BUILD=1 just build-terraform
build-terraform branch="":
    just build "{{ branch }}"
    just terraform
