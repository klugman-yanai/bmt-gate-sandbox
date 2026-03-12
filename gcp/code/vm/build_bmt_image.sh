#!/usr/bin/env bash
# Build a pre-baked BMT runtime image (code + deps baked into /opt/bmt).
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
#   BMT_EXPECTED_IMAGE_FAMILY       (default: bmt-runtime)
#   BMT_EXPECTED_BASE_IMAGE_FAMILY  (default: ubuntu-2204-lts)
#   BMT_IMAGE_BUILDER_MACHINE_TYPE  (default: e2-standard-4)
#   BMT_IMAGE_BUILDER_VM_NAME       (default: <BMT_VM_NAME>-image-builder-<timestamp>)
#   BMT_KEEP_IMAGE_BUILDER          (default: 0; set 1 for debugging failures)
#
# Example:
#   export GCP_PROJECT=... GCP_ZONE=europe-west4-a BMT_VM_NAME=bmt-performance-gate GCS_BUCKET=...
#   ./remote/code/vm/build_bmt_image.sh

set -euo pipefail

GCP_PROJECT="${GCP_PROJECT:-}"
GCP_ZONE="${GCP_ZONE:-}"
BMT_VM_NAME="${BMT_VM_NAME:-}"
GCS_BUCKET="${GCS_BUCKET:-}"

BMT_IMAGE_FAMILY="${BMT_IMAGE_FAMILY:-bmt-runtime}"
BMT_BASE_IMAGE_FAMILY="${BMT_BASE_IMAGE_FAMILY:-ubuntu-2204-lts}"
BMT_BASE_IMAGE_PROJECT="${BMT_BASE_IMAGE_PROJECT:-ubuntu-os-cloud}"
BMT_EXPECTED_IMAGE_FAMILY="${BMT_EXPECTED_IMAGE_FAMILY:-bmt-runtime}"
BMT_EXPECTED_BASE_IMAGE_FAMILY="${BMT_EXPECTED_BASE_IMAGE_FAMILY:-ubuntu-2204-lts}"
BMT_IMAGE_BUILDER_MACHINE_TYPE="${BMT_IMAGE_BUILDER_MACHINE_TYPE:-e2-standard-4}"
BMT_KEEP_IMAGE_BUILDER="${BMT_KEEP_IMAGE_BUILDER:-0}"

if [[ -z "$GCP_PROJECT" || -z "$GCP_ZONE" || -z "$BMT_VM_NAME" || -z "$GCS_BUCKET" ]]; then
	echo "::error::Set GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, and GCS_BUCKET. See script header for required env." >&2
	exit 1
fi

if [[ "${BMT_IMAGE_FAMILY}" != "${BMT_EXPECTED_IMAGE_FAMILY}" ]]; then
	echo "::error::Image family policy violation: got '${BMT_IMAGE_FAMILY}', expected '${BMT_EXPECTED_IMAGE_FAMILY}'." >&2
	exit 1
fi
if [[ "${BMT_BASE_IMAGE_FAMILY}" != "${BMT_EXPECTED_BASE_IMAGE_FAMILY}" ]]; then
	echo "::error::Base image family policy violation: got '${BMT_BASE_IMAGE_FAMILY}', expected '${BMT_EXPECTED_BASE_IMAGE_FAMILY}'." >&2
	exit 1
fi

for cmd in gcloud jq python3; do
	if ! command -v "$cmd" >/dev/null 2>&1; then
		echo "::error::Missing required command: $cmd. Install it and re-run." >&2
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
	echo "::error::SSH did not become ready on ${instance} within timeout. Check VM boot and network; re-run or set BMT_KEEP_IMAGE_BUILDER=1 to debug." >&2
	return 1
}

# Retry a command up to max_attempts times with exponential backoff (delay_sec, 2*delay, 4*delay...).
_retry() {
	local max_attempts="$1"
	local delay_sec="$2"
	shift 2
	local attempt=1
	while true; do
		if "$@"; then
			return 0
		fi
		if [[ "$attempt" -ge "$max_attempts" ]]; then
			return 1
		fi
		echo "Attempt ${attempt}/${max_attempts} failed; retrying in ${delay_sec}s..."
		sleep "$delay_sec"
		attempt=$((attempt + 1))
		delay_sec=$((delay_sec * 2))
	done
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
_retry 3 5 gcloud storage rsync "gs://${GCS_BUCKET}/code" "${tmp_dir}/code" --recursive

if [[ ! -f "${tmp_dir}/code/vm/install_deps.sh" ]]; then
	echo "::error::Bucket code sync is missing vm/install_deps.sh. Run just sync-gcp and ensure GCS_BUCKET has code/ synced." >&2
	exit 1
fi

if [[ ! -f "${tmp_dir}/code/vm/vm_deps.txt" ]]; then
	echo "::error::Bucket code sync is missing vm/vm_deps.txt. Sync gcp/code to the bucket and re-run." >&2
	exit 1
fi

echo "Uploading code snapshot to builder VM..."
gcloud compute scp --recurse "${tmp_dir}/code" "${BMT_IMAGE_BUILDER_VM_NAME}:/tmp/bmt-code" \
	--project="$GCP_PROJECT" \
	--zone="$GCP_ZONE" \
	--quiet

_run_builder_install() {
	gcloud compute ssh "$BMT_IMAGE_BUILDER_VM_NAME" \
		--project="$GCP_PROJECT" \
		--zone="$GCP_ZONE" \
		--quiet \
		--command "
    set -euo pipefail
    sudo rm -rf /opt/bmt
    sudo mkdir -p /opt/bmt
    sudo cp -a /tmp/bmt-code/. /opt/bmt/
    GLIBC_VERSION_RAW=\$(ldd --version 2>/dev/null | head -n1 || true)
    printf 'GLIBC_VERSION=%s\n' \"\$GLIBC_VERSION_RAW\" | sudo tee /tmp/bmt-image-build-meta.env >/dev/null
    echo 'Installing Google Cloud Ops Agent for Cloud Logging...'
    curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
    sudo bash add-google-cloud-ops-agent-repo.sh --also-install
    rm -f add-google-cloud-ops-agent-repo.sh
    echo 'Installing Python 3.12 via deadsnakes PPA...'
    for attempt in 1 2 3; do
      sudo add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null && break
      [[ \$attempt -lt 3 ]] && sleep \$((attempt * 5)) || exit 1
    done
    for attempt in 1 2 3; do
      sudo apt-get update -q && sudo apt-get install -y -q python3.12 python3.12-venv python3.12-dev && break
      [[ \$attempt -lt 3 ]] && sleep \$((attempt * 10)) || exit 1
    done
    sudo bash /opt/bmt/vm/install_deps.sh /opt/bmt
    sudo python3 - <<'PY'
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

repo = Path('/opt/bmt')
build_meta = {}
meta_path = Path('/tmp/bmt-image-build-meta.env')
if meta_path.exists():
    for line in meta_path.read_text(encoding='utf-8').splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        build_meta[key.strip()] = value.strip()
def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ''

manifest = {
    'bake_timestamp_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'image_family': '${BMT_IMAGE_FAMILY}',
    'base_image_family': '${BMT_BASE_IMAGE_FAMILY}',
    'base_image_project': '${BMT_BASE_IMAGE_PROJECT}',
    'image_source': {
        'bucket': '${GCS_BUCKET}',
        'code_prefix': 'code/'
    },
    'deps_fingerprint': digest(repo / 'pyproject.toml'),
    'pyproject_sha256': digest(repo / 'pyproject.toml'),
    'glibc_version': build_meta.get('GLIBC_VERSION', ''),
}
(repo / '.image_manifest.json').write_text(json.dumps(manifest, indent=2) + '\\n', encoding='utf-8')
PY
    # Reset cloud-init instance state before image capture.
    # Without this, cloned VMs can inherit stale state and delay/skip startup sequencing.
    if command -v cloud-init >/dev/null 2>&1; then
      sudo cloud-init clean --logs --machine-id || sudo cloud-init clean --logs
    fi
  "
}

echo "Installing VM dependencies on builder..."
_retry 2 15 _run_builder_install

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
