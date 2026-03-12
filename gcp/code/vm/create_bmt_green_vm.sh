#!/usr/bin/env bash
# Create a green VM from a pre-baked image while preserving core settings from current VM.
#
# Required env vars:
#   GCP_PROJECT, GCP_ZONE, BMT_VM_NAME
#
# Optional env vars:
#   BMT_GREEN_VM_NAME    (default: ${BMT_VM_NAME}-v2)
#   BMT_IMAGE_FAMILY     (default: bmt-runtime)
#   BMT_IMAGE_NAME       (optional explicit image; overrides family lookup)
#   BMT_GREEN_ALLOW_RECREATE (default: 0; set 1 to delete/recreate existing green VM)
#
# Example:
#   export GCP_PROJECT=... GCP_ZONE=europe-west4-a BMT_VM_NAME=bmt-performance-gate
#   export BMT_IMAGE_FAMILY=bmt-runtime
#   ./remote/code/vm/create_bmt_green_vm.sh

set -euo pipefail

GCP_PROJECT="${GCP_PROJECT:-}"
GCP_ZONE="${GCP_ZONE:-}"
BMT_VM_NAME="${BMT_VM_NAME:-}"
BMT_GREEN_VM_NAME="${BMT_GREEN_VM_NAME:-${BMT_VM_NAME}-v2}"
BMT_IMAGE_FAMILY="${BMT_IMAGE_FAMILY:-bmt-runtime}"
BMT_IMAGE_NAME="${BMT_IMAGE_NAME:-}"
BMT_GREEN_ALLOW_RECREATE="${BMT_GREEN_ALLOW_RECREATE:-0}"

if [[ -z "$GCP_PROJECT" || -z "$GCP_ZONE" || -z "$BMT_VM_NAME" ]]; then
  echo "Set GCP_PROJECT, GCP_ZONE, and BMT_VM_NAME." >&2
  exit 1
fi

for cmd in gcloud jq; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
done

if [[ -z "$BMT_IMAGE_NAME" ]]; then
  BMT_IMAGE_NAME="$(
    gcloud compute images describe-from-family "$BMT_IMAGE_FAMILY" \
      --project="$GCP_PROJECT" \
      --format='value(name)'
  )"
  if [[ -z "$BMT_IMAGE_NAME" ]]; then
    echo "Could not resolve image from family ${BMT_IMAGE_FAMILY} in project ${GCP_PROJECT}." >&2
    exit 1
  fi
fi

if gcloud compute instances describe "$BMT_GREEN_VM_NAME" \
  --project="$GCP_PROJECT" --zone="$GCP_ZONE" >/dev/null 2>&1; then
  if [[ "$BMT_GREEN_ALLOW_RECREATE" != "1" ]]; then
    echo "Green VM ${BMT_GREEN_VM_NAME} already exists. Set BMT_GREEN_ALLOW_RECREATE=1 to recreate." >&2
    exit 1
  fi
  echo "Deleting existing green VM ${BMT_GREEN_VM_NAME}..."
  gcloud compute instances delete "$BMT_GREEN_VM_NAME" \
    --project="$GCP_PROJECT" \
    --zone="$GCP_ZONE" \
    --quiet
fi

tmp_dir="$(mktemp -d -t bmt-green-vm-XXXXXX)"
trap 'rm -rf "$tmp_dir"' EXIT
base_json="${tmp_dir}/base-vm.json"
gcloud compute instances describe "$BMT_VM_NAME" \
  --project="$GCP_PROJECT" \
  --zone="$GCP_ZONE" \
  --format=json >"$base_json"

machine_type="$(jq -r '.machineType | split("/") | last' "$base_json")"
network="$(jq -r '.networkInterfaces[0].network // "" | split("/") | last' "$base_json")"
subnetwork="$(jq -r '.networkInterfaces[0].subnetwork // "" | split("/") | last' "$base_json")"
service_account="$(jq -r '.serviceAccounts[0].email // ""' "$base_json")"
scopes="$(jq -r '(.serviceAccounts[0].scopes // []) | join(",")' "$base_json")"
tags="$(jq -r '(.tags.items // []) | join(",")' "$base_json")"
boot_disk_source="$(jq -r '(.disks // [] | map(select(.boot == true)) | .[0].source // "" | split("/") | last)' "$base_json")"
boot_disk_size_gb="$(jq -r '(.disks // [] | map(select(.boot == true)) | .[0].diskSizeGb) // ""' "$base_json")"
boot_disk_type=""
if [[ -n "$boot_disk_source" ]]; then
  boot_disk_type_uri="$(
    gcloud compute disks describe "$boot_disk_source" \
      --project="$GCP_PROJECT" \
      --zone="$GCP_ZONE" \
      --format='value(type)' 2>/dev/null || true
  )"
  if [[ -n "$boot_disk_type_uri" ]]; then
    boot_disk_type="${boot_disk_type_uri##*/}"
  fi
  boot_disk_size_from_disk="$(
    gcloud compute disks describe "$boot_disk_source" \
      --project="$GCP_PROJECT" \
      --zone="$GCP_ZONE" \
      --format='value(sizeGb)' 2>/dev/null || true
  )"
  if [[ -n "$boot_disk_size_from_disk" ]]; then
    boot_disk_size_gb="$boot_disk_size_from_disk"
  fi
fi
gcs_bucket="$(jq -r '((.metadata.items // []) | map(select(.key=="GCS_BUCKET")) | .[0].value) // ""' "$base_json")"
bmt_repo_root="$(jq -r '((.metadata.items // []) | map(select(.key=="BMT_REPO_ROOT")) | .[0].value) // "/opt/bmt"' "$base_json")"
startup_script="$(jq -r '((.metadata.items // []) | map(select(.key=="startup-script")) | .[0].value) // ""' "$base_json")"
startup_script_url="$(jq -r '((.metadata.items // []) | map(select(.key=="startup-script-url")) | .[0].value) // ""' "$base_json")"

metadata_pairs=(
  "GCS_BUCKET=${gcs_bucket}"
  "BMT_REPO_ROOT=${bmt_repo_root}"
  "bmt_image_family=${BMT_IMAGE_FAMILY}"
  "bmt_image_version=${BMT_IMAGE_NAME}"
  "bmt_bake_timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
)
if [[ -n "$startup_script_url" ]]; then
  metadata_pairs+=("startup-script-url=${startup_script_url}")
else
  metadata_pairs+=("startup-script-url=")
fi

family_label="$(printf '%s' "$BMT_IMAGE_FAMILY" | tr '[:upper:]_' '[:lower:]-' | tr -cd 'a-z0-9-')"
version_label="$(printf '%s' "$BMT_IMAGE_NAME" | tr '[:upper:]_' '[:lower:]-' | tr -cd 'a-z0-9-')"
ts_label="$(date -u +%Y%m%d-%H%M%S)"
labels="bmt-image-family=${family_label},bmt-image-version=${version_label},bmt-bake-timestamp=${ts_label}"

create_cmd=(
  gcloud compute instances create "$BMT_GREEN_VM_NAME"
  --project="$GCP_PROJECT"
  --zone="$GCP_ZONE"
  --machine-type="$machine_type"
  --image="$BMT_IMAGE_NAME"
  --metadata "$(IFS=,; echo "${metadata_pairs[*]}")"
  --labels "$labels"
)
if [[ -n "$network" ]]; then
  create_cmd+=(--network="$network")
fi
if [[ -n "$subnetwork" ]]; then
  create_cmd+=(--subnet="$subnetwork")
fi
if [[ -n "$service_account" ]]; then
  create_cmd+=(--service-account="$service_account")
fi
if [[ -n "$scopes" ]]; then
  create_cmd+=(--scopes="$scopes")
fi
if [[ -n "$boot_disk_size_gb" ]]; then
  create_cmd+=(--boot-disk-size="${boot_disk_size_gb}GB")
fi
if [[ -n "$boot_disk_type" ]]; then
  create_cmd+=(--boot-disk-type="$boot_disk_type")
fi
if [[ -n "$tags" ]]; then
  create_cmd+=(--tags="$tags")
fi
if [[ -n "$startup_script" ]]; then
  startup_script_file="${tmp_dir}/startup-script.sh"
  printf '%s\n' "$startup_script" >"$startup_script_file"
  create_cmd+=(--metadata-from-file "startup-script=${startup_script_file}")
fi

echo "Creating green VM ${BMT_GREEN_VM_NAME} from image ${BMT_IMAGE_NAME}..."
echo "Inherited boot disk profile: size=${boot_disk_size_gb:-<default>}GB type=${boot_disk_type:-<default>}"
"${create_cmd[@]}"

echo "Green VM created:"
echo "  vm:       ${BMT_GREEN_VM_NAME}"
echo "  image:    ${BMT_IMAGE_NAME}"
echo "  labels:   ${labels}"
echo "  gcs:      ${gcs_bucket}"
echo "  repoRoot: ${bmt_repo_root}"
