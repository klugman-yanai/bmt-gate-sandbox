# DRY and YAML organization in `.github/`

Recommendations for reducing duplication and keeping workflow/action config maintainable.

**Note:** actionlint (and GitHub’s workflow schema) do not allow custom top-level keys or YAML merge keys (`<<`). So branch-list anchors, permission anchors, and job merge keys are not used in this repo; branches and permissions are repeated where needed.

## 1. **Branch lists (build-and-test.yml)**

**Current:** Same branch list repeated for `push.branches` and `pull_request.branches`.

**DRY:** Define once with a YAML anchor (GitHub ignores custom top-level keys but resolves anchors).

```yaml
# Branches that trigger CI (push + pull_request). Update in one place.
x-ci-branches: &ci-branches
  - dev
  - ci/check-bmt-gate
  - test/check-bmt-gate-*
  - test/workflow-optimizations
  - test/*

on:
  push:
    branches: *ci-branches
  pull_request:
    branches: *ci-branches
```

**BMT gate branches** (e.g. `contains(fromJson('["dev", "ci/check-bmt-gate"]'), ...)`) can stay as-is or reference a second anchor if you want a single source of truth for “branches that run BMT” (e.g. `x-bmt-gate-branches: &bmt-gate-branches ["dev", "ci/check-bmt-gate"]` and use `fromJson(toJson(*bmt-gate-branches))` in the expression—or keep the inline JSON for clarity).

---

## 2. **BMT input resolution (bmt.yml)**

**Current:** Long expressions repeated many times:
- `${{ inputs.head_sha || github.event.inputs.head_sha || github.sha }}`
- `${{ inputs.head_branch || github.event.inputs.head_branch || github.ref_name }}`
- `${{ inputs.ci_run_id || github.event.inputs.ci_run_id }}`
- etc.

**DRY:** GitHub Actions does not support workflow-level “computed” values that jobs can reference. Two options:

- **Option A (minimal):** Add a single “resolver” job that runs first, outputs e.g. `head_sha`, `head_branch`, `run_id`, and have every other job `needs` it and use `needs.resolve.outputs.head_sha`. That adds a dependency and more wiring.
- **Option B (pragmatic):** Keep the expressions but document the pattern in one place (e.g. in this doc or a comment at the top of `bmt.yml`) and accept repetition. Optional: use a YAML anchor for a **multi-line string** that you don’t actually use as a value, just as a “template” comment so the exact expression is written once and copied when editing (anchors can’t inject into `${{ }}`).

**Recommendation:** Option B plus a short comment in `bmt.yml` listing the canonical expressions, so future edits stay consistent.

---

## 3. **Third-party action versions (single source of truth)**

**Current:** Pinned SHAs for the same actions appear in multiple files:

| Action | Used in |
|--------|--------|
| `actions/checkout@de0fac2e...` # v6 | build-and-test, bmt, bmt-image-build, bmt-vm-provision, bmt-job-setup |
| `actions/download-artifact@70fc10c6...` # v8 | build-and-test (×2), bmt, bmt-job-setup (×2) |
| `actions/upload-artifact@bbbca2dd...` # v7 | build-and-test, bmt-image-build |
| `google-github-actions/auth@7c6bc77...` # v3 | setup-gcp-uv only (bmt-image-build, bmt-vm-provision use it) |
| `google-github-actions/setup-gcloud@aa5489c8...` # v3.0.1 | setup-gcp-uv only |
| `astral-sh/setup-uv@65ef9077...` # v7 | bmt-image-build, bmt-job-setup, bmt-prepare, setup-gcp-uv |

**DRY:** GitHub Actions does not support “variables” for action refs in the sense of a single global pin. You can:

- **Centralize in composite actions:** You already do this for `setup-gcp-uv` (auth + gcloud + uv). `bmt-image-build.yml` and `bmt-vm-provision.yml` use raw `auth` + `setup-gcloud` instead of `setup-gcp-uv`. Switching them to `setup-gcp-uv` would remove duplicate auth/gcloud pins and make upgrades one-place (in `setup-gcp-uv/action.yml`).
- **Document pins in one place:** Add a `.github/docs/action-versions.md` (or a comment in README) that lists each action and the single pinned SHA to use when adding new workflows, so at least the “source of truth” is documented even if YAML can’t reference it.

**Recommendation:** Prefer using `setup-gcp-uv` in `bmt-image-build.yml` and `bmt-vm-provision.yml` where you only need GCP + optional uv (image build can pass `install_uv: true` for the provenance step). Then document the remaining pins (checkout, upload-artifact, download-artifact) in `.github/docs/action-versions.md`.

---

## 4. **Dummy build jobs (build-and-test.yml)**

**Current:** `dummy-build-release` and `dummy-build-non-release` are almost identical (only the matrix output name differs: `release_presets` vs `non_release_presets`).

**DRY:** Use a single job with a matrix that includes both “release” and “non-release” presets (e.g. one matrix with a `type: release | non-release` and the preset list per type). That would require restructuring the matrix so one job runs over the union of presets with a type flag. Alternatively, keep two jobs for clarity and use a YAML anchor for the common structure (steps, permissions, env):

```yaml
x-dummy-build-common: &dummy-build-common
  needs: [prepare-builds]
  runs-on: ubuntu-latest
  permissions:
    contents: read
    actions: write
  env:
    GRADLE_USER_HOME: ${{ github.workspace }}/.gradle
  steps:
    - name: Download repo-snapshot
      uses: actions/download-artifact@70fc10c6e5e1ce46ad2ea6f2b72d43f7d47b13c3 # v8
      with:
        name: repo-snapshot
    - name: Extract repo snapshot
      run: tar -xzf repo-snapshot.tar.gz -C .
    - name: Dummy build ( ${{ matrix.short }} )
      run: |
        echo "Sandbox dummy build for ${{ matrix.short }} - no real compile."

  dummy-build-release:
    <<: *dummy-build-common
    strategy:
      fail-fast: false
      max-parallel: 6
      matrix:
        include: ${{ fromJson(needs.prepare-builds.outputs.release_presets) }}

  dummy-build-non-release:
    <<: *dummy-build-common
    strategy:
      fail-fast: false
      max-parallel: 6
      matrix:
        include: ${{ fromJson(needs.prepare-builds.outputs.non_release_presets) }}
```

Merge keys (`<<: *anchor`) are valid in GitHub Actions YAML and reduce duplication.

---

## 5. **BMT “Checkout repo (for local actions)” step (bmt.yml)**

**Current:** The same step block appears in several jobs (setup, upload-runners, handshake, handoff): checkout sparse `.github` then `bmt-job-setup` with ref/run-id/token.

**DRY:** `bmt-job-setup` now does checkout (sparse .github), download+extract repo-snapshot, uv, sync, load-env in one composite. The workflow still has a first "Checkout repo (for local actions)" step so the runner has `.github` and can resolve the local action; then `bmt-job-setup` runs (and does its own checkout + restore so ref/run-id are correct). The repetition of that two-step pattern across jobs is structural. Actionlint does not support YAML merge keys, so a shared step-list anchor is not used. The workflow uses “Checkout” (sparse .github) then “bmt-job-setup” because job-setup expects the repo to be checked out first (for local actions). You can’t fold the sparse checkout into bmt-job-setup without making the action do a checkout itself (and losing the ability to pass different ref/run-id per job). So the repetition is structural. You can still reduce it with a YAML anchor for the **step list** that’s identical across jobs:

```yaml
x-bmt-repo-and-setup-steps: &bmt-repo-and-setup
  - name: Checkout repo (for local actions)
    uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6
    with:
      ref: ${{ inputs.head_sha || github.event.inputs.head_sha || github.sha }}
      fetch-depth: 1
      sparse-checkout: .github
  - uses: ./.github/actions/bmt-job-setup
    with:
      ref: ${{ inputs.head_sha || github.event.inputs.head_sha || github.sha }}
      run-id: ${{ inputs.ci_run_id || github.event.inputs.ci_run_id }}  # or needs.setup.outputs.run_id
      github-token: ${{ secrets.GITHUB_TOKEN }}
```

Each job would then use `steps: *bmt-repo-and-setup` and append its specific steps. The `run-id` differs (inputs.ci_run_id vs needs.setup.outputs.run_id), so you’d need two anchors (e.g. `bmt-repo-and-setup-with-run-id` and `bmt-repo-and-setup-with-needs-run-id`) or accept one repeated step block. Given that, a single anchor used in jobs that share the same run-id source might be enough for the “checkout + bmt-job-setup” pair in setup and handoff (which use inputs), and a second for upload-runners/handshake (which use needs.setup.outputs.run_id). Optional refinement; the current repetition is still manageable.

---

## 6. **Permissions**

**Current:** Several jobs use `permissions: contents: read; actions: write` or `id-token: write` etc.

**DRY:** You already introduced `x-bmt-caller-permissions` for the BMT workflow call. You can add:

- `x-build-job-permissions: &build-job-permissions` → `contents: read`, `actions: write` for prepare-builds, dummy-build-release, dummy-build-non-release.
- In `bmt.yml`, job-level permissions are already minimal (e.g. `id-token: write`). No need to anchor unless you add more jobs with the same block.

---

## 7. **Concurrency group pattern**

**Current:** `concurrency.group` uses a long expression in build-and-test and bmt.

**DRY:** No shared concurrency across workflows; each workflow’s group is appropriate as-is. Optional: document the pattern (e.g. `ci-${{ github.repository }}-${{ ... }}`) in this doc for consistency when adding new workflows.

---

## 8. **actionlint config and variables**

**Current:** `actionlint.yaml` holds the list of config variables. `bmt.yml` and other workflows reference the same variable names.

**DRY:** actionlint’s config is already the single place for “known variables.” Keep it. If you add more workflows that use the same vars, they’re already consistent by name; no change needed.

---

## 9. **GCP/auth in bmt-image-build and bmt-vm-provision**

**Current:** Both workflows use inline `google-github-actions/auth` + `google-github-actions/setup-gcloud` instead of `setup-gcp-uv`.

**DRY:** Use `setup-gcp-uv` in both, with `install_uv: true` where you need uv (e.g. bmt-image-build for provenance), and `install_uv: false` where you only need GCP (e.g. bmt-vm-provision if it doesn’t run Python/uv). That way auth and gcloud versions live only in `setup-gcp-uv/action.yml`.

---

## Summary (priority)

| Priority | Item | Status |
|----------|------|--------|
| High | Use setup-gcp-uv in bmt-image-build and bmt-vm-provision | Done |
| Medium | Document action pins | Done (`.github/docs/action-versions.md`) |
| Low | BMT input resolution comment in bmt.yml | Done |
| — | Branch list / dummy-build merge key (anchors) | Not used (actionlint does not support custom keys or `<<`) |
