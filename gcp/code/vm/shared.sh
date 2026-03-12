#!/usr/bin/env bash
# Shared logging helpers for VM scripts. Source from the same directory:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   . "${SCRIPT_DIR}/shared.sh"
#   _bmt_log_tag="script_name"   # set before first _log call
#
# Callers must set _bmt_log_tag for meaningful log prefixes. Default is "vm".

_bmt_log_tag="${_bmt_log_tag:-vm}"
_log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [${_bmt_log_tag}] $*"; }
_log_err() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [${_bmt_log_tag}] $*" >&2; }
