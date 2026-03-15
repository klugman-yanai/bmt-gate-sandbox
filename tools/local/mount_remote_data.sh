#!/usr/bin/env bash
# Mount GCS bucket dataset prefix read-only for local inspection (VLC, IDE, etc.).
# Usage: GCS_BUCKET=<bucket> [BMT_MOUNT_POINT=<path>] tools/local/mount_remote_data.sh
# Requires: gcsfuse installed, gcloud auth.
# Safety: -o ro prevents accidental writes to the bucket.
set -euo pipefail

BUCKET="${GCS_BUCKET:?Set GCS_BUCKET}"
MOUNT_POINT="${BMT_MOUNT_POINT:-./mnt/audio_data}"
PREFIX="sk/inputs/false_rejects"

if [[ -d "${MOUNT_POINT}" ]] && mountpoint -q "${MOUNT_POINT}" 2>/dev/null; then
  echo "Already mounted: ${MOUNT_POINT}"
  exit 0
fi

mkdir -p "${MOUNT_POINT}"
echo "Mounting gs://${BUCKET}/${PREFIX} at ${MOUNT_POINT} (read-only)..."
exec gcsfuse -o ro --implicit-dirs --only-dir "${PREFIX}" "${BUCKET}" "${MOUNT_POINT}"
