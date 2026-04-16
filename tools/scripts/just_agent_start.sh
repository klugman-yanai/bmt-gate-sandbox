#!/usr/bin/env bash
set -euo pipefail
PROJECT="${GCP_PROJECT:-train-kws-202311}"
if docker ps --format '{{.Names}}' | grep -qxF bmt-transfer-agent; then
  echo "Agent already running."
  exit 0
fi
docker run -d --name bmt-transfer-agent \
  -v "$HOME/.config/gcloud:/root/.config/gcloud" \
  -v "$PWD/data:/transfer_root" \
  gcr.io/cloud-ingest/tsop-agent \
  --project="$PROJECT" \
  --agent-pool=bmt-upload-pool
echo "Agent started. Stop with: just agent-stop"
