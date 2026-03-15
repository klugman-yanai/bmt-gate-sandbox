# E2E Test Readiness (Test/Mocking Context)

This document summarizes repo state for running or authoring a **full end-to-end test in a test/mocking context**: i.e. one test (or small suite) that exercises the full BMT flow using mocks/fakes only (no real GCS, VM, or GitHub).

**Scope:** Unit + contract + integration tests under `tests/`; excludes live/smoke tests that hit real cloud.

---

## 1. What “full E2E” means here

- **Production E2E (docs):** Trigger → VM starts → watcher picks up trigger → orchestrator runs legs → pointer update → status/check. This is **manual** (real GCS/VM); see [development.md](development.md#testing-production-ci-locally).
- **E2E in test/mocking context:** The same flow exercised in pytest with **all external deps mocked** (GCS, VM, GitHub). There is **no single test** that chains the full flow today; the suite is split into:
  - **Unit:** CI models, gate, counter regex, pointer path helpers, GitHub PR/checks/comment.
  - **Contract:** Trigger guard, wait-handshake, start-vm, sync-vm-metadata, upload-runner dedup, vm_watcher (trigger process, pointer, PR closed/superseded).
  - **Integration:** CI commands via `bmt` subprocess (matrix, filter-supported-matrix, trigger, etc.), bootstrap scripts, devtools exit codes.

So “ready for full E2E test” means: (1) existing tests are stable and fixtures/config are correct, and (2) you can add a single E2E-style test that wires trigger → handshake → watcher with mocks.

---

## 2. Current test run

- **Command:** `uv run python -m pytest tests/ -v` (from repo root).
- **Config:** `pyproject.toml` — `testpaths = ["tests"]`, markers: `unit`, `contract`, `integration`, `live_smoke`; timeout 420s (per test 60s in run below).
- **Result (as of check):** 211 tests collected; **one timeout** in a contract test (see below). Rest pass.

---

## 3. Blockers / gaps

### 3.1 Stale fixture: `gcp_code_root` (conftest.py)

- **Location:** `tests/conftest.py`
- **Issue:** Fixture points to `repo_root / "gcp" / "code"`. The repo uses **`gcp/image`** (no `gcp/code`). So `gcp_code_root` would raise at fixture setup if any test requested it.
- **Impact:** No test currently uses `gcp_code_root`; only `repo_root` and (in other files) `_repo_root()` are used. So the suite still runs, but the fixture is wrong for future use.
- **Action:** Change to `repo_root / "gcp" / "image"`, or rename to `gcp_image_root` and keep a single source of truth.

### 3.2 Timeout: `test_process_run_trigger_superseded_mid_run_skips_pointer_promotion`

- **Location:** `tests/vm/test_vm_watcher_pointer.py`
- **Issue:** Test hits the 60s timeout. `_process_run_trigger` starts daemon threads (`_heartbeat_loop`, `_check_run_progress_loop`). The progress loop calls `status_file.read_status` (mocked to `{"legs": [{}, {}]}` with no `vm_state`), so it never sees `vm_state in ("done", "failed", "cancelled", "superseded")` and keeps looping. It then calls `_update_check_run_resilient`; the test mocks `github_checks.update_check_run` but **not** `_update_check_run_resilient`, so the progress thread can block on real I/O (e.g. HTTP) until the test timeout.
- **Action:** Either:
  - Mock `_update_check_run_resilient` in this test (like in another test in the same file), or
  - Make the mocked `read_status` return `vm_state: "superseded"` (or `"cancelled"`) so the progress loop exits immediately after the main thread sets the cancel path.

### 3.3 No single E2E test with mocks

- **Gap:** There is no test that runs the full sequence: write-run-trigger (or equivalent) → wait-handshake (mocked) → watcher processes trigger (mocked GCS/GitHub) → pointer/verdict.
- **Existing building blocks:** `tests/_support/harness.py` has `FakeGcsStore`, `FakeVmBackend`, `FakeGithubBackend`. Contract tests in `tests/vm/` and `tests/ci/` use `monkeypatch` on `_gcloud_*`, `status_file`, `github_*`, etc. Integration tests run `uv run bmt matrix|trigger|...` from repo root.
- **Action (optional):** Add an E2E test that: (1) writes a trigger payload into `FakeGcsStore`, (2) runs handshake and trigger-processing code paths with fakes/mocks, (3) asserts pointer/verdict and status writes. This would require injecting the fakes into the CI/watcher code paths (e.g. via env or a small test-only adapter).

---

## 4. What is in good shape

- **Repo layout:** `gcp/image` and `.github/bmt` exist. Config lives in `gcp/image/config` (e.g. `bmt_config.py`); matrix is built from `CMakePresets.json` at repo root (used by `bmt matrix`).
- **CI entrypoint:** `.github/bmt/ci/driver.py` exposes `bmt` commands (matrix, write-run-trigger, wait-handshake, etc.). Integration tests run these via subprocess from repo root with `GITHUB_OUTPUT` and env; they pass.
- **Test layers:** Markers and `conftest` assign unit/contract/integration consistently; `repo_root` and cwd are stable; no test uses the broken `gcp_code_root`.
- **Fakes:** `FakeGcsStore`, `FakeVmBackend`, `FakeGithubBackend` are available for future E2E or contract tests.

---

## 5. Checklist for “ready for full E2E test” (mocking context)

| Item | Status |
|------|--------|
| All non–live_smoke tests pass without timeout | ❌ One contract test times out |
| conftest path fixtures match repo layout (`gcp/image`) | ❌ `gcp_code_root` points to `gcp/code` |
| Contract tests that start watcher threads mock all I/O used by those threads | ❌ Superseded test leaves progress loop unmocked |
| Optional: one E2E test chaining trigger → handshake → watcher with mocks | ❌ Not implemented |

---

## 6. Recommended next steps

1. **Fix conftest:** Set `gcp_code_root` to `repo_root / "gcp" / "image"` (or introduce `gcp_image_root` and deprecate `gcp_code_root`).
2. **Fix superseded test:** In `test_process_run_trigger_superseded_mid_run_skips_pointer_promotion`, either mock `_update_check_run_resilient` or make the progress loop exit immediately (e.g. by returning `vm_state: "superseded"` from the mocked `read_status`).
3. **Re-run suite:** `uv run python -m pytest tests/ -v` and confirm no timeouts/failures (excluding `live_smoke` if not intended for default run).
4. **(Optional)** Add an E2E test that wires trigger write → handshake → watcher with `FakeGcsStore` / mocked VM and GitHub, and asserts pointer/verdict and status updates.

After (1)–(3), the repo is **ready for a full E2E test in the test/mocking context** in the sense that the suite is stable and fixtures are correct; (4) is the step that actually adds that E2E test.
