#!/usr/bin/env bash
set -euo pipefail
PROJECT="${GCP_PROJECT:-train-kws-202311}"
REGION="${CLOUD_RUN_REGION:-europe-west4}"
echo "JOB  IMAGE"
for JOB in bmt-control bmt-task-standard bmt-task-heavy bmt-orchestrator-standard bmt-orchestrator-heavy; do
  IMG=$(gcloud run jobs describe "$JOB" --region="$REGION" --project="$PROJECT" \
    --format="value(spec.template.spec.template.spec.containers[0].image)" 2>/dev/null || echo "(not found)")
  echo "$JOB  $IMG"
done
