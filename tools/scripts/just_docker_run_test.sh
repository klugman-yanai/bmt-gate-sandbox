#!/usr/bin/env bash
set -euo pipefail
exec docker run --rm -v ./plugins:/mnt/runtime:ro -e BMT_CONFIG=/etc/bmt/config.json bmt-orchestrator:latest "$@"
