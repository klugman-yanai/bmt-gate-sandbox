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
# Bucket: deploy and preflight (GCS_BUCKET from env or gh variable)
# -----------------------------------------------------------------------------

# Sync gcp/image to bucket and verify code + runtime seed. Run after changing gcp/ code.
deploy:
    uv run python -m tools.remote.bucket_sync_gcp
    uv run python -m tools.remote.bucket_verify_gcp_sync
    uv run python -m tools.remote.bucket_verify_runtime_seed_sync

# Pre-flight: bucket contents and diff code/ vs gcp/image. Report in .local/preflight-bucket-*.txt
preflight:
    tools/scripts/run_preflight_bucket.sh

# -----------------------------------------------------------------------------
# VM and runtime observability
# -----------------------------------------------------------------------------

# Live TUI: trigger, ack, status, VM/GCS state (GCS_BUCKET, BMT_LIVE_VM, GCP_ZONE)
monitor:
    uv run python -m tools.bmt.bmt_monitor

# -----------------------------------------------------------------------------
# Repo vars, validation, Terraform (see docs/configuration.md)
# -----------------------------------------------------------------------------

# Terraform: preflight, apply, push vars. Default quiet; use -v/--verbose for full output.
# E.g. just terraform, just terraform --verbose, just terraform import-topics
terraform arg1="" arg2="":
    #!/usr/bin/env -S bash -eu
    VERBOSE=""
    [[ "{{arg1}}" == "--verbose" || "{{arg1}}" == "-v" || "{{arg2}}" == "--verbose" || "{{arg2}}" == "-v" ]] && VERBOSE="--verbose"
    [[ "{{arg1}}" == "import-topics" || "{{arg2}}" == "import-topics" ]] && uv run python -m tools.terraform.terraform_import_topics $VERBOSE
    uv run python -m tools.terraform.terraform_preflight $VERBOSE
    uv run python -m tools.terraform.terraform_apply $VERBOSE

# Check repo vars vs Terraform/contract and vs VM metadata (run both together).
validate:
    uv run python -m tools.repo.gh_repo_vars
    uv run python -m tools.repo.gh_validate_vm_vars

# Print env var names used by CI, VM, tools
show-env:
    uv run python -m tools.repo.gh_show_env

# Remove Python/uv bloat from GCS (dry-run by default). Usage: just clean-bloat | just clean-bloat execute
clean-bloat execute="":
    #!/usr/bin/env -S bash -eu
    EXEC_ARG=""
    [[ "{{execute}}" == "execute" || "{{execute}}" == "--execute" ]] && EXEC_ARG="--execute"
    uv run python -m tools.remote.bucket_clean_bloat $EXEC_ARG

# Scaffold a new BMT project. Usage: just add-project myproject
add-project project:
    uv run python tools/scripts/add_bmt_project.py "{{ project }}"

# -----------------------------------------------------------------------------
# Run workflows locally (act). Use .env for vars; required for handoff.
# Usage: just act | just act handoff | just act trigger | just act <job> (e.g. just act prepare-builds)
# -----------------------------------------------------------------------------
act which="":
    #!/usr/bin/env -S bash -eu
    VAR_ARG=""
    [[ -f .env ]] && VAR_ARG="--var-file .env"
    W=".github/workflows/build-and-test.yml"
    case "{{ which }}" in
      handoff)
        act workflow_dispatch -W .github/workflows/bmt-handoff.yml \
          -i ci_run_id=$${GITHUB_RUN_ID:-local123} \
          -i head_sha="$(git rev-parse HEAD)" \
          -i head_branch="$(git branch --show-current)" \
          -i head_event=push \
          -i pr_number= \
          $VAR_ARG
        ;;
      trigger)
        act pull_request -W .github/workflows/trigger-ci.yml -e .github/workflows/events/pull_request.json $VAR_ARG
        ;;
      "")
        act workflow_dispatch -W "$W" $VAR_ARG
        ;;
      *)
        act workflow_dispatch -W "$W" -j "{{ which }}" $VAR_ARG
        ;;
    esac

# -----------------------------------------------------------------------------
# Image build then Terraform. Usage: just build | just build no_wait=1 | just build skip_image=1
# - default: validate Packer, dispatch image build, wait, then run terraform.
# - no_wait=1: dispatch image build and return (no wait, no terraform).
# - skip_image=1: skip image build, run terraform only.
# -----------------------------------------------------------------------------
# Validate Packer template only (no GCP). Also run automatically at start of 'just build'.
packer-validate:
    packer validate \
      -var 'gcp_project=dry-run' \
      -var 'gcp_zone=europe-west4-a' \
      -var 'gcs_bucket=dry-run' \
      infra/packer/bmt-runtime.pkr.hcl

build branch="" no_wait="" skip_image="":
    #!/usr/bin/env -S bash -eu
    B="{{ branch }}"
    [[ -z "$B" ]] && B="$(git rev-parse --abbrev-ref HEAD)"
    REPO="$(git remote get-url origin | sed 's|.*github.com[:/]\(.*\)\.git|\1|;s|.*github.com[:/]\(.*\)|\1|')"

    do_image=1
    [[ "{{ skip_image }}" == "1" || "{{ skip_image }}" == "true" ]] && do_image=0
    run_terraform=1
    [[ "{{ no_wait }}" == "1" || "{{ no_wait }}" == "true" ]] && run_terraform=0

    if [[ "{{ no_wait }}" == "1" || "{{ no_wait }}" == "true" ]]; then
      if [[ $do_image -eq 1 ]]; then
        echo "Dispatching image build from branch: $B (repo: $REPO)"
        gh workflow run trigger-image-build.yml --repo "$REPO" -f branch="$B"
      fi
      exit 0
    fi

    if [[ $do_image -eq 1 ]]; then
      packer validate \
        -var 'gcp_project=dry-run' \
        -var 'gcp_zone=europe-west4-a' \
        -var 'gcs_bucket=dry-run' \
        infra/packer/bmt-runtime.pkr.hcl
      echo "Dispatching image build from branch: $B (repo: $REPO)"
      if ! gh workflow run trigger-image-build.yml --repo "$REPO" -f branch="$B" 2>&1; then
        echo "::warning::Trigger workflow must exist on default branch. Use 'just build skip_image=1' to run terraform only."
        exit 1
      fi
      echo "Waiting for image build to complete..."
      sleep 5
      RUN_ID="$(gh run list --workflow=trigger-image-build.yml --repo "$REPO" --limit 1 --json databaseId -q '.[0].databaseId')"
      gh run watch "$RUN_ID" --repo "$REPO" --exit-status
    fi

    if [[ $run_terraform -eq 1 ]]; then
      uv run python -m tools.terraform.terraform_preflight
      uv run python -m tools.terraform.terraform_apply
    fi
