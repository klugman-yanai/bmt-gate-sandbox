# CI-driven release Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement task-by-task. Steps use `- [ ]` checkbox syntax. Do not skip phase gates.

**Goal:** Eliminate the four-surface drift class of failures (stale Cloud Run image, stale GCS plugins, stale Pulumi vars, stale PEX) by making CI the **only** producer of any artifact the BMT pipeline consumes. Merges to `ci/check-bmt-gate` (and release tag pushes) atomically update all four surfaces, write a single release marker, and only then dispatch the BMT handoff. Laptops keep escape hatches for local iteration but not for production-consumed surfaces.

**Resolves:** Open question 1 of [`docs/brainstorms/2026-03-23-container-image-identity-ship-brainstorm.md`](../../brainstorms/2026-03-23-container-image-identity-ship-brainstorm.md) — *"Should CI be the only producer of prod images?"*. Answer: **yes**, extended to plugins and Pulumi.

**Architecture:**

```
push to ci/check-bmt-gate
        │
        ▼
  release.yml ─── concurrency: release-${{ github.ref }}
    ├─ test             (just test — fail fast; no side effects yet)
    ├─ image            (conditional: diff touches runtime/** | Dockerfile | pyproject.toml | uv.lock)
    │                    push :latest + :${GIT_SHA}; capture manifest digest
    ├─ plugins          (conditional: diff touches plugins/**)
    │                    uv run python -m tools bucket deploy
    ├─ pulumi           (conditional: diff touches infra/pulumi/**)
    │                    uv run python -m tools pulumi apply (WIF-authed; GCS state backend)
    ├─ mark             (always)
    │                    write gs://$BUCKET/_state/release.json =
    │                      { git_sha, image_digest, plugins_sha, pex_tag, pulumi_stack_sha, built_at }
    └─ handoff          (always)
                         workflow_call → bmt-handoff.yml
                             └─ Plan job asserts release.json.git_sha == github.sha
```

**Tech stack:** GitHub Actions (reusable workflows, WIF), `tools/cli/*.py` (existing build/bucket/pulumi commands), Artifact Registry (manifest digest via `gcloud artifacts docker tags list`), `gs://$BUCKET/_state/` (new prefix).

**Decisions (resolved in discussion 2026-04-18):**

| # | Decision | Choice |
|---|---|---|
| D1 | Preflight lives where? | Release marker + assertion (not a preflight diff). Marker is ground truth. |
| D2 | Mismatch mode? | Hard-fail — Plan job aborts with `release workflow did not complete for <sha>`. |
| D3 | What triggers release? | Path-filtered per-step (image/plugins/pulumi steps each have their own filter); release.yml itself always runs. |
| D4 | Surfaces covered v1? | All four: image + plugins + Pulumi + PEX. |
| D5 | Laptop escape hatches? | Remove `just deploy`. Keep `just image` as `just image-debug` with explicit warning. `just ship` demoted to docs-only emergency recipe. |
| D6 | Trigger events? | `push: ci/check-bmt-gate` **and** `push: tags: bmt-v*` (PEX release path). |
| D7 | Pulumi backend? | GCS-backed (`gs://$BUCKET/pulumi-state-…`) — WIF covers it, **no new secret needed**. |

---

## File Map

| File | Action |
|---|---|
| `.github/workflows/release.yml` | **Create** — new orchestrating workflow |
| `.github/workflows/bmt-handoff.yml` | **Modify** — drop `push` trigger for `ci/check-bmt-gate` (keep `workflow_call` + `workflow_dispatch`); Plan job reads + asserts release marker |
| `.github/workflows/build-and-test*.yml` | **Modify** — ensure PR trigger stays; remove any duplicated cloud-affecting steps |
| `ci/kardome_bmt/release_marker.py` | **Create** — read/write `gs://$BUCKET/_state/release.json` + assertion helper |
| `ci/kardome_bmt/runner.py` | **Modify** — `write_handoff_context` calls the assertion before dispatching |
| `tools/cli/release_cmd.py` | **Create** — `bmt release mark-and-verify` subcommand wiring the marker helpers into the PEX CLI |
| `tools/scripts/just_docker_push.sh` | **Modify** — emit pushed manifest digest to stdout (consumed by `release.yml`) |
| `tools/cli/bucket_cmd.py` | **Modify** — compute plugins tree-sha (sorted path+content hash) during `deploy`; emit to stdout |
| `tools/pulumi/pulumi_apply.py` | **Modify** — emit pulumi stack sha from `pulumi stack export` digest; accept `--ci` flag for WIF-backed auth |
| `Justfile` | **Modify** — remove `deploy`, rename `image` → `image-debug`, demote `ship`, add `release-check` target (local dry-run) |
| `CLAUDE.md` | **Modify** — update CI/BMT section to reflect CI-only release path |
| `docs/architecture.md` | **Modify** — document the four-surface lifecycle |
| `tests/ci/test_release_marker.py` | **Create** — unit tests for marker write/read/assert |
| `tests/ci/test_release_cmd.py` | **Create** — CLI integration tests |

---

## Phases and gates

Each phase is one logical PR or direct push to `ci/check-bmt-gate`. **A phase does not start until the previous phase's CI run is fully green end-to-end.** This matches the existing discipline ("no more PRs that don't trigger full e2e").

---

## Phase A — Release marker plumbing (additive, no behavior change)

**Goal:** Add the ability to read/write the release marker and the assertion helper. Everything still goes through laptop `just ship` for now. CI unchanged.

### Task A.1: Release marker module

- Create: `ci/kardome_bmt/release_marker.py`
- [ ] Implement `ReleaseMarker` dataclass: `{git_sha, image_digest, plugins_sha, pex_tag, pulumi_stack_sha, built_at}`
- [ ] `write(bucket: str, marker: ReleaseMarker) -> None` — writes to `gs://{bucket}/_state/release.json` atomically (write to `release.json.new`, then rename)
- [ ] `read(bucket: str) -> ReleaseMarker | None` — returns `None` if missing (first-run case)
- [ ] `assert_matches(bucket: str, git_sha: str) -> None` — raises `ReleaseMarkerMismatchError` with actionable message if mismatch, passes silently if match, fails loudly if missing
- [ ] All GCS access via existing `google-cloud-storage` client helper in `tools/shared/`; no new deps

### Task A.2: Unit tests for the marker module

- Create: `tests/ci/test_release_marker.py`
- [ ] `test_write_then_read_roundtrip` — uses `fakestorage` or monkey-patched client
- [ ] `test_read_missing_returns_none`
- [ ] `test_assert_matches_ok` / `test_assert_matches_mismatch` / `test_assert_matches_missing`
- [ ] `test_mismatch_message_contains_remediation` — verify the error string names the release workflow

### Task A.3: CLI wiring

- Create: `tools/cli/release_cmd.py`
- [ ] Add `bmt release mark` subcommand: reads env (`GIT_SHA`, `IMAGE_DIGEST`, …), calls `ReleaseMarker.write`
- [ ] Add `bmt release verify --sha <sha>` subcommand: calls `assert_matches`, exits non-zero on mismatch
- [ ] Register in `tools/__main__.py` alongside other `Typer` app mounts
- Create: `tests/ci/test_release_cmd.py` — integration tests against the CLI

### Gate A — e2e verification

- [ ] `just test` green
- [ ] Direct push to `ci/check-bmt-gate`; existing `bmt-handoff.yml` unchanged; full pipeline still passes
- [ ] Manually run `uv run python -m tools release verify --sha $(git rev-parse HEAD)` — expected to fail with "marker missing" (proves the error path is wired)
- [ ] Manually run `uv run python -m tools release mark` with test env — inspect `gs://$BUCKET/_state/release.json`

---

## Phase B — `release.yml` workflow (additive, shadows existing trigger)

**Goal:** CI builds image, deploys plugins, runs Pulumi (conditional), writes marker, invokes handoff. Existing `bmt-handoff.yml` push trigger is **temporarily kept** so any misbehavior in `release.yml` doesn't kill CI entirely. At phase end we flip the trigger.

### Task B.1: Emit digests/shas from existing recipes

- Modify: `tools/scripts/just_docker_push.sh`
- [ ] After `docker push`, `gcloud artifacts docker tags list` → resolve `:${GIT_SHA}` to manifest digest; emit to stdout as `IMAGE_DIGEST=<sha256:…>`; also write to `${GITHUB_OUTPUT}` when set
- Modify: `tools/cli/bucket_cmd.py` `deploy` command
- [ ] After sync, compute `plugins_sha = sha256(sorted list of "path:content_hash\n")` over `plugins/projects/**` + `plugins/shared/**`; emit `PLUGINS_SHA=<hex>`
- Modify: `tools/pulumi/pulumi_apply.py`
- [ ] After `pulumi up`, emit `PULUMI_STACK_SHA=<sha256 of pulumi stack export>`
- [ ] Add `--ci` flag: when set, use WIF-provided credentials (ADC) instead of `gcloud auth login` check

### Task B.2: release.yml

- Create: `.github/workflows/release.yml`
- [ ] Triggers: `push: branches: [ci/check-bmt-gate]` and `push: tags: [bmt-v*]`
- [ ] `concurrency: group: release-${{ github.ref }}, cancel-in-progress: false`
- [ ] Permissions: `contents: read, id-token: write` (WIF)
- [ ] Jobs:
  - `detect-changes` — `dorny/paths-filter@v3` with `runtime`, `plugins`, `infra` filters
  - `test` — `just test` (matches existing)
  - `image` — `if: needs.detect-changes.outputs.runtime == 'true' || startsWith(github.ref, 'refs/tags/bmt-v')`; runs `just image`; captures `IMAGE_DIGEST`
  - `plugins` — `if: needs.detect-changes.outputs.plugins == 'true'`; runs `uv run python -m tools bucket deploy`; captures `PLUGINS_SHA`
  - `pulumi` — `if: needs.detect-changes.outputs.infra == 'true'`; runs `uv run python -m tools pulumi apply --ci`; captures `PULUMI_STACK_SHA`
  - `mark` — `needs: [test, image, plugins, pulumi]`, `if: always() && !failure() && !cancelled()`; assembles marker from job outputs (empty/previous values when steps skipped via `always()` + resolve-existing) and runs `uv run python -m tools release mark`
  - `handoff` — `needs: [mark]`, `uses: ./.github/workflows/bmt-handoff.yml` with `secrets: inherit` (requires B.3)
- [ ] Step summary: aggregated "Release marker" table at the top of the run summary

### Task B.3: bmt-handoff as reusable workflow

- Modify: `.github/workflows/bmt-handoff.yml`
- [ ] Add `on: workflow_call:` with required `inputs: release_git_sha` and secrets passthrough
- [ ] **Keep** the existing `push` and `workflow_dispatch` triggers during Phase B — do not remove yet
- [ ] Plan job reads release marker via `uv run python -m tools release verify --sha ${{ github.sha }}`; fails with actionable error on mismatch

### Task B.4: Tests

- Extend `tests/ci/test_release_marker.py` with a test that simulates the full write-then-verify CLI chain using `subprocess`

### Gate B — e2e verification

- [ ] Direct push to `ci/check-bmt-gate` with a no-op change to `runtime/` (forces image rebuild)
- [ ] Verify: `release.yml` ran, image step fired, plugins step skipped (unchanged), pulumi skipped, marker written
- [ ] Verify: `bmt-handoff.yml` ran via both `push` trigger (legacy) and `workflow_call` (new) — they both succeed
  - (The push-triggered one will also run `assert_matches` and succeed because the release.yml one already wrote the marker)
- [ ] Verify: BMT Gate status check posts green
- [ ] Verify: `gs://$BUCKET/_state/release.json` has correct git_sha and image_digest

---

## Phase C — Flip the trigger, remove escape hatches

**Goal:** `release.yml` becomes the sole entry to the cloud pipeline. Laptop recipes that touched cloud artifacts are removed or demoted.

### Task C.1: Flip bmt-handoff trigger

- Modify: `.github/workflows/bmt-handoff.yml`
- [ ] **Remove** `on: push:` block entirely
- [ ] Keep `workflow_call` (used by release.yml) and `workflow_dispatch` (emergency manual trigger)
- [ ] Update README / `.github/README.md` to reflect new trigger topology

### Task C.2: Remove / demote laptop recipes

- Modify: `Justfile`
- [ ] **Delete** `deploy` recipe (`uv run python -m tools bucket deploy`)
- [ ] **Rename** `image` → `image-debug`; add warning banner: `*** This tags :latest — the next CI release will overwrite. Use only for local Cloud Run emulation. ***`
- [ ] **Demote** `ship` recipe: keep it but its first line is `@echo "WARN: \`just ship\` bypasses CI. Prefer merging to ci/check-bmt-gate. Use --force to continue."` and require `--force` flag
- [ ] **Keep** `test`, `release-check`, `pulumi` (local preview), and all bucket read-only recipes

### Task C.3: Docs cutover

- Modify: `CLAUDE.md`
- [ ] Update "CI / BMT CLI" section: CI is now the single producer
- [ ] Update "Devtools and pre-commit" section: remove `just deploy` instructions
- Modify: `docs/architecture.md`
- [ ] Add "Release lifecycle" section describing the four surfaces and the marker
- Modify: `CONTRIBUTING.md`
- [ ] Replace any "before pushing run `just ship`" advice with "push to ci/check-bmt-gate; CI handles the rest"
- [ ] Document the emergency path (`--force` on `ship`) for offline/broken-CI scenarios
- Modify: `CHANGELOG.md`
- [ ] `Unreleased` entry describing the CI-driven release cutover

### Gate C — e2e verification

- [ ] Push to `ci/check-bmt-gate`; verify `release.yml` ran **exactly once** end-to-end and `bmt-handoff` ran exactly once (no duplicate trigger)
- [ ] Verify `just deploy` is gone (`just --list | rg deploy` empty)
- [ ] Verify emergency path still works: `just ship --force` from laptop with test change
- [ ] core-main consumer smoke: open a trivial PR in `core-main` against `ci/check-bmt-gate`; verify `setup-bmt-pex` picks up the correct tag and BMT runs

---

## Phase D — Versioned plugin↔runtime contract (deferred, independent PR)

Out of scope for the first-pass landing of A–C. Tracked as follow-up issue:

- Replace `LegacyKardomeStdoutConfig(**kwargs)` construction at the plugin↔runtime boundary with a JSON schema `{schema_version, fields}` accepted by the runtime.
- Add `RUNTIME_REQUIREMENT = ">=X.Y.Z"` on each plugin; task startup compares against `runtime.__version__` and fails the leg with a human-readable error on mismatch.

Not blocking A–C because after A–C the image and plugins co-evolve in a single CI release, eliminating the **inter-release** drift that motivates this. D addresses **intra-release** drift (hot-patching a plugin in the bucket without a release), which is rare but real for debug scenarios.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `release.yml` flaky → merges land without cloud update | Phase B keeps legacy `push` trigger on handoff as parallel safety net until Phase C; Phase C only lands after Phase B has been green end-to-end across ≥2 real merges |
| Pulumi CI run leaks secrets into logs | `pulumi up` has existing secret masking; `--ci` flag adds `--suppress-outputs` on sensitive exports |
| Image build on every runtime edit is slow (~5-10m) | Docker layer cache via BuildKit inline cache; path filter on `detect-changes` keeps most merges image-step-free |
| Concurrent merges race on the bucket marker | `concurrency: release-${{ github.ref }}, cancel-in-progress: false` serializes; second release simply waits |
| Emergency local rebuild needed | `just ship --force` preserved as explicit, loud, documented escape hatch |
| Stale bucket during a rollback | Rolling back = reverting the merge commit; release.yml then re-runs against the old sha and rewrites the marker. Tested in Phase C verification. |

---

## Open questions (resolve during implementation)

1. Should the image step use Artifact Registry's Docker layer cache, or Buildx inline cache? Decide during B.2 based on measured build time.
2. Should `release.yml` also fan out to a post-release smoke test Cloud Workflow before updating the marker, or is the existing BMT handoff the smoke test? Current plan: handoff **is** the smoke test; marker is written before handoff so handoff's Plan-job assertion works.
3. Do we need an `/dev` branch release path, or does `dev` purely promote from `ci/check-bmt-gate` with no new artifact production? Current plan: `dev` promotes only (no release.yml trigger); matches existing branch policy.
