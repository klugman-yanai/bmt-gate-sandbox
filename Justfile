# bmt-gcloud maintainer commands

# List recipes
default:
    @just --list

# Tests, lint, layout policies
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

# Sync .github-release/bmt/ from .github/bmt/
release-package:
    rm -rf .github-release/bmt/ci .github-release/bmt/config .github-release/bmt/pyproject.toml .github-release/bmt/uv.lock
    cp -r .github/bmt/ci .github/bmt/config .github/bmt/pyproject.toml .github/bmt/uv.lock .github-release/bmt/
    @echo "Updated .github-release/bmt/ from .github/bmt/ (ci, config, pyproject.toml, uv.lock)"

# Sync gcp/ to bucket and verify
deploy:
    uv run python -m tools.remote.bucket_sync_gcp
    uv run python -m tools.remote.bucket_verify_gcp_sync
    uv run python -m tools.remote.bucket_verify_runtime_seed_sync

# Bucket preflight (diff, report to .local/)
preflight:
    tools/scripts/run_preflight_bucket.sh

# Live TUI for trigger/VM/GCS
monitor:
    uv run python -m tools.bmt.bmt_monitor

# Preflight, apply, export vars (-v verbose; import-topics)
terraform arg1="" arg2="":
    #!/usr/bin/env -S bash -eu
    VERBOSE=""
    [[ "{{arg1}}" == "--verbose" || "{{arg1}}" == "-v" || "{{arg2}}" == "--verbose" || "{{arg2}}" == "-v" ]] && VERBOSE="--verbose"
    [[ "{{arg1}}" == "import-topics" || "{{arg2}}" == "import-topics" ]] && uv run python -m tools.terraform.terraform_import_topics $VERBOSE
    uv run python -m tools.terraform.terraform_preflight $VERBOSE
    uv run python -m tools.terraform.terraform_apply $VERBOSE

# Check repo vars vs Terraform and VM metadata
validate:
    uv run python -m tools.repo.gh_repo_vars
    uv run python -m tools.repo.gh_validate_vm_vars

# Print CI/VM env var names
show-env:
    uv run python -m tools.repo.gh_show_env

# Remove GCS bloat (dry-run; --execute to run)
clean-bloat arg="":
    #!/usr/bin/env -S bash -eu
    EXEC_ARG=""
    [[ "{{arg}}" == "--execute" || "{{arg}}" == "-e" ]] && EXEC_ARG="--execute"
    uv run python -m tools.remote.bucket_clean_bloat $EXEC_ARG

# Scaffold BMT project
add-project project:
    uv run python tools/scripts/add_bmt_project.py "{{ project }}"

# Run workflows locally (act; .env for vars)
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

# Validate Packer template (no GCP)
packer-validate:
    packer validate \
      -var 'gcp_project=dry-run' \
      -var 'gcp_zone=europe-west4-a' \
      -var 'gcs_bucket=dry-run' \
      infra/packer/bmt-runtime.pkr.hcl

# Image build then terraform (--no-wait, --skip-image, optional branch)
build first="" second="" third="":
    #!/usr/bin/env -S bash -eu
    B=""
    [[ "{{first}}" != "" && "{{first}}" != "--no-wait" && "{{first}}" != "-w" && "{{first}}" != "--skip-image" ]] && B="{{first}}"
    [[ -z "$B" && "{{second}}" != "" && "{{second}}" != "--no-wait" && "{{second}}" != "-w" && "{{second}}" != "--skip-image" ]] && B="{{second}}"
    [[ -z "$B" && "{{third}}" != "" && "{{third}}" != "--no-wait" && "{{third}}" != "-w" && "{{third}}" != "--skip-image" ]] && B="{{third}}"
    [[ -z "$B" ]] && B="$(git rev-parse --abbrev-ref HEAD)"
    REPO="$(git remote get-url origin | sed 's|.*github.com[:/]\(.*\)\.git|\1|;s|.*github.com[:/]\(.*\)|\1|')"

    do_image=1
    [[ "{{first}}" == "--skip-image" || "{{second}}" == "--skip-image" || "{{third}}" == "--skip-image" ]] && do_image=0
    run_terraform=1
    [[ "{{first}}" == "--no-wait" || "{{first}}" == "-w" || "{{second}}" == "--no-wait" || "{{second}}" == "-w" || "{{third}}" == "--no-wait" || "{{third}}" == "-w" ]] && run_terraform=0

    if [[ $run_terraform -eq 0 ]]; then
      if [[ $do_image -eq 1 ]]; then
        echo "Dispatching image build from branch: $B (repo: $REPO)"
        gh workflow run trigger-image-build.yml --repo "$REPO" --ref "$B"
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
      if ! gh workflow run trigger-image-build.yml --repo "$REPO" --ref "$B" 2>&1; then
        echo "::warning::Trigger workflow must exist on default branch. Use 'just build --skip-image' to run terraform only."
        exit 1
      fi
      echo "Waiting for image build to complete..."
      sleep 5
      RUN_ID="$(gh run list --workflow=trigger-image-build.yml --repo "$REPO" --branch "$B" --limit 1 --json databaseId -q '.[0].databaseId')"
      gh run watch "$RUN_ID" --repo "$REPO" --exit-status
    fi

    if [[ $run_terraform -eq 1 ]]; then
      uv run python -m tools.terraform.terraform_preflight
      uv run python -m tools.terraform.terraform_apply
    fi
