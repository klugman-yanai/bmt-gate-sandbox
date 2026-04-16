# bmt-gcloud dev tools

default:
    @just help

help:
    @echo "Tip: just test, just build-pex. Full recipe list:"
    @just --list

# Passthrough to the unified Typer CLI (see: just tools --help).
[group('cli')]
tools *args:
    uv run python -m tools {{ args }}

# -- Pre-push ---------------------------------------------------------------

# Sections run in priority order; each completes before the next. Stops at first failing section.
# Optional diagnostics (not part of just test): dead code + duplicate-code on env-related modules.
[group('validate')]
doctor:
    uv run vulture runtime/config tools/shared/env.py tools/shared/bucket_env.py --min-confidence 80
    uv run pylint --disable=all --enable=duplicate-code --min-similarity-lines=6 runtime/config/env_parse.py tools/shared/env.py tools/shared/bucket_env.py ci/ci/workflow_dispatch.py

[group('validate')]
typecheck section="all":
    #!/usr/bin/env bash
    set -euo pipefail
    run() { echo ""; echo "==> ty check: $$1 ($$2)"; uv run ty check "$$2"; }
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
        run "CI" "ci" ;;
      runtime|gcp)
        run "Runtime" "runtime" ;;
      infra)
        run "Infra" "infra" ;;
      tools)
        run "Tools" "tools" ;;
      tests)
        run "Tests" "tests" ;;
      stage)
        run "Plugins mirror" "plugins" ;;
      *)
        echo "Unknown section {{section}}. Use: all | ci | runtime | infra | tools | tests | stage" >&2
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
    PYTHONPATH=./ uv run ty check
    command -v actionlint >/dev/null 2>&1 || (echo "Install actionlint (https://github.com/rhysd/actionlint)" >&2; exit 1)
    actionlint -config-file .github/actionlint.yaml
    command -v shellcheck >/dev/null 2>&1 || (echo "Install shellcheck (e.g. apt install shellcheck)" >&2; exit 1)
    shellcheck --severity=warning tools/scripts/hooks/*.sh
    uv run python -m tools repo validate-layout

    just release-check

# -- Bucket ------------------------------------------------------------------

[group('bucket')]
deploy:
    uv run python -m tools bucket deploy

# Verify plugins matches the GCS bucket runtime seed manifest (requires GCS_BUCKET).
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
    gcloud storage cp -r "gs://$${GCS_BUCKET}/projects/{{ project }}/inputs/{{ dataset }}/" \
        "plugins/projects/{{ project }}/inputs/{{ dataset }}/"

# Fetch a single file from GCS into plugins/.
# Example: just fetch-wav projects/sk/inputs/false_rejects/ambient/cafe_001.wav
[private]
[group('bucket')]
fetch-wav path:
    gcloud storage cp "gs://$${GCS_BUCKET}/{{ path }}" "plugins/{{ path }}"

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
    bash tools/scripts/just_mount_data.sh "{{ project }}"

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
    gh variable set GCS_BUCKET --body "$$(cd infra/pulumi && pulumi stack output gcs_bucket)"

# -- Large dataset uploads (Storage Transfer Service agent) ------------------

# One-time: create the agent pool. Safe to re-run.
[group('upload')]
infra-setup:
    #!/usr/bin/env bash
    set -euo pipefail
    PROJECT="$${GCP_PROJECT:-train-kws-202311}"
    gcloud transfer agent-pools create bmt-upload-pool --project="$$PROJECT" 2>/dev/null || true
    echo "Agent pool ready."
    echo "Next: just agent-start before any large upload, then just transfer with project, dataset, source args"
    echo "For Drive->GCS: docker run --rm -it -v \$HOME/.config/rclone:/config/rclone rclone/rclone config"

# Start the Transfer Service agent. Mounts ./data as /transfer_root inside the container.
# Run once before a batch of transfers; stop when done.
[group('upload')]
agent-start:
    bash tools/scripts/just_agent_start.sh

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
    PROJECT="$${GCP_PROJECT:-train-kws-202311}"
    gcloud transfer jobs create \
      --source-agent-pool=bmt-upload-pool \
      --source-directory="/transfer_root/{{source}}" \
      --destination="gs://$${GCS_BUCKET}/projects/{{project}}/inputs/{{dataset}}" \
      --project="$$PROJECT"
    echo ""
    echo "Monitor: https://console.cloud.google.com/storage-transfer?project=$$PROJECT"
    echo "After completion run: GCS_BUCKET=$${GCS_BUCKET} just upload-data {{project}} {{dataset}} data/{{source}} --force"

# Compare local vs GCS file counts for a dataset.
# Example: GCS_BUCKET=... just upload-status sk false_alarms
[group('upload')]
upload-status project dataset:
    #!/usr/bin/env bash
    set -euo pipefail
    LOCAL=$$(find "data/{{dataset}}" -type f 2>/dev/null | wc -l || echo 0)
    REMOTE=$$(gcloud storage ls "gs://$${GCS_BUCKET}/projects/{{project}}/inputs/{{dataset}}/**" 2>/dev/null | wc -l || echo 0)
    echo "Local  (data/{{dataset}}):                         $$LOCAL files"
    echo "Remote (gs://$${GCS_BUCKET}/projects/{{project}}/inputs/{{dataset}}): $$REMOTE files"
    if [ "$$LOCAL" -eq "$$REMOTE" ]; then echo "✓ In sync"; else echo "✗ Mismatch"; fi

# Google Drive folder -> GCS via rclone (requires prior: docker run --rm -it rclone/rclone config).
# <folder_id> is the Drive folder ID from the URL.
# Example: GCS_BUCKET=... just drive-sync 1CFF2GQ... sk false_alarms
[group('upload')]
drive-sync folder_id project dataset:
    docker run --rm -v "$$HOME/.config/rclone:/config/rclone" rclone/rclone copy "drive:{{folder_id}}" "gcs:$${GCS_BUCKET}/projects/{{project}}/inputs/{{dataset}}" --drive-root-folder-id="{{folder_id}}" --progress --transfers=4 --stats=5s

# -- Monitoring & debug -------------------------------------------------------

# Tail recent logs for a Cloud Run job. Default: last 1 hour.
# Example: just logs bmt-control
[group('monitor')]
logs job freshness="1h":
    #!/usr/bin/env bash
    set -euo pipefail
    PROJECT="$${GCP_PROJECT:-train-kws-202311}"
    gcloud logging read \
      "resource.type=cloud_run_job AND resource.labels.job_name={{job}}" \
      --project="$$PROJECT" \
      --limit=200 \
      --freshness="{{freshness}}" \
      --format="table(timestamp,textPayload)"

# Show the image digest each Cloud Run job is currently pinned to.
[group('monitor')]
image-status:
    bash tools/scripts/just_image_status.sh

# Open a PR from the current branch targeting ci/check-bmt-gate to trigger the E2E BMT pipeline.
[group('monitor')]
e2e-trigger:
    gh pr create --title "chore: E2E trigger" --body "Trigger BMT gate E2E pipeline." --base ci/check-bmt-gate

# -- Infrastructure ----------------------------------------------------------

# Apply GCS lifecycle rules (run once after pulumi apply; deletes orphaned imports/ after 2d, triggers/ after 7d).
[group('infra')]
set-lifecycle:
    bash tools/scripts/just_set_lifecycle.sh

[group('infra')]
pulumi *args:
    uv run python -m tools pulumi apply {{ args }}

# Build the Cloud Run image (optional repo override: see tools build image).
[private]
[group('infra')]
build *args:
    #!/usr/bin/env bash
    uv run python -m tools build image --branch "$$(git rev-parse --abbrev-ref HEAD)" {{ args }}

[private]
[group('infra')]
packer-validate:
    uv run python -m tools build packer-validate

# -- Validation & debug -------------------------------------------------------

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

# Legacy: assemble .github-release/ for core-main (deprecated — production uses published bmt.pex + bmt-get-pex).
[group('dev')]
release-legacy *args:
    uv run python scripts/assemble_release.py {{ args }}

[group('dev')]
release-check:
    command -v actionlint >/dev/null 2>&1 || (echo Install actionlint >&2; exit 1)
    actionlint -config-file .github/actionlint.yaml \
      .github/workflows/bmt-handoff.yml \
      .github/workflows/internal/build-kardome-bmt-pex.yml

# Self-contained bmt CLI for consumer CI (GitHub Release asset: bmt.pex on tag bmt-v*).
[group('dev')]
build-pex:
    bash scripts/build_kardome_bmt_pex.sh

# -- Local CI ----------------------------------------------------------------

# Default: workflow_dispatch on build-and-test.yml. For handoff or internal/trigger-ci, run act with -W yourself or see .github/README.md.
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
    bash tools/scripts/just_docker_run_test.sh {{ args }}

# Tag and push the image to Artifact Registry (requires gcloud auth configure-docker).
# Also tags with the full git commit SHA so just ship can verify the image via Artifact Registry.
[private]
[group('docker')]
docker-push:
    bash tools/scripts/just_docker_push.sh

# -- E2E Tests ---------------------------------------------------------------

# Placeholder: previous recipe mixed invalid Just syntax (@printf multiline, finally:). Restore from git history if needed.
e2e-test-cloud-run:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "e2e-test-cloud-run is not implemented as a maintained Just recipe." >&2
    echo "Use docs/architecture.md and manual gcloud/pulumi steps, or restore an older Justfile from git." >&2
    exit 1