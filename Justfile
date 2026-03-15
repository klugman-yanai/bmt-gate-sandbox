# bmt-gcloud dev tools (run `just` for list)

default:
    @just --list --unsorted

# -- Pre-push ---------------------------------------------------------------

[group('pre-push')]
test:
    uv sync
    uv run python -m pytest tests/ -v
    ruff check .
    ruff format --check .
    basedpyright
    command -v shellcheck >/dev/null 2>&1 || (echo "Install shellcheck (e.g. apt install shellcheck)" >&2; exit 1)
    shellcheck --severity=warning gcp/image/scripts/*.sh .github/bmt/ci/resources/startup_entrypoint.sh tools/scripts/hooks/*.sh
    uv run python -m tools repo validate-layout

# -- Bucket ------------------------------------------------------------------

[group('bucket')]
deploy:
    uv run python -m tools bucket deploy

[group('bucket')]
preflight:
    uv run python -m tools bucket preflight

# Upload WAV dataset to projects/<project>/inputs/<dataset>/ in GCS and gcp/remote/.
# Source can be a .zip archive or a folder. Dataset name is auto-detected from the filename.
# Example: just upload-data sk audio/sk_false_rejects.zip
[group('bucket')]
upload-data project source *args:
    uv run python -m tools bucket upload-dataset "{{ project }}" "{{ source }}" {{ args }}

# Remove Python/uv bloat from GCS bucket; pass e.g. --execute to actually delete (default dry-run)
[group('bucket')]
clean-bloat *args:
    uv run python -m tools bucket clean-bloat {{ args }}

# Set GCS_BUCKET GitHub repo var from Pulumi output (e.g. after it was removed)
[group('bucket')]
set-bucket-var:
    gh variable set GCS_BUCKET --body "$(cd infra/pulumi && pulumi stack output gcs_bucket)"

# -- Infrastructure ----------------------------------------------------------

[group('infra')]
pulumi *args:
    uv run python -m tools pulumi apply {{ args }}

# Build VM image (dispatch trigger-image-build.yml). Pass --repo owner/name after 'build' if origin differs (e.g. just build --repo klugman-yanai/bmt-gcloud).
[group('infra')]
build *args:
    uv run python -m tools build image --branch "`git rev-parse --abbrev-ref HEAD`" {{ args }}

[group('infra')]
packer-validate:
    uv run python -m tools build packer-validate

# -- Validation & debug ------------------------------------------------------

[group('validate')]
validate:
    uv run python -m tools repo validate

# Apply repo vars from Pulumi/contract to GitHub (set BMT_PRUNE_EXTRA=1 to remove extra vars)
[group('validate')]
repo-vars-apply:
    uv run python -m tools.repo.gh_repo_vars --apply

[group('validate')]
show-env:
    uv run python -m tools repo show-env

[group('validate')]
monitor:
    uv run python -m tools bmt monitor

# Fetch trigger and ack JSON from GCS for a run (requires GCS_BUCKET; see just show-env)
[group('validate')]
vm-check run_id:
    uv run python -m tools bmt vm-check {{ run_id }}

# -- Scaffolding & release ---------------------------------------------------

[group('dev')]
add-project project:
    uv run python -m tools bmt add-project "{{ project }}"

[group('dev')]
release-package:
    rm -rf .github-release/bmt/ci .github-release/bmt/config .github-release/bmt/pyproject.toml .github-release/bmt/uv.lock
    cp -r .github/bmt/ci .github/bmt/config .github/bmt/pyproject.toml .github/bmt/uv.lock .github-release/bmt/
    @echo "Updated .github-release/bmt/ from .github/bmt/ (ci, config, pyproject.toml, uv.lock)"

# -- Local CI ----------------------------------------------------------------

[group('local-ci')]
act which="":
    #!/usr/bin/env -S bash -eu
    VAR_ARG=""
    [[ -f .env ]] && VAR_ARG="--var-file .env"
    W=".github/workflows/build-and-test.yml"
    case "{{ which }}" in
      handoff)
        act workflow_dispatch -W .github/workflows/bmt-handoff.yml \
          --input ci_run_id="$${GITHUB_RUN_ID:-local123}" \
          --input head_sha="$(git rev-parse HEAD)" \
          --input head_branch="$(git branch --show-current)" \
          --input head_event=push \
          --input pr_number= \
          $VAR_ARG
        ;;
      trigger)
        act pull_request -W .github/workflows/ops/trigger-ci.yml -e .github/workflows/events/pull_request.json $VAR_ARG
        ;;
      "")
        act workflow_dispatch -W "$W" $VAR_ARG
        ;;
      *)
        act workflow_dispatch -W "$W" -j "{{ which }}" $VAR_ARG
        ;;
    esac
