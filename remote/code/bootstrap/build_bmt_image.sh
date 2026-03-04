#!/usr/bin/env bash
# Build a pre-baked BMT runtime image (deps preinstalled, code still synced at runtime).
# Uses bucket code as source of truth for bake content.
#
# Required env vars:
#   GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, GCS_BUCKET
#
# Optional env vars:
#   BMT_IMAGE_FAMILY                (default: bmt-runtime)
#   BMT_IMAGE_NAME                  (default: <family>-YYYYMMDD-HHMMSS)
#   BMT_BASE_IMAGE_FAMILY           (default: ubuntu-2204-lts)
#   BMT_BASE_IMAGE_PROJECT          (default: ubuntu-os-cloud)
#   BMT_IMAGE_BUILDER_MACHINE_TYPE  (default: e2-standard-4)
#   BMT_IMAGE_BUILDER_VM_NAME       (default: <BMT_VM_NAME>-image-builder-<timestamp>)
#   BMT_KEEP_IMAGE_BUILDER          (default: 0; set 1 for debugging failures)
#
# Example:
#   export GCP_PROJECT=... GCP_ZONE=europe-west4-a BMT_VM_NAME=bmt-performance-gate GCS_BUCKET=...
#   ./remote/code/bootstrap/build_bmt_image.sh

set -euo pipefail

GCP_PROJECT="${GCP_PROJECT:-}"
GCP_ZONE="${GCP_ZONE:-}"
BMT_VM_NAME="${BMT_VM_NAME:-}"
GCS_BUCKET="${GCS_BUCKET:-}"

BMT_IMAGE_FAMILY="${BMT_IMAGE_FAMILY:-bmt-runtime}"
BMT_BASE_IMAGE_FAMILY="${BMT_BASE_IMAGE_FAMILY:-ubuntu-2204-lts}"
BMT_BASE_IMAGE_PROJECT="${BMT_BASE_IMAGE_PROJECT:-ubuntu-os-cloud}"
BMT_IMAGE_BUILDER_MACHINE_TYPE="${BMT_IMAGE_BUILDER_MACHINE_TYPE:-e2-standard-4}"
BMT_KEEP_IMAGE_BUILDER="${BMT_KEEP_IMAGE_BUILDER:-0}"

if [[ -z "$GCP_PROJECT" || -z "$GCP_ZONE" || -z "$BMT_VM_NAME" || -z "$GCS_BUCKET" ]]; then
  echo "Set GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, and GCS_BUCKET." >&2
  exit 1
fi

for cmd in gcloud jq python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
done

timestamp="$(date -u +%Y%m%d-%H%M%S)"
BMT_IMAGE_NAME="${BMT_IMAGE_NAME:-${BMT_IMAGE_FAMILY}-${timestamp}}"
BMT_IMAGE_BUILDER_VM_NAME="${BMT_IMAGE_BUILDER_VM_NAME:-${BMT_VM_NAME}-image-builder-${timestamp}}"
tmp_dir="$(mktemp -d -t bmt-image-build-XXXXXX)"
builder_created=0
builder_deleted=0

wait_for_ssh() {
  local instance="$1"
  local retries="${2:-30}"
  local delay_sec="${3:-5}"
  local attempt
  for attempt in $(seq 1 "$retries"); do
    if gcloud compute ssh "$instance" \
      --project="$GCP_PROJECT" \
      --zone="$GCP_ZONE" \
      --quiet \
      --command "echo ready" >/dev/null 2>&1; then
      echo "SSH ready on ${instance} (attempt ${attempt}/${retries})."
      return 0
    fi
    echo "Waiting for SSH on ${instance} (${attempt}/${retries})..."
    sleep "$delay_sec"
  done
  echo "::error::SSH did not become ready on ${instance} within timeout." >&2
  return 1
}

cleanup() {
  if [[ "$BMT_KEEP_IMAGE_BUILDER" != "1" && "$builder_created" -eq 1 && "$builder_deleted" -eq 0 ]]; then
    echo "Cleaning up builder VM ${BMT_IMAGE_BUILDER_VM_NAME}..."
    gcloud compute instances delete "$BMT_IMAGE_BUILDER_VM_NAME" \
      --project="$GCP_PROJECT" \
      --zone="$GCP_ZONE" \
      --quiet >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

echo "Reading source VM spec from ${BMT_VM_NAME}..."
base_json="${tmp_dir}/base-vm.json"
gcloud compute instances describe "$BMT_VM_NAME" \
  --project="$GCP_PROJECT" \
  --zone="$GCP_ZONE" \
  --format=json >"$base_json"

base_sa="$(jq -r '.serviceAccounts[0].email // ""' "$base_json")"
base_scopes="$(jq -r '(.serviceAccounts[0].scopes // []) | join(",")' "$base_json")"
base_network="$(jq -r '.networkInterfaces[0].network // "" | split("/") | last' "$base_json")"
base_subnetwork="$(jq -r '.networkInterfaces[0].subnetwork // "" | split("/") | last' "$base_json")"
base_tags="$(jq -r '(.tags.items // []) | join(",")' "$base_json")"

create_cmd=(
  gcloud compute instances create "$BMT_IMAGE_BUILDER_VM_NAME"
  --project="$GCP_PROJECT"
  --zone="$GCP_ZONE"
  --machine-type="$BMT_IMAGE_BUILDER_MACHINE_TYPE"
  --image-family="$BMT_BASE_IMAGE_FAMILY"
  --image-project="$BMT_BASE_IMAGE_PROJECT"
)
if [[ -n "$base_sa" ]]; then
  create_cmd+=(--service-account="$base_sa")
fi
if [[ -n "$base_scopes" ]]; then
  create_cmd+=(--scopes="$base_scopes")
fi
if [[ -n "$base_network" ]]; then
  create_cmd+=(--network="$base_network")
fi
if [[ -n "$base_subnetwork" ]]; then
  create_cmd+=(--subnet="$base_subnetwork")
fi
if [[ -n "$base_tags" ]]; then
  create_cmd+=(--tags="$base_tags")
fi

echo "Creating builder VM ${BMT_IMAGE_BUILDER_VM_NAME}..."
"${create_cmd[@]}"
builder_created=1

wait_for_ssh "$BMT_IMAGE_BUILDER_VM_NAME"

echo "Syncing bucket code locally from gs://${GCS_BUCKET}/code ..."
mkdir -p "${tmp_dir}/code"
gcloud storage rsync "gs://${GCS_BUCKET}/code" "${tmp_dir}/code" --recursive

if [[ ! -f "${tmp_dir}/code/bootstrap/install_deps.sh" ]]; then
  echo "::error::Bucket code sync is missing bootstrap/install_deps.sh" >&2
  exit 1
fi

echo "Uploading code snapshot to builder VM..."
gcloud compute scp --recurse "${tmp_dir}/code" "${BMT_IMAGE_BUILDER_VM_NAME}:/tmp/bmt-code" \
  --project="$GCP_PROJECT" \
  --zone="$GCP_ZONE" \
  --quiet

echo "Installing VM dependencies on builder..."
gcloud compute ssh "$BMT_IMAGE_BUILDER_VM_NAME" \
  --project="$GCP_PROJECT" \
  --zone="$GCP_ZONE" \
  --quiet \
  --command "
    set -euo pipefail
    sudo rm -rf /opt/bmt
    sudo mkdir -p /opt/bmt
    sudo cp -a /tmp/bmt-code/. /opt/bmt/
    if [[ -f /opt/bmt/_tools/uv/linux-x86_64/uv ]]; then
      sudo chmod +x /opt/bmt/_tools/uv/linux-x86_64/uv
      sudo BMT_UV_BIN=/opt/bmt/_tools/uv/linux-x86_64/uv bash /opt/bmt/bootstrap/install_deps.sh /opt/bmt
    elif command -v uv >/dev/null 2>&1; then
      sudo bash /opt/bmt/bootstrap/install_deps.sh /opt/bmt
    else
      echo '::error::No uv binary found (neither /opt/bmt/_tools/uv nor PATH uv).' >&2
      exit 1
    fi
    sudo python3 - <<'PY'
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

repo = Path('/opt/bmt')
def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ''

manifest = {
    'bake_timestamp_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'image_source': {
        'bucket': '${GCS_BUCKET}',
        'code_prefix': 'code/'
    },
    'deps_fingerprint': hashlib.sha256(
        (digest(repo / 'pyproject.toml') + digest(repo / 'uv.lock')).encode('utf-8')
    ).hexdigest(),
    'pyproject_sha256': digest(repo / 'pyproject.toml'),
    'uv_lock_sha256': digest(repo / 'uv.lock'),
    'uv_binary_sha256': digest(repo / '_tools/uv/linux-x86_64/uv'),
}
(repo / '.image_manifest.json').write_text(json.dumps(manifest, indent=2) + '\\n', encoding='utf-8')
PY
  "

echo "Stopping builder VM..."
gcloud compute instances stop "$BMT_IMAGE_BUILDER_VM_NAME" \
  --project="$GCP_PROJECT" \
  --zone="$GCP_ZONE" \
  --quiet

family_label="$(printf '%s' "$BMT_IMAGE_FAMILY" | tr '[:upper:]_' '[:lower:]-' | tr -cd 'a-z0-9-')"
version_label="$(printf '%s' "$BMT_IMAGE_NAME" | tr '[:upper:]_' '[:lower:]-' | tr -cd 'a-z0-9-')"
ts_label="$(date -u +%Y%m%d-%H%M%S)"
labels="bmt-image-family=${family_label},bmt-image-version=${version_label},bmt-bake-timestamp=${ts_label}"

echo "Creating image ${BMT_IMAGE_NAME} (family=${BMT_IMAGE_FAMILY})..."
gcloud compute images create "$BMT_IMAGE_NAME" \
  --project="$GCP_PROJECT" \
  --source-disk="$BMT_IMAGE_BUILDER_VM_NAME" \
  --source-disk-zone="$GCP_ZONE" \
  --family="$BMT_IMAGE_FAMILY" \
  --labels="$labels"

if [[ "$BMT_KEEP_IMAGE_BUILDER" != "1" ]]; then
  echo "Deleting builder VM ${BMT_IMAGE_BUILDER_VM_NAME}..."
  gcloud compute instances delete "$BMT_IMAGE_BUILDER_VM_NAME" \
    --project="$GCP_PROJECT" \
    --zone="$GCP_ZONE" \
    --quiet
  builder_deleted=1
else
  echo "Keeping builder VM per BMT_KEEP_IMAGE_BUILDER=1"
fi

echo "Image build complete:"
echo "  image:   ${BMT_IMAGE_NAME}"
echo "  family:  ${BMT_IMAGE_FAMILY}"
echo "  labels:  ${labels}"
