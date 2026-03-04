## CI Checkout Reliability Plan (Core-Main + Sandbox, Native Minimal)

### Summary
Implement a minimal, GitHub-native hardening pass to reduce recurring checkout timeouts without changing core BMT logic.  
Scope is both repos, with parity on shared BMT workflow logic and targeted CI changes in core-main.

This plan is based on observed failures:
- Multiple jobs timing out exactly at 10m during `actions/checkout` fetch phase.
- Same SHA succeeding in some jobs while failing in others, indicating transient git transport + checkout pressure, not a bad commit.
- BMT prep checkout failing independently, causing handoff cascade failure.

### Root Cause (Decision-locked)
1. Checkout failures are predominantly transient fetch/network/git-ops failures under load.
2. Current workflow topology can create high overlapping checkout pressure (release/nonrelease/BMT jobs).
3. Secondary correctness risk exists in `bmt.yml` due to mixed SHA/reference usage in `prepare` vs downstream jobs (not primary cause of current timeouts, but should be fixed).

---

### Scope
1. `Kardome-org/core-main` (primary)
- [build-and-test.yml](/home/yanai/kardome/core-main/.github/workflows/build-and-test.yml)
- [bmt.yml](/home/yanai/kardome/core-main/.github/workflows/bmt.yml)

2. `klugman-yanai/bmt-gate-sandbox` (mirror for shared behavior)
- [bmt.yml](/home/yanai/sandbox/bmt-gcloud/.github/workflows/bmt.yml)
- Keep sandbox-only files (`dummy-build-and-test.yml`, env/secrets) repo-specific unless explicitly required.

---

### Important Interface / Contract Changes
1. No public API or secret-name contract changes.
2. Internal workflow contract changes:
- Checkout retry semantics added to additional jobs.
- BMT `prepare` checkout ref source made explicit/consistent with handoff inputs.
- Nonrelease matrix concurrency reduced in core-main for lower contention.

---

### Implementation Plan

#### Phase 1: Normalize checkout ref correctness in BMT workflow
1. Update `prepare` checkout ref in both repos’ `bmt.yml`:
- Replace `ref: ${{ github.sha }}` with `ref: ${{ inputs.head_sha || github.event.inputs.head_sha || github.sha }}`.
2. Keep downstream jobs on `needs.prepare.outputs.head_sha`.
3. Add one guard step in `prepare` summary/log:
- Print resolved checkout ref and head SHA.
4. Goal:
- Eliminate SHA divergence edge-case risk across call/dispatch paths.

#### Phase 2: Add native bounded checkout retries in BMT hot jobs
1. In both repos’ `bmt.yml`, convert single-checkout jobs to bounded 2-attempt pattern:
- Jobs: `prepare`, `classify-handoff`, `handoff`, `failure-fallback`.
- Attempt 1: `actions/checkout@v4`, `timeout-minutes: 10`, `continue-on-error: true`.
- Backoff: `sleep 10`.
- Attempt 2: `actions/checkout@v4`, `timeout-minutes: 15`, `fetch-depth: 0`.
2. In `upload-runners` (already has two attempts):
- Keep two attempts.
- Change attempt 2 to `fetch-depth: 0` and `timeout-minutes: 15`.
3. Goal:
- Recover from transient shallow-fetch and transport failures while keeping retry bounded.

#### Phase 3: Reduce checkout pressure in core-main CI
1. In `core-main` `build-and-test.yml`:
- Keep `build-release max-parallel: 12` (release-first requirement unchanged).
- Reduce `build-nonrelease max-parallel` from `6` to `4`.
2. Add same bounded checkout retry to `build-nonrelease` checkout step:
- Attempt 1: depth 1, 10m.
- Attempt 2: depth 0, 15m.
3. Keep release checkout retry as-is but align attempt 2 to depth 0 + 15m for consistency.
4. Goal:
- Preserve release-first/BMT-start behavior while lowering concurrent fetch pressure and timeout rate.

#### Phase 4: Keep branch-scoped cancellation strict
1. Keep existing workflow `concurrency` in CI and BMT workflows.
2. Ensure both repos keep `cancel-in-progress: true` on branch-scoped groups.
3. Goal:
- Prevent stale runs from consuming checkout capacity during rapid-commit testing.

#### Phase 5: Sync shared BMT logic from core-main to sandbox
1. Mirror final `bmt.yml` changes from core-main into sandbox.
2. Do not force-sync repo-specific workflow files (`build-and-test.yml` vs `dummy-build-and-test.yml`).
3. Goal:
- Shared handoff behavior remains aligned for validation fidelity.

---

### Validation Plan

#### Static validation
1. Run `actionlint` on:
- core-main [build-and-test.yml](/home/yanai/kardome/core-main/.github/workflows/build-and-test.yml)
- core-main [bmt.yml](/home/yanai/kardome/core-main/.github/workflows/bmt.yml)
- sandbox [bmt.yml](/home/yanai/sandbox/bmt-gcloud/.github/workflows/bmt.yml)

#### Functional validation (sandbox first)
1. Push one commit to sandbox test branch and confirm:
- BMT `prepare` checkout succeeds.
- No `Checkout timed out after 10 minutes`.
2. Push two quick follow-up commits to same branch:
- Older run canceled by concurrency.
- Latest run proceeds with retry logic only when needed.

#### Functional validation (core-main)
1. Merge PR to `ci/check-bmt-gate`.
2. Confirm:
- Release jobs complete.
- BMT handoff starts.
- No checkout timeout in `BMT Handoff / 01 Prepare Context`.
3. Trigger one additional run (empty commit) to check reproducibility.

#### Acceptance criteria
1. 3 consecutive `ci/check-bmt-gate` runs with zero checkout-timeout failures in:
- `BMT Handoff / 01 Prepare Context`
- `BMT Handoff / 02 Upload Runners*`
- Any release/nonrelease build checkout steps
2. Retry steps may execute, but final checkout succeeds without manual reruns.

---

### Rollout Order
1. Implement in sandbox `bmt.yml`, validate once.
2. Implement in core-main `build-and-test.yml` + `bmt.yml`.
3. Run controlled PR merge to `ci/check-bmt-gate`.
4. Run one reproducibility commit.
5. Keep monitoring for 24 hours of active commits.

---

### Rollback Plan
1. If runtime increases too much:
- Revert only timeout/depth retry hunk for nonrelease first.
2. If behavior regresses in BMT handoff:
- Revert only `bmt.yml` checkout retry changes.
3. If throughput impact is unacceptable:
- Restore `build-nonrelease max-parallel` from 4 back to 6 while keeping retries.

---

### Explicit Assumptions / Defaults
1. Use native minimal hardening (no new custom checkout action).
2. Keep release-first strategy intact.
3. Keep BMT branch scope as currently configured.
4. Partial transient GitHub fetch issues may still occur; objective is to make them non-fatal in normal load.
