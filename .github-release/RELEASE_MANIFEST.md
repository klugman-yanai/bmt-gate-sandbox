# .github/

This directory contains the repo’s GitHub Actions: workflows, custom actions, and the BMT CLI used by CI.

---

## Workflows

- **build-and-test.yml** — Main CI. On push and pull requests to `dev`: parses CMake presets, runs release and non-release builds, then runs the BMT gate when the release build succeeds (same repo, base branch `dev`). Uses `pull_request_target` for fork-safe checkout.

- **bmt-handoff.yml** — Reusable BMT workflow. Triggered by the main CI when the gate runs: selects or starts the BMT VM, writes the run trigger to GCS, waits for VM handshake, writes the handoff summary. Called with `workflow_call` from `build-and-test`.

- **clang-format-auto-fix.yml** — Applies clang-format to matching files.

- **code-owner-enforcement.yml** — Ensures PRs are reviewed by configured code owners.

---

## Custom actions

- **bmt-prepare-context** — Emits BMT context, validates required vars, parses release runners.
- **bmt-filter-handoff-matrix** — Resolves uploaded runners and builds the filtered handoff matrix.
- **bmt-handoff-run** — Preflight, VM metadata sync, VM start, trigger write, handshake wait, summary.
- **bmt-write-summary** — Writes the handoff step summary to the job summary.
- **bmt-failure-fallback** — On handoff failure: resolve failure context, post timeout status, cleanup trigger artifacts.
- **bmt-runner-env** — Checkout (sparse .github), restore snapshot artifact, setup uv, sync BMT package, run `uv run bmt load-env`.
- **setup-gcp-uv** — Authenticate to GCP (WIF), install gcloud, optionally install uv.
- **check-image-up-to-date** — Verifies the BMT runtime image build ran when infra/packer or gcp/image changed.

---

## BMT package (`bmt/`)

Python package used by the above actions. Commands run via `uv run bmt <command>` (e.g. `load-env`, `matrix`, `write-run-trigger`, `wait-handshake`). Contains the `ci` module (driver, config, GCS, GitHub, VM, handshake, trigger, matrix, runner, handoff, preset) and `config/` docs. Built with `pyproject.toml` and locked with `uv.lock`.

---

## Config

- **actionlint.yaml** — Declares repo/org variables used in workflows so actionlint can validate references.
