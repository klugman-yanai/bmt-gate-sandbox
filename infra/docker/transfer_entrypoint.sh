#!/usr/bin/env bash
# Cloud Run entrypoint for the bmt-dataset-transfer job.
# Copies a Google Drive folder to GCS using rclone, then generates a dataset manifest.
set -euo pipefail

# ---------------------------------------------------------------------------
# Validate required env vars
# ---------------------------------------------------------------------------
missing=()
for var in DRIVE_FOLDER_ID DEST_PROJECT DEST_DATASET DEST_BUCKET BMT_DRIVE_SA_KEY; do
    if [[ -z "${!var:-}" ]]; then
        missing+=("$var")
    fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "::error::Missing required env vars: ${missing[*]}" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Write Drive service account key to a temp file
# ---------------------------------------------------------------------------
SA_KEY_FILE=/tmp/sa.json
printf '%s' "$BMT_DRIVE_SA_KEY" > "$SA_KEY_FILE"
chmod 600 "$SA_KEY_FILE"

# ---------------------------------------------------------------------------
# Write rclone config
# Drive backend uses the SA key; GCS backend uses Workload Identity (ADC).
# ---------------------------------------------------------------------------
mkdir -p ~/.config/rclone
cat > ~/.config/rclone/rclone.conf <<EOF
[gdrive]
type = drive
service_account_file = ${SA_KEY_FILE}

[gcs]
type = google cloud storage
EOF

# ---------------------------------------------------------------------------
# Run rclone copy: Drive folder → GCS destination prefix
# ---------------------------------------------------------------------------
DEST_PREFIX="projects/${DEST_PROJECT}/inputs/${DEST_DATASET}"
GCS_DEST="gcs:${DEST_BUCKET}/${DEST_PREFIX}/"

echo "Copying Google Drive folder ${DRIVE_FOLDER_ID} → gs://${DEST_BUCKET}/${DEST_PREFIX}/"
rclone copy \
    "gdrive:${DRIVE_FOLDER_ID}" \
    "$GCS_DEST" \
    --drive-root-folder-id="${DRIVE_FOLDER_ID}" \
    --transfers=8 \
    --checkers=16 \
    --stats=60s \
    --progress \
    --log-level INFO

echo "rclone copy complete."

# ---------------------------------------------------------------------------
# Generate dataset_manifest.json and upload to GCS
# ---------------------------------------------------------------------------
GCS_PREFIX="gs://${DEST_BUCKET}/${DEST_PREFIX}"
MANIFEST_LOCAL=/tmp/dataset_manifest.json
MANIFEST_GCS="${GCS_PREFIX}/dataset_manifest.json"

echo "Generating manifest at ${MANIFEST_GCS}…"
gcloud storage ls --json "${GCS_PREFIX}/" | python3 - <<'PYEOF'
import json, sys, datetime, os

objects = json.load(sys.stdin)
files = []
for obj in objects:
    name_full = obj.get("name", "")
    basename = name_full.rsplit("/", 1)[-1]
    if not basename or basename == "dataset_manifest.json":
        continue
    files.append({
        "name": basename,
        "size_bytes": int(obj.get("size", 0)),
        "updated": obj.get("updated", ""),
    })

manifest = {
    "schema_version": 1,
    "project": os.environ["DEST_PROJECT"],
    "dataset": os.environ["DEST_DATASET"],
    "bucket": os.environ["DEST_BUCKET"],
    "prefix": f"projects/{os.environ['DEST_PROJECT']}/inputs/{os.environ['DEST_DATASET']}",
    "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "file_count": len(files),
    "files": files,
}
with open("/tmp/dataset_manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)
print(f"Manifest: {len(files)} file(s)")
PYEOF

gcloud storage cp "$MANIFEST_LOCAL" "$MANIFEST_GCS"
echo "Manifest uploaded to ${MANIFEST_GCS}"
