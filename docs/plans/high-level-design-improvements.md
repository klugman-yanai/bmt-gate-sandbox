# High-level design improvements (purpose-driven)

> **For Claude:** When implementing these improvements, use an implementation plan with bite-sized tasks (exact files, steps, commands). See writing-plans skill.

**Goal:** Align bmt-gcloud design with its purpose: reliable local testing of production CI using real VM and GCS.

**Scope:** Priority improvements 1, 2, 4, 5 (entry point, one how-to doc, mirror prerequisite, test tiers); supporting improvement 3 (production surface). Optional 6–7 deferred.

---

Based on the project’s **purpose** — reliably test production CI locally using the real VM and GCS — and its supporting pillars (mirror `remote/`, test suite, dev QoL), these are high-level improvements that would make the design better aligned with intended usage.

---

## 1. First-class “test production CI locally” path

**Gap:** The main purpose is documented, but there is no single entry point. Users must remember to sync, then run the same steps as the workflow (matrix → trigger → start VM → wait-handshake) from multiple recipes or workflow code.

**Improvement:**

- Add a **single entry point** that encodes the full sequence, e.g.:
  - `just prod-ci-local` (or `just test-prod-ci`), or
  - A script `devtools/run_prod_ci_local.py` that:
    1. Checks prerequisites (repo vars set, `gcloud` auth, optional: mirror in sync).
    2. Runs the same steps as the workflow in order: sync mirror (or verify), matrix → trigger → start VM → wait-handshake, with the same env contract the workflow uses.
    3. Prints where to look next (monitor, GCS trigger/ack, Check Run).
- Document this as **the** way to “test production CI locally” in README and development.md, and link to it from the Purpose section.

**Outcome:** The main purpose is achievable in one command (or one obvious script), with no guesswork about order or missing steps.

---

## 2. One “How to test production CI locally” flow in docs

**Gap:** Prereqs, sync, and workflow steps are spread across README, development.md, and Justfile. There is no single, linear “do this then this then this” guide.

**Improvement:**

- Add a **short, linear guide** (e.g. a section in `docs/development.md` or a dedicated `docs/testing-production-ci-locally.md`) that:
  1. Lists prerequisites (repo vars, `gcloud` auth, optional Python/uv).
  2. Says: sync mirror (`just sync-gcp`, `just verify-sync`).
  3. Walks through the exact sequence the workflow runs (with concrete commands or Just recipe names).
  4. Describes how to verify (monitor, gcs-trigger, Check Run, GCS pointers).
- Link to this guide from README “Local usage” and from CLAUDE.md so it’s the canonical “test prod CI locally” reference.

**Outcome:** New contributors and AI have one place to follow for the main use case.

---

## 3. Explicit production-surface boundary

**Gap:** It’s not always obvious what “production” runs vs what is bmt-gcloud–only. Drift between “what we test locally” and “what runs in production” would undermine the main purpose.

**Improvement:**

- **Document the production surface** in one place (e.g. in `docs/architecture.md` or a new “Production surface” section):
  - What is copied or reused in production: workflow files (e.g. `bmt.yml`, dispatch), `.github/bmt` CLI (or equivalent), `remote/code` layout and contracts (trigger payload, GCS layout, VM bootstrap).
  - What stays dev-only: devtools, Justfile, tests, local config (e.g. `tools/repo_vars_contract.py` or optional overrides), `.local/`.
- Add a short checklist or script that validates “local workflow steps match production” (e.g. same bmt subcommands, same trigger payload shape).

**Outcome:** Clear contract for “testing production CI” = “running the same production surface locally,” with less risk of accidental divergence.

---

## 4. Mirror sync as a documented prerequisite

**Gap:** Sync is mentioned in README and remote/README, but it’s not framed as a strict prerequisite for “test prod CI locally.” Some users might run trigger/start-vm without syncing first.

**Improvement:**

- In the “How to test production CI locally” flow (see §2), state explicitly: **before** running workflow steps, run `just sync-gcp` and `just verify-sync` so the bucket matches `remote/`.
- Optionally, the first-class entry point (§1) can run sync (or verify-sync) by default, with a flag to skip when the user knows the mirror is already in sync.

**Outcome:** Fewer “why did the VM run old code?” incidents; mirror discipline is part of the main story.

---

## 5. Test tiers aligned with purpose

**Gap:** Tests are described (unit vs with GCS/VM), but not explicitly tied to “testing production CI locally.” It’s unclear what level of test corresponds to “I’ve validated the prod path.”

**Improvement:**

- Define **test tiers** in docs (e.g. in `docs/development.md`):
  - **T1 — Unit:** No GCS/VM; BMT logic, gate, pointer resolution, CI command parsing. Fast, no credentials.
  - **T2 — Integration:** Uses real GCS (and optionally VM) for a subset of behavior (e.g. manager run, trigger write, pointer read). Requires bucket/vars.
  - **T3 — E2E prod-like:** Full sequence: sync + workflow steps (matrix → trigger → start VM → wait-handshake) + VM runs legs; verify pointers/Check Run. Same contract as production.
- State that **“test production CI locally”** corresponds to running the **T3 path** (and that T1/T2 support it by catching regressions earlier).

**Outcome:** Shared vocabulary and a clear definition of “I tested the production path” (T3).

---

## 6. Optional: Run manifest for replay (when needed)

**Gap:** config-approach.md already predicts that “replay this run locally” may become desirable. Today there’s no artifact that captures an exact run’s inputs for replay.

**Improvement (defer until needed):**

- When someone asks for replay, introduce a **run manifest** (e.g. written by the workflow or by the first local step) that records matrix, run_context, head_sha, trigger payload, etc.
- **Contract stays env in CI;** the manifest is an optional artifact. Locally, a script or mode can read the manifest and populate the same env (or drive steps) so “replay” uses the same contract as production without changing production.
- Document in config-approach.md that this is the intended approach when replay becomes a requirement.

**Outcome:** When replay is needed, the design is already decided: manifest as optional artifact, env contract unchanged.

---

## 7. Optional: CI smoke test for the handoff (bmt-gcloud repo)

**Gap:** The claim “we can test production CI locally” is only validated by humans running the flow. The bmt-gcloud repo could run its own handoff (e.g. against a test bucket/VM) on push or on a schedule.

**Improvement:**

- Add a **smoke workflow** (or a scheduled job) that runs the handoff sequence (matrix → trigger → start VM → wait-handshake) in bmt-gcloud’s CI, against a test bucket and VM (or a minimal path that doesn’t run full BMT legs).
- This proves “prod CI is testable” and catches breakage in the handoff path. Can be optional or low-frequency to control cost.

**Outcome:** The main purpose is continuously validated by CI, not only by ad-hoc local runs.

---

## Summary

| # | Improvement | Effect |
|---|-------------|--------|
| 1 | First-class “test prod CI locally” entry point (`just prod-ci-local` or script) | Main purpose achievable in one command. |
| 2 | Single linear “How to test production CI locally” doc | One canonical flow; fewer missed steps. |
| 3 | Explicit production-surface boundary | Clear contract; less drift between local and prod. |
| 4 | Mirror sync as documented prerequisite | Fewer runs against stale bucket state. |
| 5 | Test tiers (T1/T2/T3) aligned with purpose | Clear meaning of “tested the production path” (T3). |
| 6 | Run manifest for replay (when needed) | Ready when replay is requested; env contract unchanged. |
| 7 | CI smoke test for handoff in bmt-gcloud | Main purpose validated by CI. |

Priorities that best serve the stated purpose and usage: **1, 2, 4, 5** (entry point, one doc, sync prerequisite, test tiers). **3** (production surface) supports long-term consistency. **6** and **7** can be done when replay or CI smoke becomes a concrete need.
