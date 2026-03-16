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

# Upload WAV dataset to projects/<project>/inputs/<dataset>/ in GCS only (datasets can be 30-40 GB).
# Source can be a .zip archive or a folder. Dataset name is auto-detected from the filename.
# Pass --local to also mirror into gcp/remote/. Example: just upload-data sk audio/sk_false_rejects.zip
[group('bucket')]
upload-data project source *args:
    uv run python -m tools bucket upload-dataset "{{ project }}" "{{ source }}" {{ args }}

# Remove Python/uv bloat from GCS bucket; pass e.g. --execute to actually delete (default dry-run)
[group('bucket')]
clean-bloat *args:
    uv run python -m tools bucket clean-bloat {{ args }}

# -- Data access (local fetch, manifests, FUSE mounts) -----------------------

# Fetch a full dataset from GCS into gcp/stage/ for local use.
# Example: just fetch-inputs sk false_rejects
[group('bucket')]
fetch-inputs project dataset:
    gcloud storage cp -r "gs://$GCS_BUCKET/projects/{{ project }}/inputs/{{ dataset }}/" \
        "gcp/stage/projects/{{ project }}/inputs/{{ dataset }}/"

# Fetch a single file from GCS into gcp/stage/.
# Example: just fetch-wav projects/sk/inputs/false_rejects/ambient/cafe_001.wav
[group('bucket')]
fetch-wav path:
    gcloud storage cp "gs://$GCS_BUCKET/{{ path }}" "gcp/stage/{{ path }}"

# (Re-)generate dataset_manifest.json for a dataset (requires GCS_BUCKET).
# Example: just gen-manifest sk false_rejects
[group('bucket')]
gen-manifest project dataset:
    BMT_PROJECT={{ project }} BMT_DATASET={{ dataset }} uv run python -m tools.remote.gen_input_manifest

# Mount a dataset read-only via gcsfuse into gcp/mnt/<project>-inputs/ (dev QoL, opt-in).
# Requires gcsfuse. Example: just mount-data sk
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

# Unmount a gcsfuse data mount. Example: just umount-data sk
[group('bucket')]
umount-data project:
    fusermount -u gcp/mnt/{{ project }}-inputs

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

# -- Docker (Cloud Run image) --------------------------------------------------

# Build the BMT orchestrator container image (buildx for BuildKit/cache)
[group('docker')]
docker-build:
    docker buildx build --load -t bmt-orchestrator:latest -f gcp/image/Dockerfile .

# Run the container locally with gcp/stage bind-mounted as /mnt/runtime (FUSE simulation)
[group('docker')]
docker-run-test *args:
    docker run --rm \
        -v "$(pwd)/gcp/stage:/mnt/runtime:ro" \
        -e BMT_CONFIG=/etc/bmt/config.json \
        {{ args }} \
        bmt-orchestrator:latest

# Tag and push the image to Artifact Registry (requires gcloud auth configure-docker)
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
