# bmt-gcloud dev tools

default:
    @just help

help:
    @printf '%s\n' \
      'Daily' \
      '  just test              Full suite: pytest, ruff, ty, actionlint, shellcheck, layout' \
      '  just ship              Pre-push gate (test → preflight → deploy → image); see --help' \
      '  just deploy            Sync plugins to GCS + verify' \
      '  just setup             Bootstrap: uv, gcloud, ADC, deps, hooks (just setup --dev for full)' \
      '' \
      'Infra & BMT' \
      '  just pulumi            Pulumi apply + repo vars' \
      '  just image             Docker build + push (Artifact Registry)' \
      '  just add-project       Scaffold staged project' \
      '  just add-bmt / publish-bmt' \
      '' \
      'Bucket & data' \
      '  just check-sync        Verify plugins matches GCS bucket (advisory)' \
      '  just upload-data       Small datasets: zip/folder → GCS via rsync' \
      '  just infra-setup       One-time: create Transfer Service agent pool' \
      '  just agent-start/stop  Manage local Transfer Service agent (Docker)' \
      '  just transfer          Large WAV datasets → GCS via Transfer Service agent' \
      '  just drive-sync        Google Drive folder → GCS via rclone (Docker)' \
      '  just upload-status     Compare local vs GCS file counts for a dataset' \
      '  just mount-project / umount-project' \
      '' \
      'Monitoring' \
      '  just logs              Tail Cloud Run job logs' \
      '  just image-status      Show image digest pinned to each Cloud Run job' \
      '  just e2e-trigger       Open a PR to trigger the full E2E BMT pipeline' \
      '' \
      'Other' \
      '  just typecheck [section]   ty: all sections, or one of ci | runtime | infra | tools | tests | plugins' \
      '  just release / release-check' \
      '  just show-env, validate, doctor' \
      '' \
      'Escape hatch (full CLI)' \
      '  just tools …           Same as: uv run python -m tools …' \
      '  just tools --help      List all subcommands (bucket, bmt, repo, …)'

# Passthrough to the unified Typer CLI (see `just tools --help`).
[group('cli')]
tools *args:
    uv run python -m tools {{ args }}

# -- Pre-push ---------------------------------------------------------------

# Sections run in priority order; each completes before the next. Stops at first failing section.
# Optional diagnostics (not part of `just test`): dead code + duplicate-code on env-related modules.
[group('validate')]
doctor:
    uv run vulture runtime/config tools/shared/env.py tools/shared/bucket_env.py --min-confidence 80
    uv run pylint --disable=all --enable=duplicate-code --min-similarity-lines=6 \
      runtime/config/env_parse.py tools/shared/env.py tools/shared/bucket_env.py ci/ci/workflow_dispatch.py

[group('validate')]
typecheck section="all":
    #!/usr/bin/env bash
    set -euo pipefail
    run() { printf '\n==> ty check: %s (%s)\n' "$1" "$2"; uv run ty check "$2"; }
    case "{{section}}" in
      all)
        run "CI" "ci"
        run "Runtime" "runtime"
        run "Infra" "infra"
        run "Tools" "tools"
        run "Tests" "tests"
        run "Plugins mirror" "plugins"
        ;;
      ci)
        printf '\n==> ty check: CI (ci)\n'; uv run ty check ci ;;
      runtime|gcp)
        printf '\n==> ty check: Runtime\n'; uv run ty check runtime ;;
      infra)
        printf '\n==> ty check: Infra\n'; uv run ty check infra ;;
      tools)
        printf '\n==> ty check: Tools\n'; uv run ty check tools ;;
      tests)
        printf '\n==> ty check: Tests\n'; uv run ty check tests ;;
      stage)
        printf '\n==> ty check: Plugins mirror\n'; uv run ty check plugins ;;
      *)
        printf 'Unknown section %q. Use: all | ci | runtime | infra | tools | tests | stage\n' "{{section}}" >&2
        exit 1
        ;;
    esac

[group('pre-push')]
ship *args:
    uv run python -m tools ship {{ args }}

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

# Verify plugins matches the GCS bucket's runtime seed manifest (requires GCS_BUCKET).
# Run this before triggering BMT to catch stale local mirrors.
[group('bucket')]
check-sync:
    uv run python -m tools.remote.bucket_verify_runtime_seed_sync

[private]
[group('bucket')]
preflight:
    uv run python -m tools bucket preflight

# Upload WAV dataset to projects/<project>/inputs/<dataset>/ in GCS only (datasets can be 30-40 GB).
# Archives use gcloud storage cp + Cloud Run extraction. Folders use gcloud storage rsync.
# Dataset name is auto-detected from the filename.
# Pass --local to also mirror into plugins/. Example: just upload-data sk audio/sk_false_rejects.zip
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

# Fetch a full dataset from GCS into plugins/ for local use.
# Example: just fetch-inputs sk false_rejects
[private]
[group('bucket')]
fetch-inputs project dataset:
    gcloud storage cp -r "gs://$GCS_BUCKET/projects/{{ project }}/inputs/{{ dataset }}/" \
        "plugins/projects/{{ project }}/inputs/{{ dataset }}/"

# Fetch a single file from GCS into plugins/.
# Example: just fetch-wav projects/sk/inputs/false_rejects/ambient/cafe_001.wav
[private]
[group('bucket')]
fetch-wav path:
    gcloud storage cp "gs://$GCS_BUCKET/{{ path }}" "plugins/{{ path }}"

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
    mkdir -p mnt/{{ project }}-inputs
    gcsfuse \
        --only-dir="projects/{{ project }}/inputs" \
        --file-mode=444 \
        --dir-mode=555 \
        --implicit-dirs \
        --stat-cache-ttl=300s \
        --type-cache-ttl=300s \
        --kernel-list-cache-ttl-secs=60 \
        "$GCS_BUCKET" mnt/{{ project }}-inputs

[group('bucket')]
mount-project project:
    uv run python -m tools bucket mount-project "{{ project }}"

# Unmount a gcsfuse data mount. Example: just umount-data sk
[private]
[group('bucket')]
umount-data project:
    fusermount -u mnt/{{ project }}-inputs

[group('bucket')]
umount-project project:
    uv run python -m tools bucket umount-project "{{ project }}"

# Set GCS_BUCKET GitHub repo var from Pulumi output (e.g. after it was removed)
[private]
[group('bucket')]
set-bucket-var:
    gh variable set GCS_BUCKET --body "$(cd infra/pulumi && pulumi stack output gcs_bucket)"

# -- Large dataset uploads (Storage Transfer Service agent) ------------------

# One-time: create the agent pool. Safe to re-run.
[group('upload')]
infra-setup:
    #!/usr/bin/env bash
    set -euo pipefail
    PROJECT="${GCP_PROJECT:-train-kws-202311}"
    gcloud transfer agent-pools create bmt-upload-pool --project="$PROJECT" 2>/dev/null || true
    echo "Agent pool ready."
    echo "Next: 'just agent-start' before any large upload, then 'just transfer <project> <dataset> <source>'"
    echo "For Drive→GCS: docker run --rm -it -v \$HOME/.config/rclone:/config/rclone rclone/rclone config"

# Start the Transfer Service agent. Mounts ./data as /transfer_root inside the container.
# Run once before a batch of transfers; stop when done.
[group('upload')]
agent-start:
    #!/usr/bin/env bash
    set -euo pipefail
    PROJECT="${GCP_PROJECT:-train-kws-202311}"
    if docker ps --format '{{{{.Names}}}}' | grep -q '^bmt-transfer-agent$'; then
      echo "Agent already running."
      exit 0
    fi
    docker run -d --name bmt-transfer-agent \
      -v "$HOME/.config/gcloud:/root/.config/gcloud" \
      -v "$(pwd)/data:/transfer_root" \
      gcr.io/cloud-ingest/tsop-agent \
      --project="$PROJECT" \
      --agent-pool=bmt-upload-pool
    echo "Agent started. Stop with: just agent-stop"

[group('upload')]
agent-stop:
    docker rm -f bmt-transfer-agent || true

# Create a managed transfer job for a WAV dataset.
# <source> is a path relative to ./data (e.g. false_alarms or rejects/quiet).
# Monitor at https://console.cloud.google.com/storage-transfer
# Example: GCS_BUCKET=train-kws-202311-bmt-gate just transfer sk false_alarms false_alarms
[group('upload')]
transfer project dataset source:
    #!/usr/bin/env bash
    set -euo pipefail
    PROJECT="${GCP_PROJECT:-train-kws-202311}"
    gcloud transfer jobs create \
      --source-agent-pool=bmt-upload-pool \
      --source-directory="/transfer_root/{{source}}" \
      --destination="gs://${GCS_BUCKET}/projects/{{project}}/inputs/{{dataset}}" \
      --project="$PROJECT"
    echo ""
    echo "Monitor: https://console.cloud.google.com/storage-transfer?project=$PROJECT"
    echo "After completion run: GCS_BUCKET=${GCS_BUCKET} just upload-data {{project}} {{dataset}} data/{{source}} --force"

# Compare local vs GCS file counts for a dataset.
# Example: GCS_BUCKET=... just upload-status sk false_alarms
[group('upload')]
upload-status project dataset:
    #!/usr/bin/env bash
    set -euo pipefail
    LOCAL=$(find "data/{{dataset}}" -type f 2>/dev/null | wc -l || echo 0)
    REMOTE=$(gcloud storage ls "gs://${GCS_BUCKET}/projects/{{project}}/inputs/{{dataset}}/**" 2>/dev/null | wc -l || echo 0)
    echo "Local  (data/{{dataset}}):                         $LOCAL files"
    echo "Remote (gs://${GCS_BUCKET}/projects/{{project}}/inputs/{{dataset}}): $REMOTE files"
    if [ "$LOCAL" -eq "$REMOTE" ]; then echo "✓ In sync"; else echo "✗ Mismatch"; fi

# Google Drive folder → GCS via rclone (requires prior: docker run --rm -it rclone/rclone config).
# <folder_id> is the Drive folder ID from the URL.
# Example: GCS_BUCKET=... just drive-sync 1CFF2GQ... sk false_alarms
[group('upload')]
drive-sync folder_id project dataset:
    docker run --rm \
      -v "$HOME/.config/rclone:/config/rclone" \
      rclone/rclone copy \
      "drive:{{folder_id}}" \
      "gcs:${GCS_BUCKET}/projects/{{project}}/inputs/{{dataset}}" \
      --drive-root-folder-id="{{folder_id}}" \
      --progress \
      --transfers=4 \
      --stats=5s

# -- Monitoring & debug -------------------------------------------------------

# Tail recent logs for a Cloud Run job. Default: last 1 hour.
# Example: just logs bmt-control
[group('monitor')]
logs job freshness="1h":
    #!/usr/bin/env bash
    set -euo pipefail
    PROJECT="${GCP_PROJECT:-train-kws-202311}"
    gcloud logging read \
      "resource.type=cloud_run_job AND resource.labels.job_name={{job}}" \
      --project="$PROJECT" \
      --limit=200 \
      --freshness="{{freshness}}" \
      --format="table(timestamp,textPayload)"

# Show the image digest each Cloud Run job is currently pinned to.
[group('monitor')]
image-status:
    #!/usr/bin/env bash
    set -euo pipefail
    PROJECT="${GCP_PROJECT:-train-kws-202311}"
    REGION="${CLOUD_RUN_REGION:-europe-west4}"
    printf '%-35s %s\n' "JOB" "IMAGE"
    for JOB in bmt-control bmt-task-standard bmt-task-heavy bmt-orchestrator-standard bmt-orchestrator-heavy; do
      IMG=$(gcloud run jobs describe "$JOB" --region="$REGION" --project="$PROJECT" \
        --format="value(spec.template.spec.template.spec.containers[0].image)" 2>/dev/null || echo "(not found)")
      printf '%-35s %s\n' "$JOB" "$IMG"
    done

# Open a PR from the current branch targeting ci/check-bmt-gate to trigger the E2E BMT pipeline.
[group('monitor')]
e2e-trigger:
    gh pr create \
      --title "chore: E2E trigger" \
      --body "Trigger BMT gate E2E pipeline." \
      --base ci/check-bmt-gate

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

# One-time setup for a fresh machine: installs uv, gcloud, ADC, syncs deps, installs prek hooks.
# Pass --dev for a full developer environment (shellcheck, actionlint, pulumi).
# Pass --dry-run to preview what would be installed without making changes.
[group('setup')]
setup *args:
    bash tools/scripts/setup.sh {{ args }}

[group('dev')]
publish-bmt project bmt_slug:
    uv run python -m tools bmt publish-bmt "{{ project }}" "{{ bmt_slug }}"

[group('dev')]
release *args:
    uv run python scripts/assemble_release.py {{ args }}
    @echo "Deploy: rsync .github-release/ → ~/kardome/core-main/.github/"

# CI parity: bundle without local PEM; verify provenance; lint handoff + main CI workflows only
# (templates like trigger-ci.yml may not pass full actionlint — see .github/README.md file-release checklist).
[group('dev')]
release-check:
    uv run python scripts/assemble_release.py --skip-secrets
    test -f .github-release/bmt_release.json
    jq -e '.source_sha | length >= 7' .github-release/bmt_release.json
    test -f .github-release/workflows/bmt-handoff.yml
    command -v actionlint >/dev/null 2>&1 || (echo "Install actionlint (https://github.com/rhysd/actionlint)" >&2; exit 1)
    # Handoff only: build-and-test.yml may hit shellcheck noise unrelated to the release bundle.
    actionlint -config-file .github-release/actionlint.yaml \
      .github-release/workflows/bmt-handoff.yml

# -- Local CI ----------------------------------------------------------------

# Default: workflow_dispatch on build-and-test.yml. For handoff or internal/trigger-ci, run `act` with -W yourself or see .github/README.md.
[group('local-ci')]
act:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -f .env ]]; then
      exec act workflow_dispatch -W .github/workflows/build-and-test.yml --var-file .env
    fi
    exec act workflow_dispatch -W .github/workflows/build-and-test.yml

# -- Docker (Cloud Run image) --------------------------------------------------

[group('docker')]
image: docker-build docker-push

# Build the BMT orchestrator container image (legacy builder; install buildx for BuildKit)
[private]
[group('docker')]
docker-build:
    docker build -t bmt-orchestrator:latest -f runtime/Dockerfile .

# Run the container locally with plugins bind-mounted as /mnt/runtime (FUSE simulation)
[private]
[group('docker')]
docker-run-test *args:
    docker run --rm \
        -v "$(pwd)/plugins:/mnt/runtime:ro" \
        -e BMT_CONFIG=/etc/bmt/config.json \
        {{ args }} \
        bmt-orchestrator:latest

# Tag and push the image to Artifact Registry (requires gcloud auth configure-docker).
# Also tags with the full git commit SHA so `just ship` can verify the image via Artifact Registry.
[private]
[group('docker')]
docker-push:
    #!/usr/bin/env bash
    set -euo pipefail
    PROJECT=$(cd infra/pulumi && pulumi stack output gcp_project 2>/dev/null || echo "${GCP_PROJECT:-train-kws-202311}")
    REGION="${CLOUD_RUN_REGION:-europe-west4}"
    REPO="${ARTIFACT_REGISTRY_REPO:-bmt-images}"
    GIT_SHA=$(git rev-parse HEAD)
    IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/bmt-orchestrator"
    docker tag bmt-orchestrator:latest "${IMAGE_BASE}:latest"
    docker tag bmt-orchestrator:latest "${IMAGE_BASE}:${GIT_SHA}"
    docker push "${IMAGE_BASE}:latest"
    docker push "${IMAGE_BASE}:${GIT_SHA}"
    echo "Pushed: ${IMAGE_BASE}:latest and :${GIT_SHA}"
