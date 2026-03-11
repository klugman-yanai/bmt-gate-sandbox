#!/usr/bin/env bash
# Pre-push hook: block direct pushes from ci/check-bmt-gate.
set -euo pipefail

if [[ "${ALLOW_DIRECT_CI_PUSH:-}" == "1" ]]; then
  exit 0
fi

current_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [[ "$current_branch" == "ci/check-bmt-gate" ]]; then
  cat <<'EOF' >&2
ERROR: direct push from ci/check-bmt-gate is blocked by policy.
Treat ci/check-bmt-gate like dev: use feature branch + PR.

Emergency bypass (explicit): ALLOW_DIRECT_CI_PUSH=1 git push ...
EOF
  exit 1
fi

exit 0
