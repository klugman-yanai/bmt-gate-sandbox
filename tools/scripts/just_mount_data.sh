#!/usr/bin/env bash
set -euo pipefail
project="${1:?project required}"
mkdir -p "mnt/${project}-inputs"
gcsfuse \
  --only-dir="projects/${project}/inputs" \
  --file-mode=444 \
  --dir-mode=555 \
  --implicit-dirs \
  --stat-cache-ttl=300s \
  --type-cache-ttl=300s \
  --kernel-list-cache-ttl-secs=60 \
  "${GCS_BUCKET}" "mnt/${project}-inputs"
