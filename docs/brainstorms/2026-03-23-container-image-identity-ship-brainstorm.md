# Brainstorm: Hardening container image identity for `ship` / auto-skip decisions

**Date:** 2026-03-23  
**Scope:** WHAT to optimize for (identity, traceability, skip-vs-build policy)—not implementation details of `tools ship` yet.

## What we're building

A **reliable notion of “this image is the one for this source state”** so local tooling (e.g. `just ship`) and automation can decide **skip vs build/push** without false confidence.

Today, **path-only** or **naive “same tree”** checks are weak: paths can match while **content** differs; conversely **git** can be clean after a push while the **registry still has no** (or a stale) image. A random **UUID** per build is useful as a **correlation id**, but it is **not** the OCI-native immutable identity.

## Industry standard (OCI / Artifact Registry)

- **Canonical immutable reference in the registry:** the **manifest digest** — `repository@sha256:<hex>`. Content-addressable; this is what you pin for “exactly this image.”
- **Tags** (`:latest`, `:v1.2.3`, a **git SHA as tag**): **mutable pointers** to a digest (unless the repo enforces immutable tags). `:latest` is convenient but **not** a guarantee of recency or uniqueness.
- **“Image UUID”** as a term: **not** an OCI standard. Teams sometimes use **UUID-shaped tag names** or build IDs; behaviorally they are **tags**, not a substitute for **digest**.
- **Docker “image ID” locally:** config hash; **not** the same as the **registry manifest digest** used across CI/CD.
- **Practice:** push with **traceable tags** (e.g. **git SHA** + optional semver), then **record and deploy using digest** from the push (or resolve tag → digest in the pipeline). Google Artifact Registry documents digest as the stable identifier; tags are optional labels.

**Implication for this repo:** `just image` currently pushes **`bmt-orchestrator:latest`** only ([Justfile](../../Justfile)). That maximizes **overwrite** of a moving pointer and minimizes **traceability** from deploy → exact bits unless something else records the digest.

## Problem we’re really solving

| Pitfall | Why git-diff-only heuristics fail |
|--------|-----------------------------------|
| Content changed, paths unchanged | Rare for renames; **normal edits** are seen by git. **Uncommitted** or **ignored** inputs break if not in diff scope. |
| Clean tree after **push** | Local **git diff empty**; registry may still need a build. |
| **Base image** / upstream moves | **No** repo file change; rebuild may still be required. |
| **Failed** or **skipped** prior `docker push` | Tree matches; artifact missing or old. |

So: **content hash of declared build context** beats **path list**; **registry truth** (digest exists for intended tag/label) beats **local hash** for “did we actually publish?”

## Approaches (2–3)

### A — **Context content digest** (local file manifest)

Hash a **canonical listing** of all files under the Dockerfile’s effective context (e.g. `gcp/image/**`, `gcp/__init__.py`, Dockerfile bytes), sorted paths + **per-file content hashes**. Compare to a **last-success** digest stored after a successful `just image` (gitignored local file or team-owned cache).

**Pros:** Strong “same inputs → same expected build” without registry calls.  
**Cons:** Must stay in sync with Dockerfile `COPY` graph; base image still needs **digest-pinned `FROM`** or separate policy.

### B — **Registry + traceable tags** (industry-typical)

Push **`bmt-orchestrator:<git-sha>`** (and optionally `:latest`). Before skipping local build, **query Artifact Registry** for an image with tag = current `HEAD` (or resolve **digest** for that tag). Skip only if present **and** policy allows (e.g. same SHA as local).

**Pros:** Matches “did we **publish** for this commit?” Fixes **post-push clean tree** when CI or a prior push succeeded.  
**Cons:** Needs **gcloud/crane** and permissions; network; tag mutability unless **immutable tags** policy on the repo.

### C — **Digest-only deploy contract**

Treat **only** `image@sha256:…` as deployable; CI writes digest to a file or Pulumi/GitHub var; `ship` never guesses—only builds when digest file missing or mismatch.

**Pros:** Strongest operational clarity.  
**Cons:** Heavier process; may be overkill for **local dev** `ship` if YAGNI.

## Recommendation (YAGNI-first)

1. **Short term:** Keep **`--force-image`** as the escape hatch; document that **git-based auto-skip is heuristic**.
2. **Next hardening (pick one primary):**
   - Prefer **A (content digest)** if the goal is **local skip without registry** and Dockerfile context is stable.
   - Prefer **B (tag = git SHA + registry check)** if the goal is **“artifact exists for this commit”** and you’re OK adding **gcloud** to the check—aligns with common CI/CD practice.
3. **Long term / prod hygiene:** Push **SHA tags** (and optionally keep `:latest` as a convenience pointer); **record digest** from `docker push` output or registry API for anything production-critical.

**UUID:** Use only as a **human/build correlation** tag if desired; **do not** treat it as replacing **manifest digest** for immutability.

## Key decisions (proposed)

- [ ] **Identity for “built for this commit”:** manifest **digest** (ground truth) vs **git-SHA tag** (traceability pointer) vs both.
- [ ] **Whether `ship` auto-skip may call the registry** (approach B) or stays **offline** (approach A only).
- [ ] **Immutable tags policy** on Artifact Registry for production repository (optional hardening).
- [ ] **Pin base images** in Dockerfile by **digest** when reproducibility matters.

## Open questions

1. Should **CI** be the only producer of **prod** images, with **local `just image`** only for dev—making **registry + SHA tag** the single gate?
2. Is **network access** acceptable during `just ship` for a **read-only** Artifact Registry query?
3. Do we need a **single** “expected digest” file checked into repo or generated in CI for Cloud Run job updates?

## Resolved questions

_(none yet)_
