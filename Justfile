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
    uv run python -m tools.repo.gcp_layout_policy
    uv run python -m tools.repo.repo_layout_policy

# -- Bucket ------------------------------------------------------------------

[group('bucket')]
deploy:
    uv run python -m tools bucket deploy

[group('bucket')]
preflight:
    uv run python -m tools bucket preflight

[group('bucket')]
clean-bloat *args:
    uv run python -m tools bucket clean-bloat {{ args }}

# -- Infrastructure ----------------------------------------------------------

[group('infra')]
terraform *args:
    uv run python -m tools terraform apply {{ args }}

[group('infra')]
terraform-import-topics *args:
    uv run python -m tools terraform import-topics {{ args }}

# Build VM image (dispatch trigger-image-build.yml). Pass --repo owner/name after 'build' if origin is a different repo (e.g. sandbox).
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

[group('validate')]
show-env:
    uv run python -m tools repo show-env

[group('validate')]
monitor:
    uv run python -m tools bmt monitor

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
