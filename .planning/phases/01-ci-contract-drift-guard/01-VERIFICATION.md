---
phase: 01-ci-contract-drift-guard
verified: 2026-03-26T00:21:00Z
status: passed
score: 2/2 must-haves verified
---

# Phase 1: CI contract + drift guard Verification Report

**Phase Goal:** CI-owned modules hold env names, gate decisions, sanitization, and URL helpers; tests prove parity with `gcp.image` without `ci` importing it.
**Verified:** 2026-03-26T00:21:00Z
**Status:** passed

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | The CI package has a local contract module for every `gcp.image` symbol phase 1 inventoried as required for portability. | ✓ VERIFIED | `.github/bmt/ci/env_contract.py`, `.github/bmt/ci/gate_contract.py`, `.github/bmt/ci/env_parse.py`, and `.github/bmt/ci/workflow_links.py` cover the inventory recorded in `01-RESEARCH.md`. |
| 2 | The parity test proves the CI-local contract matches the runtime SSOT without CI importing `gcp.image` at runtime. | ✓ VERIFIED | `tests/ci/test_ci_contract_parity.py` passed with 38 assertions using `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -o addopts='' tests/ci/test_ci_contract_parity.py -v`. |

**Score:** 2/2 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `.github/bmt/ci/env_contract.py` | CI-local constants/defaults contract | ✓ EXISTS + SUBSTANTIVE | Defines the workflow name, status context, decision strings, and all env names CI currently imports from runtime. |
| `.github/bmt/ci/gate_contract.py` | Local gate enum and run-id sanitizer | ✓ EXISTS + SUBSTANTIVE | Defines `GateDecision`, `RUN_ID_MAX_LEN`, and `sanitize_run_id`. |
| `.github/bmt/ci/env_parse.py` | Local truthy env parser | ✓ EXISTS + SUBSTANTIVE | Exposes `is_truthy_env_value` with the runtime truthy token set. |
| `.github/bmt/ci/workflow_links.py` | Local workflow console URL helper | ✓ EXISTS + SUBSTANTIVE | Exposes `workflow_execution_console_url` with runtime-equivalent formatting. |
| `tests/ci/test_ci_contract_parity.py` | Drift/parity guard | ✓ EXISTS + SUBSTANTIVE | Covers constants, enum values, `sanitize_run_id`, `is_truthy_env_value`, and workflow execution URLs. |

**Artifacts:** 5/5 verified

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `tests/ci/test_ci_contract_parity.py` | `gcp/image/config/constants.py` | constant-name parameterization | ✓ WIRED | `CONTRACT_CONSTANT_NAMES` is used to compare each mirrored constant to runtime SSOT. |
| `tests/ci/test_ci_contract_parity.py` | `gcp/image/config/value_types.py`, `gcp/image/config/env_parse.py`, `gcp/image/github/reporting.py` | direct helper comparisons | ✓ WIRED | The test file compares `sanitize_run_id`, `is_truthy_env_value`, and `workflow_execution_console_url` to runtime implementations. |

**Wiring:** 2/2 connections verified

## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| PORT-01: `.github/bmt/ci` has its own contract modules for the runtime constants, gate decisions, run-id sanitization, truthy parsing, and workflow console URL it currently imports from `gcp.image`. | ✓ SATISFIED | - |

**Coverage:** 1/1 requirements satisfied

## Anti-Patterns Found

None.

## Human Verification Required

None — all verifiable items checked programmatically.

## Gaps Summary

**No gaps found.** Phase goal achieved. Ready to proceed.

## Verification Metadata

**Verification approach:** Goal-backward from the roadmap goal and plan `must_haves`
**Must-haves source:** `01-01-PLAN.md` frontmatter
**Automated checks:** 1 passed, 0 failed
**Human checks required:** 0
**Total verification time:** 2 min

---
*Verified: 2026-03-26T00:21:00Z*
*Verifier: the agent*
