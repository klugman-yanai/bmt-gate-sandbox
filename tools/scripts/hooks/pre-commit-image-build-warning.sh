#!/usr/bin/env bash
# Pre-commit hook: warn when committing under image-affecting paths.
# Does not block; reminds to run BMT Image Build for this branch (or rely on push trigger).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
staged="$(git diff --cached --name-only | grep -E '^(infra/packer/|gcp/code/bootstrap/)' || true)"
if [[ -n "${staged//[[:space:]]/}" ]]; then
	echo "::notice::You changed image-affecting paths (infra/packer or gcp/code/bootstrap)."
	echo "Ensure BMT Image Build runs before merging: push to trigger it, or run the workflow manually from the Actions tab."
fi
exit 0
