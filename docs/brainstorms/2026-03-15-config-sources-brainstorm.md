# Brainstorm: Fewer configuration sources

**Date:** 2026-03-15  
**Driver:** Too many places to set/config values — Pulumi, GitHub vars, secrets, VM metadata, code constants; hard to know where to set what.

---

## What we're building

A way to reduce the number of *sources* operators and developers need to think about when configuring BMT. Today values live in:

- **Pulumi** — `infra/pulumi/bmt.tfvars.json` (gcp_project, gcs_bucket, etc.) → stack outputs → exported to GitHub vars
- **GitHub Variables** — GCS_BUCKET, GCP_PROJECT, BMT_LIVE_VM, GCP_SA_EMAIL (from Pulumi) + GCP_WIF_PROVIDER, BMT_DISPATCH_APP_ID (manual)
- **GitHub Secrets** — BMT_DISPATCH_APP_PRIVATE_KEY
- **VM metadata** — GCS_BUCKET, BMT_REPO_ROOT, BMT_IDLE_TIMEOUT_SEC, startup-script (synced by workflow)
- **Code constants** — bmt_config.py, constants.py (handshake timeouts, status context, etc.)
- **Local / tools** — .env, BMT_CONFIG, GCS_BUCKET for bucket commands

Success looks like: "I know exactly where to set X" with fewer distinct places, or one clear map.

---

## Approaches

### Approach A: Single declarative file + sync (one file drives all non-secret config)

**Idea:** One file (e.g. extend `bmt.tfvars.json` or add `bmt-config.json`) holds every non-secret value. Pulumi reads infra keys from it (already does). A single sync step (e.g. `just sync-config` or part of `just pulumi`) pushes the same file’s values to GitHub Variables and to VM metadata. Secrets are never stored in the file — only referenced by name (e.g. "BMT_DISPATCH_APP_PRIVATE_KEY must be set in GitHub Secrets"). Operators edit one file and run one command.

**Pros:** Single place to edit; clear mental model.  
**Cons:** Sync logic must stay in sync with GitHub and GCP APIs; secrets still live in GitHub/GCP.  
**Best for:** Teams willing to maintain a sync step in exchange for one source of truth for non-secrets.

---

### Approach B: Config manifest + "where to set" tool (one map, sources unchanged)

**Idea:** Keep current sources. Add one **config manifest** — a doc or generated output (e.g. `just config-sources`) that lists every logical setting once with exactly one line: "X → set in Y (how)." Constants stay "in code (read-only)". Optional: a validator that checks all required sources are populated (Pulumi stack, GitHub vars, etc.). No change to where values are stored; we only make the map explicit and easy to query.

**Pros:** No change to Pulumi, GitHub, or workflows; low implementation cost.  
**Cons:** Still multiple sources; we're clarifying, not consolidating.  
**Best for:** Quick win and/or when consolidating into one file is not acceptable (e.g. GitHub Actions must read vars from GitHub at runtime).

---

### Approach C: Tiered doc-only (restructure configuration.md)

**Idea:** Restructure configuration.md into three short tiers: "Tier 1 — You set these (bmt.tfvars.json + 2 GitHub vars)", "Tier 2 — Set by Tier 1 (Pulumi export → GitHub)", "Tier 3 — Derived or in code". No new tooling or sync. Just a clearer doc so "where do I set X?" is answerable in one place.

**Pros:** Doc-only; no code or workflow changes.  
**Cons:** Doesn’t reduce number of sources; only explains them better.  
**Best for:** Minimal change, fast improvement to onboarding.

---

## Recommendation (after best-practices research)

**Hybrid A + C (with B folded into C): do C first, then optionally extend A.**

1. **Do C first — tiered doc.** Restructure configuration.md into Tier 1 (you set these: bmt.tfvars.json + 2 GitHub vars), Tier 2 (set by Tier 1: Pulumi export → GitHub; workflow → VM metadata), Tier 3 (derived / in code). That is the config manifest (B) in doc form: one place to answer "where do I set what?" with no new tooling.
2. **Optional later — extend single file + sync (A).** Add the 2 manual non-secret vars to the declarative source (e.g. extend bmt.tfvars.json with a `ci` block or small bmt-config.json) and have `just pulumi` (or `just sync-config`) push them to GitHub Variables. Optionally drive VM metadata from the same file. Secrets stay in GitHub/GCP only.

**Reasons (from best-practices-researcher):** Single source + sync for non-secret config is widely used (Pulumi ESC sync, Terraform tfvars → CI); we already have Pulumi → GitHub. Tiered doc is the "config map" pattern (Ansible/Puppet style) and reduces cognitive load immediately. Secrets stay out of the file everywhere. C is fast and low-risk; A can follow if we want to eliminate the last manual vars.

---

## Key decisions

- **Secrets stay out of any single config file** — They remain in GitHub Secrets / GCP Secret Manager; only names and "where to set" are documented or referenced.
- **GitHub Actions still read vars from GitHub** — Workflows get `vars.*` at runtime; we cannot make Actions read from a file in the repo instead without changing how jobs are wired. So any "single file" approach implies a sync step that pushes from file → GitHub (and optionally VM metadata).
- **Constants in code are intentional** — Handshake timeouts, status context, etc. stay in bmt_config/constants unless we explicitly decide to make them configurable; the improvement is about *deployment/repo* config, not tuning every behavioral constant.

---

## Resolved questions

- **Primary pain:** Too many sources (not doc length alone, not desire for a single file regardless of sync).
- **Sync step:** User deferred to "whichever is recommended." Best-practices research recommends **C first** (tiered doc, no new sync), then **optionally A** (extend single file + sync). So: yes to sync as an optional second step; not required for the first deliverable.
- **VM metadata from same file:** Optional in the A phase; acceptable to keep VM metadata synced from workflow/script until we extend the single file to drive it.
