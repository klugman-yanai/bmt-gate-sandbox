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
echo "Hint: Cloud Run jobs (bmt-control, bmt-task-*) must reference this image digest or :latest — see .github/README.md (Orchestrator image)."

# Resolve the manifest digest of the freshly-pushed :${GIT_SHA} tag so the CI-driven
# release can record the exact image bits that were produced (release marker). The
# registry is authoritative — local Docker image IDs can differ from registry digests.
IMAGE_DIGEST="$(gcloud artifacts docker images describe "${IMAGE_BASE}:${GIT_SHA}" --format='value(image_summary.digest)' 2>/dev/null || true)"
if [[ -n "${IMAGE_DIGEST:-}" ]]; then
  echo "IMAGE_DIGEST=${IMAGE_DIGEST}"
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "image_digest=${IMAGE_DIGEST}" >>"${GITHUB_OUTPUT}"
  fi
else
  echo "::warning::failed to resolve image digest for ${IMAGE_BASE}:${GIT_SHA}; release marker will omit image_digest"
fi
