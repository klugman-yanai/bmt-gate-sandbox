# PEX Build and Publish — Design Spec

**Date:** 2026-04-12  
**Branch:** `ci/check-bmt-gate`  
**Status:** Approved for implementation

---

## Goal

Replace the `uv sync` setup pattern in CI with a single self-contained `bmt.pex` binary, published as a GitHub Release artifact on `klugman-yanai/bmt-gcloud`. Consuming repos (starting with `Kardome-org/core-main`) download the PEX via a GitHub Action during their CI — no source checkout of `.github/bmt/`, no uv, no dep resolution at run time.

---

## Context

The `bmt` Python package lives at `.github/bmt/` and is a uv workspace member. Currently every workflow that needs `uv run bmt <cmd>` calls `uv sync` first, which resolves and installs the full dependency tree at CI start. Three locations on `ci/check-bmt-gate`:

| File | Where `uv sync` is called |
|---|---|
| `.github/actions/bmt-prepare-context/action.yml` | Step: "Sync BMT" |
| `.github/actions/setup-gcp-uv/action.yml` | Step: "Sync" |
| `.github/workflows/build-and-test.yml` | Step in `repo_snapshot` job |

---

## Components

### 1. `build-pex.yml` — Release workflow

**Trigger:** Push of tags matching `bmt-v*` (e.g. `bmt-v0.1.0`).

**Steps:**
1. Checkout
2. `uv sync` — resolves workspace, gives `pex` tool access
3. `uv build --package bmt-gcloud --wheel` → `dist/bmt_gcloud-*.whl`
4. `uv build --package bmt --wheel` → `dist/bmt-*.whl`
5. `uv tool install pex`
6. Build PEX:
   ```
   pex bmt bmt-gcloud \
     --find-links dist/ \
     --no-index \
     --entry-point ci.driver:main \
     --python-shebang '/usr/bin/env python3' \
     -o dist/bmt.pex
   ```
7. Create GitHub Release + upload `bmt.pex` via `softprops/action-gh-release@v2`

**Why `--find-links dist/ --no-index`:** `bmt-gcloud` is not on PyPI; the locally-built wheel satisfies the `bmt` package's `bmt-gcloud` dependency without a registry lookup.

**Tag format:** `bmt-v<semver>` — prefix avoids collision with other repo tags. Example: `bmt-v0.1.0`.

---

### 2. `.github/actions/bmt-get-pex/action.yml` — Download action

Composite action. Inputs:

| Input | Default | Purpose |
|---|---|---|
| `repo` | `klugman-yanai/bmt-gcloud` | Source repo — update here if org changes |
| `tag` | *(required)* | e.g. `bmt-v0.1.0` |
| `token` | `${{ github.token }}` | For cross-repo download |
| `out-path` | `.` | Directory to place `bmt.pex` |

**Steps:**
1. `robinraju/release-downloader@v1` — downloads `bmt.pex` from the release
2. `chmod +x ${{ inputs.out-path }}/bmt.pex`

**Pinning:** `robinraju/release-downloader` pinned to a commit SHA in the action (not floating `@v1`) per supply-chain security practice.

---

### 3. Updated integration points

Three existing files gain a `bmt-get-pex` call and lose `uv sync`:

**`.github/actions/bmt-prepare-context/action.yml`**
- Add inputs: `bmt-repo` (default `klugman-yanai/bmt-gcloud`), `bmt-tag` (required)
- Replace "Sync BMT" step (`uv sync`) with `bmt-get-pex` call
- Replace `uv run bmt <cmd>` invocations with `./bmt.pex <cmd>`

**`.github/actions/setup-gcp-uv/action.yml`**
- Same pattern: add `bmt-repo` + `bmt-tag` inputs, swap `uv sync` for `bmt-get-pex`
- Keep `setup-uv` step only if other repo code still needs it (verify during implementation)

**`.github/workflows/build-and-test.yml`**
- `repo_snapshot` job: replace `uv sync` step with `bmt-get-pex` call
- All `uv run bmt` invocations → `./bmt.pex`

---

### 4. `just build-pex` recipe

Local smoke-test path — runs steps 2–6 of `build-pex.yml` without creating a release, outputs `dist/bmt.pex`. Lets you run `./dist/bmt.pex --help` to verify the binary before tagging.

---

## Flexibility: repo move

When `klugman-yanai/bmt-gcloud` moves to `Kardome-org/<new-name>`:
- Change the `repo` default in `bmt-get-pex/action.yml` — one line
- Consuming repos (core-main) only need to update their `bmt-repo` input value

---

## Data flow

```
[bmt-gcloud: push bmt-v* tag]
        │
        ▼
build-pex.yml
  uv build wheels → pex bundle → bmt.pex
  softprops/action-gh-release → GitHub Release (klugman-yanai/bmt-gcloud)

[core-main: PR/push triggers CI]
        │
        ▼
bmt-prepare-context/action.yml
  bmt-get-pex (robinraju/release-downloader → bmt.pex, chmod +x)
  ./bmt.pex write-context
  ./bmt.pex runner filter-upload-matrix
        │
        ▼
bmt-handoff.yml
  ./bmt.pex dispatch invoke-workflow
  ...
```

---

## Out of scope

- Publishing to PyPI (not needed; GitHub Releases is the distribution channel)
- Versioning automation (caller tags manually; semver policy TBD)
- core-main workflow changes (separate PR to Kardome-org/core-main after sandbox validates)

---

## Testing plan

1. `just build-pex` locally → `./dist/bmt.pex --help` passes
2. Push `bmt-v0.1.0` tag → `build-pex.yml` runs → release appears on GitHub with `bmt.pex`
3. Trigger `bmt-handoff.yml` on sandbox (`klugman-yanai/bmt-gate-sandbox`) with PEX-based action — full handoff completes
4. Only after sandbox passes: propose workflow change to `Kardome-org/core-main` via PR
