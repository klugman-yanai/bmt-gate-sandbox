#!/usr/bin/env bash
# Read-only FUSE mount of gs://$GCS_BUCKET/projects/<project>/inputs under gcp/mnt/<project>-inputs/.
set -euo pipefail

project="${1:?usage: $0 <project>}"
: "${GCS_BUCKET:?GCS_BUCKET must be set}"

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
mnt_root="$repo_root/gcp/mnt/${project}-inputs"

mkdir -p "$mnt_root"
gcsfuse \
    --only-dir="projects/${project}/inputs" \
    --file-mode=444 \
    --dir-mode=555 \
    --implicit-dirs \
    --stat-cache-ttl=300s \
    --type-cache-ttl=300s \
    --kernel-list-cache-ttl-secs=60 \
    "$GCS_BUCKET" "$mnt_root"
