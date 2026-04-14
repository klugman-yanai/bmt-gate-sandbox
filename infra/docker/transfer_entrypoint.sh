#!/usr/bin/env bash
# Cloud Run entrypoint for the bmt-dataset-transfer job.
# Copies a Google Drive folder to GCS using rclone, then generates a dataset manifest.
#
# Required env vars (injected as Cloud Run secrets):
#   BMT_DRIVE_CLIENT_ID     — OAuth2 Desktop app client ID
#   BMT_DRIVE_CLIENT_SECRET — OAuth2 client secret
#   BMT_DRIVE_REFRESH_TOKEN — OAuth2 refresh token (drive.readonly scope)
#
# Required env vars (set by caller via --update-env-vars):
#   DRIVE_FOLDER_ID  — Google Drive folder ID to copy from
#   DEST_PROJECT     — BMT project slug (e.g. "sk")
#   DEST_DATASET     — Dataset name (e.g. "false_alarms")
#   DEST_BUCKET      — GCS bucket name
set -euo pipefail

# ---------------------------------------------------------------------------
# Validate required env vars
# ---------------------------------------------------------------------------
missing=()
for var in DRIVE_FOLDER_ID DEST_PROJECT DEST_DATASET DEST_BUCKET \
           BMT_DRIVE_CLIENT_ID BMT_DRIVE_CLIENT_SECRET BMT_DRIVE_REFRESH_TOKEN; do
    if [[ -z "${!var:-}" ]]; then
        missing+=("$var")
    fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "::error::Missing required env vars: ${missing[*]}" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Write rclone config with OAuth2 token
# Uses Python to safely construct the token JSON without shell escaping issues.
# GCS backend uses Workload Identity (ADC) — no credentials needed.
# ---------------------------------------------------------------------------
python3 - <<'PYEOF'
import json, os

client_id     = os.environ["BMT_DRIVE_CLIENT_ID"]
client_secret = os.environ["BMT_DRIVE_CLIENT_SECRET"]
refresh_token = os.environ["BMT_DRIVE_REFRESH_TOKEN"]

token_json = json.dumps({
    "access_token": "ya29.placeholder",  # non-empty so rclone triggers a refresh
    "token_type": "Bearer",
    "refresh_token": refresh_token,
    "expiry": "2020-01-01T00:00:00Z",  # clearly past; rclone will exchange refresh_token
})

config = (
    "[gdrive]\n"
    "type = drive\n"
    f"client_id = {client_id}\n"
    f"client_secret = {client_secret}\n"
    f"token = {token_json}\n"
    "\n"
    "[gcs]\n"
    "type = google cloud storage\n"
)

os.makedirs(os.path.expanduser("~/.config/rclone"), exist_ok=True)
with open(os.path.expanduser("~/.config/rclone/rclone.conf"), "w") as f:
    f.write(config)
print("rclone.conf written")
PYEOF

# ---------------------------------------------------------------------------
# Run rclone copy: Drive folder → GCS destination prefix
# ---------------------------------------------------------------------------
DEST_PREFIX="projects/${DEST_PROJECT}/inputs/${DEST_DATASET}"
GCS_DEST="gcs:${DEST_BUCKET}/${DEST_PREFIX}/"

echo "Copying Google Drive folder ${DRIVE_FOLDER_ID} → gs://${DEST_BUCKET}/${DEST_PREFIX}/"
# gdrive: (empty path) — drive-root-folder-id makes that folder the remote root.
rclone copy \
    "gdrive:" \
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
