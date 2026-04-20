# Post-runner-fix checklist

Everything in this list is **deliberately deferred** until the
`kardome_runner` SIGSEGV in `plugins/projects/sk` is fixed (or the
runner is replaced). Until then the pipeline runs in
**runner-tolerant** mode: the SK plugin treats per-WAV crashes as
soft failures, the BMT Gate ruleset is in **evaluate** mode on
`dev`, and Kardome-org/core-main's BMT pipeline still runs the
legacy `bmt/` flow rather than the PEX path.

The pieces below are not "TODOs" — they are validated, opt-in
switches that go live once a green real-runner BMT run exists.

## 0. Confirm the runner is actually fixed

Before flipping anything, the SK plugin must produce a green BMT
result on **real WAVs** (no `use_mock_runner: true`).

- [ ] `just sk-local-pipeline` against the curated 1-passer / N-crasher
  WAV subset returns 0 crashes (or all crashes are intentional and
  the verdict is still `pass`).
- [ ] Open a feature PR into `ci/check-bmt-gate` so `trigger-ci-pr.yml`
  fires `bmt-handoff.yml` **without** `use_mock_runner`. Both legs
  (`false_alarms`, `false_rejects`) finish with `status: pass` and a
  reason code other than `bootstrap_without_baseline` once the second
  run completes.
- [ ] Spot-check `gs://$GCS_BUCKET/projects/sk/results/.../current.json`
  for a real metric payload (non-zero `summary` fields,
  non-`mock_runner` `runner_id`).

If any of those steps regress, fix the runner before continuing —
none of the items below assume a flaky runner.

## 1. Promote the BMT Gate ruleset to `active`

The dry-run for the existing posture is already wired up:

```bash
tools/scripts/configure_branch_protection.sh \
    --repo klugman-yanai/bmt-gcloud --branch dev
```

Production state today (id **12946785**) is `enforcement: active`
on `dev` with `BMT Gate` pinned to integration id `2899213`.

When the runner is fixed:

- [ ] Update the existing ruleset to keep `enforcement: active`
  (no change required) and add `ci/check-bmt-gate` as a second
  protected branch. Run:

  ```bash
  tools/scripts/configure_branch_protection.sh \
      --repo klugman-yanai/bmt-gcloud \
      --branch ci/check-bmt-gate \
      --integration-id 2899213 \
      --enforce-active --apply
  ```

- [ ] Mirror onto Kardome-org/core-main `dev` (the existing ruleset
  id there is **13168599** — pass `--update 13168599` to PUT
  instead of POST):

  ```bash
  tools/scripts/configure_branch_protection.sh \
      --repo Kardome-org/core-main --branch dev \
      --update 13168599 --enforce-active --apply
  ```

- [ ] Confirm a sample PR cannot merge while the BMT Gate is
  pending or red.

## 2. Drop runner-tolerance fallbacks (only if it's actually safe)

These were added to keep the pipeline alive while the runner crashes.
With a stable runner they should be re-evaluated, **not** automatically
removed:

- [ ] `plugins/projects/sk/sk_scoring_policy.py` — review the
  per-leg crash tolerance (`_max_crash_ratio`, `_min_completed`).
  Tighten only if a real failure mode would otherwise slip past the
  gate; otherwise keep as-is so a partial outage still produces a
  human-readable verdict.
- [ ] `plugins/projects/sk/plugin.py` — the per-WAV
  try/except wrapper around `kardome_runner.run` was always
  intended as defense in depth. Keep it; remove only if a real
  benefit (e.g. fail-fast UX) outweighs lost resilience.
- [ ] `plugins/projects/e2e-test/plugin.py` — the synthetic plugin
  is the canary for the SDK contract. Keep it; bump it whenever
  `bmt_sdk.results` changes.

## 3. Flip Kardome-org/core-main's BMT pipeline onto the PEX path

Today:

- `core-main/.github/workflows/bmt-pex-smoke.yml` proves the runner
  can fetch and execute `bmt.pex` from `bmt-v0.2.0` and run
  `matrix parse-release-runners` against the real
  `CMakePresets.json`. PR #258 (chore/use-bmt-pex-v0-2-0).
- The legacy `core-main/.github/workflows/bmt.yml` still does
  `sparse-checkout: bmt/` + direct shell scripts. It is **not**
  using `bmt.pex` for the production matrix.

Once the runner is fixed and the smoke PR is merged into core-main
`dev`:

- [ ] Set repo vars on **Kardome-org/core-main**:

  ```bash
  gh variable set BMT_CLI       --repo Kardome-org/core-main --body pex
  gh variable set BMT_PEX_TAG   --repo Kardome-org/core-main --body bmt-v0.2.0
  gh variable set BMT_PEX_REPO  --repo Kardome-org/core-main --body klugman-yanai/bmt-gcloud
  ```

- [ ] Replace `bmt.yml`'s sparse-checkout + shell pipeline with a
  thin caller that vendors `.github/workflows/bmt-handoff.yml` (or
  a `workflow_call` reference into bmt-gcloud, if cross-repo
  reusable workflows are enabled for the org) and uses the
  vendored `setup-bmt-cli` composite to run BMT subcommands
  through `bmt.pex`. Cut the change as a PR labelled `bmt:cutover`
  so it's easy to roll back.
- [ ] Run `bmt-pex-smoke.yml` once on `dev` (`gh workflow run`)
  to confirm the workflow is registered post-merge for manual
  dispatch.

## 4. Refresh the live PEX tag (when bmt-gcloud cuts a new release)

- [ ] Push tag `bmt-v<next>` on `klugman-yanai/bmt-gcloud` →
  `build-kardome-bmt-pex.yml` builds and attaches `bmt.pex`.
- [ ] Bump `BMT_PEX_TAG` on **bmt-gcloud** and **core-main** repo
  vars (in lock-step).
- [ ] Re-dispatch `bmt-pex-smoke.yml` on core-main `dev` and
  `bmt-handoff-dev.yml` on bmt-gcloud `dev` to validate.

## 5. Cleanup / parking lot

These are pure ergonomics; do them only if they're paying for
their own maintenance:

- [ ] Delete `bmt-handoff-dev.yml` once the gate is enforced and
  the mock-runner end-to-end is no longer the primary debugging
  tool. (Until then it's the cheapest way to exercise the GHA →
  Workflows → Cloud Run plumbing without touching the runner.)
- [ ] Move `tools/scripts/run_sk_local_pipeline.py` and
  `tools/scripts/kardome_runner_one_wav_logged.py` under
  `tools/local/` if they survive the runner fix as ongoing
  maintenance tools (today they live under `tools/scripts/` because
  that's where ad-hoc dev helpers landed during the runner-crash
  triage).

## Reference

- Pipeline architecture: [docs/architecture.md](architecture.md)
- Configuration / repo vars: [docs/configuration.md](configuration.md)
- Workflow inventory: [.github/README.md](../.github/README.md)
- Branch-protection helper: [tools/scripts/configure_branch_protection.sh](../tools/scripts/configure_branch_protection.sh)
- Mock-runner handoff: [.github/workflows/bmt-handoff-dev.yml](../.github/workflows/bmt-handoff-dev.yml)
- Consumer-side smoke (core-main): `~/dev/kardome/core-main/.github/workflows/bmt-pex-smoke.yml`
