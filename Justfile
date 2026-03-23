# bmt-gcloud Justfile. `just` lists recipes; `default` pins justfile() for `just -f`.
alias help := default

[doc('List grouped recipes')]
[group('help')]
default:
    @just --list --unsorted --justfile {{ justfile() }}

[doc('Typer tools CLI (tools --help)')]
[group('cli')]
tools *args:
    uv run python -m tools {{ args }}

# pytest, ruff, ty, actionlint, layout.
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

# test, workspace preflight/deploy, image.
[group('pre-push')]
ship *args:
    uv run python -m tools ship {{ args }}

# vulture + pylint duplicate-code.
[group('validate')]
doctor:
    uv run vulture gcp/image/config tools/shared/env.py tools/shared/bucket_env.py --min-confidence 80
    uv run pylint --disable=all --enable=duplicate-code --min-similarity-lines=6 \
      gcp/image/config/env_parse.py tools/shared/env.py tools/shared/bucket_env.py .github/bmt/ci/workflow_dispatch.py

[doc('ty by section; default=all')]
[group('validate')]
typecheck section="all":
    #!/usr/bin/env bash
    set -euo pipefail
    run() { printf '\n==> ty check: %s (%s)\n' "$1" "$2"; uv run ty check "$2"; }
    case "{{section}}" in
      all)
        run "CI" ".github/bmt"
        run "Runtime (gcp/image)" "gcp/image"
        run "Infra" "infra"
        run "Tools" "tools"
        run "Tests" "tests"
        run "Stage mirror" "gcp/stage"
        ;;
      ci)
        printf '\n==> ty check: CI (.github/bmt)\n'; uv run ty check .github/bmt ;;
      runtime|gcp)
        printf '\n==> ty check: Runtime (gcp/image)\n'; uv run ty check gcp/image ;;
      infra)
        printf '\n==> ty check: Infra\n'; uv run ty check infra ;;
      tools)
        printf '\n==> ty check: Tools\n'; uv run ty check tools ;;
      tests)
        printf '\n==> ty check: Tests\n'; uv run ty check tests ;;
      stage)
        printf '\n==> ty check: Stage mirror\n'; uv run ty check gcp/stage ;;
      *)
        printf 'Unknown section %q. Use: all | ci | runtime | infra | tools | tests | stage\n' "{{section}}" >&2
        exit 1
        ;;
    esac

# CI/runtime env (gh when available).
[group('validate')]
show-env:
    uv run python -m tools repo show-env

# pulumi validate preflight deploy e2e
[group('workspace')]
workspace *args:
    uv run python -m tools workspace {{ args }}

# Dataset zip/dir to GCS (see --help).
[group('bucket')]
upload-data project source *args:
    uv run python -m tools bucket upload-dataset "{{ project }}" "{{ source }}" {{ args }}

# Mount project inputs read-only (FUSE).
[group('bucket')]
mount project:
    uv run python -m tools bucket mount-project "{{ project }}"

# Unmount `just mount` target.
[group('bucket')]
unmount project:
    uv run python -m tools bucket umount-project "{{ project }}"

# Bucket lifecycle once (post-pulumi).
[group('infra')]
set-lifecycle:
    gcloud storage buckets update gs://$(cd infra/pulumi && pulumi stack output gcs_bucket) \
        --lifecycle-file=infra/lifecycle.json \
        --project=$(cd infra/pulumi && pulumi stack output gcp_project)

# buildx build + push orchestrator image.
[group('docker')]
image: docker-build docker-push

# BMT gcp/stage workflow: `just stage` (help) · project | bmt | publish + args.
[group('dev')]
stage *argv:
    uv run python -m tools bmt stage {{ argv }}

# Dev bootstrap: uv, hooks (onboard -h).
[group('dev')]
onboard *args:
    bash tools/scripts/bootstrap_dev_env.sh {{ args }}

# Build .github-release/ bundle.
[group('dev')]
release *args:
    uv run python scripts/assemble_release.py {{ args }}
    @echo "Deploy: rsync .github-release/ → ~/kardome/core-main/.github/"

# Check release bundle + handoff lint.
[group('dev')]
release-check:
    uv run python scripts/assemble_release.py --skip-secrets
    test -f .github-release/bmt_release.json
    jq -e '.source_sha | length >= 7' .github-release/bmt_release.json
    test -f .github-release/workflows/bmt-handoff.yml
    command -v actionlint >/dev/null 2>&1 || (echo "Install actionlint (https://github.com/rhysd/actionlint)" >&2; exit 1)
    actionlint -config-file .github-release/actionlint.yaml \
      .github-release/workflows/bmt-handoff.yml

# act: workflow_dispatch build-and-test.
[group('local-ci')]
act:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -f .env ]]; then
      exec act workflow_dispatch -W .github/workflows/build-and-test.yml --var-file .env
    fi
    exec act workflow_dispatch -W .github/workflows/build-and-test.yml

[private]
[group('bucket')]
project-sync project:
    uv run python -m tools bucket project-sync "{{ project }}"

[private]
[group('bucket')]
clean-bloat *args:
    uv run python -m tools bucket clean-bloat {{ args }}

[private]
[group('bucket')]
fetch-inputs project dataset:
    gcloud storage cp -r "gs://$GCS_BUCKET/projects/{{ project }}/inputs/{{ dataset }}/" \
        "gcp/stage/projects/{{ project }}/inputs/{{ dataset }}/"

[private]
[group('bucket')]
fetch-wav path:
    gcloud storage cp "gs://$GCS_BUCKET/{{ path }}" "gcp/stage/{{ path }}"

[private]
[group('bucket')]
gen-manifest project dataset:
    BMT_PROJECT={{ project }} BMT_DATASET={{ dataset }} uv run python -m tools.remote.gen_input_manifest

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

[private]
[group('bucket')]
umount-data project:
    fusermount -u gcp/mnt/{{ project }}-inputs

[private]
[group('bucket')]
set-bucket-var:
    gh variable set GCS_BUCKET --body "$(cd infra/pulumi && pulumi stack output gcs_bucket)"

[private]
[group('validate')]
repo-vars-apply:
    uv run python -m tools.repo.gh_repo_vars --apply

[private]
[group('infra')]
build *args:
    uv run python -m tools build image --branch "`git rev-parse --abbrev-ref HEAD`" {{ args }}

[private]
[group('infra')]
packer-validate:
    uv run python -m tools build packer-validate

[private]
[group('docker')]
docker-build:
    docker buildx build --load -t bmt-orchestrator:latest -f gcp/image/Dockerfile .

[private]
[group('docker')]
docker-run-test *args:
    docker run --rm \
        -v "$(pwd)/gcp/stage:/mnt/runtime:ro" \
        -e BMT_CONFIG=/etc/bmt/config.json \
        {{ args }} \
        bmt-orchestrator:latest

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
