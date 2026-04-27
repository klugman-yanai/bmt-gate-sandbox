# Plugin Conformance Checklist

Use this checklist before enabling a new project in the cloud BMT pipeline.

This document lives in **bmt-gcloud** because framework contracts, orchestration behavior, and CI gating are owned here.

---

## 1) Required Project Artifacts

- `plugins/projects/<project>/project.json`
- At least one BMT manifest: `plugins/projects/<project>/<bmt>.json`
- Plugin implementation: `plugins/projects/<project>/plugin.py`
- Scoring policy module: `plugins/projects/<project>/*_scoring_policy.py`
- Optional contract file: `plugins/projects/<project>/runner_integration_contract.json`

## 2) Runner Execution Contract

- Runner invocation method documented (CLI args/env, optional batch mode).
- Per-case output artifact contract documented:
  - per-case metrics JSON path (for example `<output>.bmt.json`)
  - required fields (`status`, metric field(s), optional `exit_code`, optional `error`)
- If batch mode exists, batch schema documented and stable.

## 3) Scoring Contract (project-owned)

- Metric name(s) and direction are explicit (`higher_better` / `lower_better`).
- Aggregation rule is explicit (mean/median/pass-rate/etc.).
- Failure semantics are explicit:
  - case-level failure handling
  - all-cases-failed handling
  - baseline-absent behavior
- Reason codes are stable and readable in CI summaries.

## 4) Dataset Contract (project-owned)

- Input dataset location/prefix pattern defined.
- `dataset_manifest.json` required and validated.
- Channel/sample-rate assumptions declared.
- Required preconditions documented (for example refs optional/required).

## 5) Framework Integration Rules

- Primary scoring path uses structured JSON, not stdout regex parsing.
- Per-case metric key names are plugin-owned (for example `metric_name` / `metric_json_keys` in manifest config), not hardcoded in framework logic.
- Execution policy is selected per manifest (`legacy_only`, `adaptive_batch_then_legacy`, `batch_json_only`).
- Plugin tuning/config does not require framework code edits for normal project work.

## 6) Required Tests Before Enablement

- Unit tests for plugin scoring/evaluation logic.
- Unit tests for metrics JSON parsing (valid, malformed, missing key).
- Execution tests for runner invocation adapter (success/failure/timeout).
- Dataset preflight tests (missing files/channel mismatch behavior).
- Batch parser tests (if batch mode enabled).
- One targeted integration test simulating a full leg result end-to-end.

## 7) CI Gate for Onboarding

- New project remains disabled by default until tests are green.
- Enablement change includes:
  - manifests + plugin + scoring + docs
  - test evidence (commands and pass output)
  - rollback plan (how to disable quickly)
- Required status context remains stable (`BMT Gate` unless explicitly changed).

## 8) Documentation Minimum

- Add project to `docs/adding-a-project.md` and docs index where relevant.
- Add project runtime notes (runner quirks, metrics schema, dataset assumptions).
- Include local run commands.
- Include known failure modes and where diagnostics are written.

## 9) Go / No-Go Definition

Project is **Go** only when all are true:

- Structured metrics contract is implemented and tested.
- Plugin scoring is deterministic and documented.
- Dataset contract validation passes.
- Targeted tests pass in CI.
- One cloud handoff run confirms expected `results/` and status reporting.
