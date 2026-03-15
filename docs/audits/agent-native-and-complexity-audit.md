# Agent-Native Architecture & Complexity Audit: bmt-gcloud

**Date:** 2025-03-15  
**Scope:** Run BMTs on a GCP VM triggered from GitHub Actions.  
**Question:** Is the project over-engineered for this scope?

---

## Overall Score Summary

| Core Principle | Score | Percentage | Status |
|----------------|-------|------------|--------|
| Action Parity | ~53/55 | 96% | ✅ |
| Tools as Primitives | 11/18 | 61% | ⚠️ |
| Context Injection | 5.5/6 | 92% | ✅ |
| Shared Workspace | 8/8 | 100% | ✅ |
| CRUD Completeness | 6/9 entities | 67% | ⚠️ |
| UI Integration | 15/15 | 100% | ✅ |
| Capability Discovery | 5/7 | 71% | ⚠️ |
| Prompt-Native Features | 4/9 | 44% | ❌ |

**Overall Agent-Native Score: 79%**

### Status Legend

- ✅ Excellent (80%+)
- ⚠️ Partial (50–79%)
- ❌ Needs Work (<50%)

---

## Over-Engineering Verdict

**Verdict: Somewhat over-engineered for “run BMTs on a cloud VM from GitHub Actions.”**

- **Architecture-strategist:** Core design (trigger → VM → run → status) is sound; handshake, code/runtime split, and pointer/snapshot are justified. Excess: many jobs/actions, seven CI manager classes, duplicate tools (`tools/bmt` vs `tools/remote`), and a single 2k-line VM watcher.
- **Kieran-Python-reviewer:** Could be simplified. Main wins: remove duplicate BMT modules, split `vm_watcher.py`, simplify manager hierarchy. No unnecessary interfaces; duplication and single-file size are the main issues.
- **Code-simplicity-reviewer:** Some excess. Dead code: `tools/remote/bmt_*.py` (3 files), dead `register()` in bmt_wait_verdicts. Unused by CI: `tools bmt wait` (verdict polling), `stage-release-runner`, `compute-preset-info`. Doc drift: references to `.github/scripts/ci_driver.py` and wrong tool paths.

**What’s justified:** Handshake (trigger-and-stop), code/ vs runtime/, per-project manager + pointer/snapshot, failure fallback, multi-BMT matrix.

**What’s beyond minimal:** Duplicate BMT tooling, 7 CI managers + 8 composite actions, 2k-line single VM script, two upload-runner commands, unused bmt commands, matrix/preset/filter chain heavier than a single config for current use.

---

## Top 10 Recommendations by Impact

| Priority | Action | Principle / Area | Effort |
|----------|--------|-------------------|--------|
| 1 | Remove duplicate BMT modules: delete `tools/remote/bmt_wait_verdicts.py`, `bmt_monitor.py`, `bmt_run_local.py`; keep only `tools/bmt/` | Simplicity / DRY | Low |
| 2 | Split `gcp/image/vm_watcher.py` into focused modules (GCS, trigger/leg, GitHub status+checks, pointer/snapshot cleanup) | Complexity / Tools as Primitives | Medium |
| 3 | Fix docs to match real CI: `.github/bmt/ci`, `uv run bmt <cmd>`, `tools/remote/bucket_*`, `tools/bmt/*`; clarify wait-handshake vs verdict wait | Capability Discovery | Low |
| 4 | Add Just recipes: `just vm-check <run_id>`, `just clean-bloat` (docs reference them; they’re missing) | Action Parity | Low |
| 5 | Expose bucket primitives: `tools bucket sync`, `verify-code`, `verify-runtime-seed` (keep `deploy` as workflow that runs all three) | Tools as Primitives | Low |
| 6 | Simplify BMT manager: thin base + shared GCS/gate/cache helpers, or one config-driven manager + ABC only for SK | Complexity | Medium |
| 7 | Consolidate CI: fewer Manager classes and bmt commands; single runner-upload behavior (`upload-runner` only) | Over-engineering | Medium |
| 8 | Add first-run / “what you can do” section in README or docs/README.md; fix `just vm-check` doc/code drift | Capability Discovery | Low |
| 9 | Add CRUD where missing: `bmt remove-project`, optional `bucket delete-runner` (or documented gcloud); document pointer “delete” as intentional | CRUD Completeness | Low–Medium |
| 10 | Make “available projects” explicit: small registry or doc (e.g. project_registry.json or configuration.md section) | Context Injection | Low |

---

## What’s Working Well

1. **Shared workspace (100%)** — All data stores (local gcp/, GCS code/runtime, GitHub vars, VM metadata, Terraform state) are shared; no agent sandbox. Single bucket, single repo vars, single VM.
2. **Action parity (96%)** — Almost all developer actions (Just, tools CLI, `uv run bmt`, workflows) are achievable by an agent with the same CLI and env; gaps are vm-check/clean-bloat missing from Justfile and TUI monitor.
3. **UI integration (100%)** — Every CI/VM action (trigger, ack, status, Check Run, commit status, pointer, snapshots) is reflected in GitHub UI, GCS, or job outputs.
4. **Context injection (92%)** — Env contract, vars contract, BmtConfig, per-project bmt_jobs.json, GCS trigger and results layout are centralized; only “available projects” is implicit.
5. **Trigger-and-stop design** — Workflow writes trigger and waits for handshake; VM runs BMTs and posts status. Fits “run on VM, report back” without blocking the runner.

---

## Principle Summaries (from sub-agent audits)

### 1. Action Parity (96%)

- User actions: Just (15), tools CLI (18), `uv run bmt` (28), workflow triggers (6), manual/doc (~12). Agent can do ~53/55 with same commands and env.
- Gaps: `just vm-check` and `just clean-bloat` documented but not in Justfile; monitor is TUI-only; secrets must be supplied.

### 2. Tools as Primitives (61%)

- 11/18 CLI commands are primitives; 7 are workflows (deploy, monitor, wait, terraform apply/import-topics, repo validate, build image).
- Recommendations: Expose bucket sync/verify as separate commands; split bmt wait into fetch → aggregate → workflow.

### 3. Context Injection (92%)

- Config, env contract, results layout, repo vars, and docs are in place. “Available projects” is implicit (matrix + bucket layout).
- Recommendation: Add project registry or doc section.

### 4. Shared Workspace (100%)

- All 8 data stores are shared; no isolated agent data. Intentional mirrors (gcp/image ↔ GCS code/, gcp/remote ↔ runtime/) are documented.
- Gap: `just pull-gcp` is documented but not in Justfile.

### 5. CRUD Completeness (67%)

- Full CRUD: run trigger, snapshot, repo vars, config files (code), Terraform, VM state. Missing: BMT project (no D), current.json pointer (no D by design), runner binaries (no D).
- Recommendations: `bmt remove-project`, optional `bucket delete-runner` or documented gcloud, document pointer policy.

### 6. UI Integration (100%)

- All 15 agent actions have visible output (GitHub status/Checks, GCS, Actions outputs, terminal). Low-visibility: status file, current.json updates (no prominent UI beyond GCS/monitor).

### 7. Capability Discovery (71%)

- Present: README/docs index, Just list, tools --help, env vars docs, error hints. Missing: first-run guidance, explicit “all capabilities” list; `just vm-check` doc/code drift.

### 8. Prompt-Native Features (44%)

- Config-driven: gate params, repo mapping, BMT paths/runner/template/parsing. Code-defined: matrix filter, verdict aggregation, pointer/cleanup, status text, timeouts. Recommendation: move matrix discovery, verdict policy, status text, timeouts, retention to config where useful.

---

## References

- Agent-native skill: option 7 (context injection) / full reference loaded.
- Sub-agent IDs (for resume): Action Parity a146e288, Tools 28be1397, Context 8c1501a5, Shared fda56d0c, CRUD 928d50e8, UI 815f0792, Discovery deef237d, Prompt 67fdd955, Architecture 8235c9b2, Kieran ca5bfc65, Simplicity bf2a79ad.
