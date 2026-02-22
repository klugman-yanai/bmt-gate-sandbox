#!/usr/bin/env bash
# SSH into the BMT VM and run dependency install (uv sync --extra vm) so deps are
# persistent on the VM's disk across stop/start. Run from your laptop; requires gcloud.
#
# Set (or export) before running (required: GCP_ZONE, VM_NAME; GCP_PROJECT or GCP_SA_EMAIL):
#   GCP_PROJECT   - GCP project ID (optional if GCP_SA_EMAIL set; derived from SA email)
#   GCP_SA_EMAIL  - Service account email (used to derive GCP_PROJECT when unset)
#   GCP_ZONE      - VM zone (e.g. europe-west4-a)
#   VM_NAME       - VM instance name (or BMT_VM_NAME)
#   BMT_REPO_ROOT - Path to repo on the VM (default: /opt/bmt)
#
# Example:
#   export GCP_SA_EMAIL=... GCP_ZONE=europe-west4-a VM_NAME=bmt-vm
#   ./remote/bootstrap/ssh_install.sh

set -euo pipefail

BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"

# Derive GCP_PROJECT from GCP_SA_EMAIL when unset
if [[ -z "${GCP_PROJECT:-}" && -n "${GCP_SA_EMAIL:-}" ]]; then
  if [[ "${GCP_SA_EMAIL}" =~ @(.+)\.iam\.gserviceaccount\.com ]]; then
    GCP_PROJECT="${BASH_REMATCH[1]}"
  fi
fi

if [[ -z "${GCP_PROJECT:-}" || -z "${GCP_ZONE:-}" || -z "${VM_NAME:-}" ]]; then
  echo "Set GCP_ZONE, VM_NAME (or BMT_VM_NAME), and GCP_PROJECT or GCP_SA_EMAIL." >&2
  echo "Example: GCP_SA_EMAIL=... GCP_ZONE=europe-west4-a VM_NAME=bmt-vm $0" >&2
  exit 1
fi

# Ensure uv is installed on the VM, then run install_deps so .venv is created/updated on persistent disk
gcloud compute ssh "$VM_NAME" \
  --zone="$GCP_ZONE" \
  --project="$GCP_PROJECT" \
  -- \
  'if ! command -v uv &>/dev/null; then curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; fi; cd '"$BMT_REPO_ROOT"' && ./remote/bootstrap/install_deps.sh '"$BMT_REPO_ROOT"
