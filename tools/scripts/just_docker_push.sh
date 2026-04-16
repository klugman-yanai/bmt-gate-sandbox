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
