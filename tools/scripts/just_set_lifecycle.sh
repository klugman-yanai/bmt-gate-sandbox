#!/usr/bin/env bash
set -euo pipefail
gcloud storage buckets update "gs://$(cd infra/pulumi && pulumi stack output gcs_bucket)" \
  --lifecycle-file=infra/lifecycle.json \
  --project="$(cd infra/pulumi && pulumi stack output gcp_project)"
