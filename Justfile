# bmt-gcloud dev tools

default:
    @just help

help:
    @printf '%s\n' \
      'Core workflow' \
      '  just pulumi                         Apply infra and sync repo vars' \
      '  just deploy                         Sync staged bucket content' \
      '  just add-project <project>          Scaffold a staged project' \
      '  just add-bmt <project> <bmt_slug>   Scaffold a staged BMT' \
      '  just publish-bmt <project> <bmt>    Validate, publish, and sync a BMT plugin' \
      '  just upload-data <project> <src>    Upload a dataset zip or WAV folder' \
      '  just mount-project <project>        Mount the live bucket view read-only' \
      '  just umount-project <project>       Unmount a project view' \
      '' \
      'Verification and image work' \
      '  just test                           Run the local verification suite' \
      '  just typecheck                      ty section-by-section (stops at first failure)' \
      '  just typecheck-section <name>     One ty section: ci | runtime | infra | tools | tests | stage' \
      '  just image                          Build and push the Cloud Run image' \
      '  just show-env                       Print the resolved repo/runtime env contract'

# -- Pre-push ---------------------------------------------------------------

# Sections run in priority order; each completes before the next. Stops at first failing section.
[group('validate')]
typecheck:
    #!/usr/bin/env bash
    set -euo pipefail
    run() { printf '\n==> ty check: %s (%s)\n' "$1" "$2"; uv run ty check "$2"; }
    run "CI" ".github/bmt"
    run "Runtime (gcp/image)" "gcp/image"
    run "Infra" "infra"
    run "Tools" "tools"
    run "Tests" "tests"
    run "Stage mirror" "gcp/stage"

[group('validate')]
typecheck-section name:
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{name}}" in
      ci) printf '\n==> ty check: CI (.github/bmt)\n'; uv run ty check .github/bmt ;;
      runtime|gcp) printf '\n==> ty check: Runtime (gcp/image)\n'; uv run ty check gcp/image ;;
      infra) printf '\n==> ty check: Infra\n'; uv run ty check infra ;;
      tools) printf '\n==> ty check: Tools\n'; uv run ty check tools ;;
      tests) printf '\n==> ty check: Tests\n'; uv run ty check tests ;;
      stage) printf '\n==> ty check: Stage mirror\n'; uv run ty check gcp/stage ;;
      *)
        printf 'Unknown section %q. Use: ci | runtime | infra | tools | tests | stage\n' "{{name}}" >&2
        exit 1
        ;;
    esac

[group('pre-push')]
test:
    uv sync
    uv run python -m pytest tests/ -v
    ruff check .
    ruff format --check .
    uv run ty check
    command -v actionlint >/dev/null 2>&1 || (echo "Install actionlint (https://github.com/rhysd/actionlint)" >&2; exit 1)
    actionlint -config-file .github/actionlint.yaml
    command -v shellcheck >/dev/null 2>&1 || (echo "Install shellcheck (e.g. apt install shellcheck)" >&2; exit 1)
    shellcheck --severity=warning tools/scripts/hooks/*.sh
    uv run python -m tools repo validate-layout

# -- Bucket ------------------------------------------------------------------

[group('bucket')]
deploy:
    uv run python -m tools bucket deploy

[private]
[group('bucket')]
preflight:
    uv run python -m tools bucket preflight

# Upload WAV dataset to projects/<project>/inputs/<dataset>/ in GCS only (datasets can be 30-40 GB).
# Archives use gcloud storage cp + Cloud Run extraction. Folders use gcloud storage rsync.
# Dataset name is auto-detected from the filename.
# Pass --local to also mirror into gcp/stage/. Example: just upload-data sk audio/sk_false_rejects.zip
[group('bucket')]
upload-data project source *args:
    uv run python -m tools bucket upload-dataset "{{ project }}" "{{ source }}" {{ args }}

[private]
[group('bucket')]
project-sync project:
    uv run python -m tools bucket project-sync "{{ project }}"

# Remove Python/uv bloat from GCS bucket; pass e.g. --execute to actually delete (default dry-run)
[private]
[group('bucket')]
clean-bloat *args:
    uv run python -m tools bucket clean-bloat {{ args }}

# -- Data access (local fetch, manifests, FUSE mounts) -----------------------

# Fetch a full dataset from GCS into gcp/stage/ for local use.
# Example: just fetch-inputs sk false_rejects
[private]
[group('bucket')]
fetch-inputs project dataset:
    gcloud storage cp -r "gs://$GCS_BUCKET/projects/{{ project }}/inputs/{{ dataset }}/" \
        "gcp/stage/projects/{{ project }}/inputs/{{ dataset }}/"

# Fetch a single file from GCS into gcp/stage/.
# Example: just fetch-wav projects/sk/inputs/false_rejects/ambient/cafe_001.wav
[private]
[group('bucket')]
fetch-wav path:
    gcloud storage cp "gs://$GCS_BUCKET/{{ path }}" "gcp/stage/{{ path }}"

# (Re-)generate dataset_manifest.json for a dataset (requires GCS_BUCKET).
# Example: just gen-manifest sk false_rejects
[private]
[group('bucket')]
gen-manifest project dataset:
    BMT_PROJECT={{ project }} BMT_DATASET={{ dataset }} uv run python -m tools.remote.gen_input_manifest

# Mount a dataset read-only via gcsfuse into gcp/mnt/<project>-inputs/ (dev QoL, opt-in).
# Requires gcsfuse. Example: just mount-data sk
[private]
[group('bucket')]
mount-data project:
    mkdir -p gcp/mnt/{{ project }}-inputs
    gcsfuse \
        --only-dir="projects/{{ project }}/inputs" \
        --file-mode=444 \
        --dir-mode=555 \
        --implicit-dirs \
        --stat-cache-ttl=300s \
        --type-cache-ttl=300s \
        --kernel-list-cache-ttl-secs=60 \
        "$GCS_BUCKET" gcp/mnt/{{ project }}-inputs

[group('bucket')]
mount-project project:
    uv run python -m tools bucket mount-project "{{ project }}"

# Unmount a gcsfuse data mount. Example: just umount-data sk
[private]
[group('bucket')]
umount-data project:
    fusermount -u gcp/mnt/{{ project }}-inputs

[group('bucket')]
umount-project project:
    uv run python -m tools bucket umount-project "{{ project }}"

# Set GCS_BUCKET GitHub repo var from Pulumi output (e.g. after it was removed)
[private]
[group('bucket')]
set-bucket-var:
    gh variable set GCS_BUCKET --body "$(cd infra/pulumi && pulumi stack output gcs_bucket)"

# -- Infrastructure ----------------------------------------------------------

# Apply GCS lifecycle rules (run once after `just pulumi`; deletes orphaned imports/ after 2d, triggers/ after 7d).
[group('infra')]
set-lifecycle:
    gcloud storage buckets update gs://$(cd infra/pulumi && pulumi stack output gcs_bucket) \
        --lifecycle-file=infra/lifecycle.json \
        --project=$(cd infra/pulumi && pulumi stack output gcp_project)

[group('infra')]
pulumi *args:
    uv run python -m tools pulumi apply {{ args }}

# Build the Cloud Run image. Pass --repo owner/name after 'build' if origin differs (e.g. just build --repo klugman-yanai/bmt-gcloud).
[private]
[group('infra')]
build *args:
    uv run python -m tools build image --branch "`git rev-parse --abbrev-ref HEAD`" {{ args }}

[private]
[group('infra')]
packer-validate:
    uv run python -m tools build packer-validate

# -- Validation & debug ------------------------------------------------------

[group('validate')]
validate:
    uv run python -m tools repo validate

# Apply repo vars from Pulumi/contract to GitHub (set BMT_PRUNE_EXTRA=1 to remove extra vars)
[private]
[group('validate')]
repo-vars-apply:
    uv run python -m tools.repo.gh_repo_vars --apply

[group('validate')]
show-env:
    uv run python -m tools repo show-env

# -- Scaffolding & release ---------------------------------------------------

[group('dev')]
add-project project:
    uv run python -m tools bmt add-project "{{ project }}"

[group('dev')]
add-bmt project bmt_slug:
    uv run python -m tools bmt add-bmt "{{ project }}" "{{ bmt_slug }}"

[group('dev')]
publish-bmt project bmt_slug:
    uv run python -m tools bmt publish-bmt "{{ project }}" "{{ bmt_slug }}"

[group('dev')]
release:
    uv run python scripts/assemble_release.py
    @echo "Deploy: rsync .github-release/ → ~/kardome/core-main/.github/"

# -- Local CI ----------------------------------------------------------------

[private]
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

# -- Docker (Cloud Run image) --------------------------------------------------

[group('docker')]
image: docker-build docker-push

# Build the BMT orchestrator container image (buildx for BuildKit/cache)
[private]
[group('docker')]
docker-build:
    docker buildx build --load -t bmt-orchestrator:latest -f gcp/image/Dockerfile .

# Run the container locally with gcp/stage bind-mounted as /mnt/runtime (FUSE simulation)
[private]
[group('docker')]
docker-run-test *args:
    docker run --rm \
        -v "$(pwd)/gcp/stage:/mnt/runtime:ro" \
        -e BMT_CONFIG=/etc/bmt/config.json \
        {{ args }} \
        bmt-orchestrator:latest

# Tag and push the image to Artifact Registry (requires gcloud auth configure-docker)
[private]
[group('docker')]
docker-push:
    #!/usr/bin/env bash
    set -euo pipefail
    PROJECT=$(cd infra/pulumi && pulumi stack output gcp_project 2>/dev/null || echo "${GCP_PROJECT:-train-kws-202311}")
    REGION="${CLOUD_RUN_REGION:-europe-west4}"
    REPO="${ARTIFACT_REGISTRY_REPO:-bmt-images}"
    IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/bmt-orchestrator:latest"
    docker tag bmt-orchestrator:latest "${IMAGE}"
    docker push "${IMAGE}"
    echo "Pushed: ${IMAGE}"
