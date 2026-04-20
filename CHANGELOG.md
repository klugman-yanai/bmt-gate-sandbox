# Changelog

## [Unreleased]

### Added

- SK leg-level channel pre-flight: the `LegacyKardomeStdoutExecutor` now probes the first WAV's RIFF header once per leg and, when the declared `plugin_config.expected_channels` (set to `4` for SK's `false_alarms` and `false_rejects`) does not match, emits a single `_channel_mismatch_` case instead of running `kardome_runner` against an incompatible dataset. This replaces per-file `free(): invalid next size` heap-corruption crashes with a readable leg-level error (`channel_mismatch:expected=4:got=8:probe=<rel>`). WAV files are never converted — this is pure graceful failure.

## bmt-v0.3.3

### Added

- Publish-matrix UI split: one Publish leg per supported BMT project plus a parallel No-BMT acknowledgement matrix for the rest, so `sk` always renders as a distinct job node (#97).
- `runner_path` and `lib_path` in every matrix row so downstream jobs can address `kardome_runner` and `libKardome.so` explicitly instead of inferring from `binary_dir`.
- Local pipeline driver and per-WAV runner harness under `tools/scripts/` for offline reproduction of runner crashes.
- `docs/post-runner-fix-checklist.md` including a section on the Cloud Run `rglob("*.wav")` input-enumeration path bypassing `dataset_manifest.json`.

### Changed

- `setup-bmt-pex` self-discovers its release tag from `github.action_ref` — invoking the action as `uses: .../setup-bmt-pex@bmt-v0.3.3` now downloads the `bmt-v0.3.3` PEX without any `with: tag: …` thread. Internal `BMT_PEX_TAG` env-var indirection removed from `bmt-handoff.yml` and `bmt-prepare-context`; a shape guard fails fast when the action is invoked via `@<sha>` or `@<branch>` so the `tag:` input stays available for cross-version testing. Consumer repos still set `vars.BMT_PEX_TAG` to pin the reusable-workflow `@ref`.
- Unified `build-and-test-dev.yml` to handle both `push` and `pull_request` events with a single matrix, deleting `trigger-ci-pr.yml` and halving per-PR compute.
- Commented out the deprecated `code-owner-enforcement.yml` in release templates; CODEOWNERS enforcement now lives in GitHub Branch Rulesets.
- `e2e-test` plugin aligned with current `bmt_sdk.results` shapes.
- Type-checker ergonomics: Pulumi config resolvers typed so `ty` and Pyright resolve them without casts.

### Fixed

- `bmt-handoff` Dispatch job no longer skips when `acknowledge_no_bmt` is not instantiated: removed the unnecessary dependency and replaced the `success|skipped` gate with a negative gate against the remaining parents.
- `bmt-handoff-dev` callable grants `pull-requests: read` so the nested call from `build-and-test-dev` succeeds on PR events.
- "No bmts dir for project 'sk'" demoted from warning to notice; `plugins/projects/<project>/bmts/` is an optional pre-flight layer, not a required input for BMT leg discovery in Cloud Run.

## 0.1.0

### Added

- Clean gate test 20260311T084632Z
