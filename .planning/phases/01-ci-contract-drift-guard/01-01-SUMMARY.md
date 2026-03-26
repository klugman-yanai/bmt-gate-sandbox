---
phase: 01-ci-contract-drift-guard
plan: 01
subsystem: infra
tags: [ci, portability, contract, drift-test]
requires: []
provides:
  - CI-local env/default contract modules for portable handoff code
  - Parity coverage that guards the copied contract against runtime drift
affects: [phase-2, phase-3, portability]
tech-stack:
  added: []
  patterns: [ci-owned-contract-surface, runtime-parity-tests]
key-files:
  created:
    - .github/bmt/ci/env_contract.py
    - .github/bmt/ci/gate_contract.py
    - .github/bmt/ci/env_parse.py
    - .github/bmt/ci/workflow_links.py
    - tests/ci/test_ci_contract_parity.py
  modified:
    - .planning/REQUIREMENTS.md
    - .planning/ROADMAP.md
key-decisions:
  - "Keep the contract split small: env/defaults, gate helpers, env parsing, and workflow links."
  - "Guard copied behavior with parity tests instead of runtime imports in the CI package."
patterns-established:
  - "Portable CI code can mirror runtime SSOT through local constants/helpers plus drift tests."
  - "Runtime imports remain isolated to tests until call sites are rewritten in later phases."
requirements-completed: [PORT-01]
duration: 20min
completed: 2026-03-26
---

# Phase 1: CI contract + drift guard Summary

**Portable CI contract modules now mirror the runtime defaults, gate helpers, and workflow link logic, with a dedicated parity test proving drift-free behavior**

## Performance

- **Duration:** 20 min
- **Started:** 2026-03-26T00:00:00Z
- **Completed:** 2026-03-26T00:20:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Added CI-local contract modules for env/default values, gate decisions, run-id sanitization, truthy parsing, and workflow console URLs.
- Documented the exact `.github/bmt/ci` dependency surface that currently points at `gcp.image`.
- Added `tests/ci/test_ci_contract_parity.py` and verified it passes against the runtime SSOT.

## Task Commits

This autonomous run intentionally left the workspace uncommitted because the repo already contains unrelated in-progress user changes. Phase evidence is captured in the planning artifacts and test output instead.

## Files Created/Modified
- `.github/bmt/ci/env_contract.py` - CI-local copy of the env/default and decision-string contract.
- `.github/bmt/ci/gate_contract.py` - Local `GateDecision` enum and `sanitize_run_id` helper.
- `.github/bmt/ci/env_parse.py` - Local truthy env parsing helper.
- `.github/bmt/ci/workflow_links.py` - Local workflow console URL formatter.
- `tests/ci/test_ci_contract_parity.py` - Drift/parity test for the copied contract surface.
- `.planning/REQUIREMENTS.md` - Added milestone requirement traceability.
- `.planning/ROADMAP.md` - Added requirement mappings for each roadmap phase.

## Decisions Made
- Kept phase 1 read-only with respect to existing `.github/bmt/ci` call sites so phase 2 can switch imports with a tested replacement already available.
- Mirrored only the runtime symbols that `.github/bmt/ci` actually uses today to keep the drift surface narrow.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Sandbox pytest plugins prevented a normal test invocation**
- **Found during:** Task 2 (parity test verification)
- **Issue:** The repo’s default pytest addopts/plugins require sockets that are blocked in this sandbox.
- **Fix:** Verified the new test with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and `-o addopts=''` so the code could be exercised without the sandbox-only plugin failure.
- **Files modified:** None
- **Verification:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -o addopts='' tests/ci/test_ci_contract_parity.py -v`
- **Committed in:** None

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** No code scope changed; only the verification command was adjusted to account for sandbox constraints.

## Issues Encountered
None beyond the sandbox-specific pytest plugin restriction during verification.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- The CI package now has a tested local contract surface ready for call-site rewrites.
- Phase 2 can replace `.github/bmt/ci` runtime imports and remove the `bmt-gcloud` package dependency.

---
*Phase: 01-ci-contract-drift-guard*
*Completed: 2026-03-26*
