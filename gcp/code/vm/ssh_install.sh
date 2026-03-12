#!/usr/bin/env bash
# SSH into the BMT VM and run dependency install (pip) so deps are
# persistent on the VM's disk across stop/start. Run from your laptop; requires gcloud.
#
# Set (or export) before running (required: GCP_PROJECT, GCP_ZONE, BMT_VM_NAME):
#   GCP_PROJECT   - GCP project ID
#   GCP_ZONE      - VM zone (e.g. europe-west4-a)
#   BMT_VM_NAME   - VM instance name
#   BMT_REPO_ROOT - Path to repo on the VM (default: /opt/bmt)
#
# Example:
#   export GCP_PROJECT=... GCP_ZONE=europe-west4-a BMT_VM_NAME=bmt-vm
#   ./gcp/code/vm/ssh_install.sh

set -euo pipefail

_log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [ssh_install] $*"; }
_log_err() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [ssh_install] $*" >&2; }

BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"
GCP_PROJECT="${GCP_PROJECT:-}"
GCP_ZONE="${GCP_ZONE:-}"
BMT_VM_NAME="${BMT_VM_NAME:-}"

if [[ -z "$GCP_PROJECT" || -z "$GCP_ZONE" || -z "$BMT_VM_NAME" ]]; then
	_log_err "::error::Set GCP_PROJECT, GCP_ZONE, and BMT_VM_NAME."
	_log_err "Example: GCP_PROJECT=... GCP_ZONE=europe-west4-a BMT_VM_NAME=bmt-vm $0"
	exit 1
fi

_log "Running install_deps.sh on ${BMT_VM_NAME} (${BMT_REPO_ROOT})..."
gcloud compute ssh "$BMT_VM_NAME" \
	--zone="$GCP_ZONE" \
	--project="$GCP_PROJECT" \
	-- \
	"set -euo pipefail; \
   cd '${BMT_REPO_ROOT}'; \
   ./vm/install_deps.sh '${BMT_REPO_ROOT}'"
_log "Done."
