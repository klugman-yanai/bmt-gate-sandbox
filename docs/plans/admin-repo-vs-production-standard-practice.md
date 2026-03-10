# Admin repo vs production: standard practice and recommended approach

You have an **admin repo** (or dev/sandbox) where you have full control for testing, and **production** (core-main) where you are not an admin. You need a sustainable way to develop and then get code into production without drift or permission bottlenecks.

**Constraint for this project:** core-main **cannot** reference an external repo; the workflow and BMT code **must live inside** core-main. So production always holds a **copy** of the files. The approach below is chosen for that constraint.

---

## Recommended approach: canonical repo + sync

Because the code must be in core-main (no external reusable workflows), the standard approach is **single source of truth with copy-based sync**:

- **bmt-gcloud** = canonical source. You author and maintain BMT workflows, actions, and `.github/bmt/` here. You have full control.
- **bmt-gate-sandbox** = copy from bmt-gcloud for testing. You deploy `dummy-build-and-test.yml` as `build-and-test.yml` and keep workflows/actions in sync. You have full control.
- **core-main** = updated via **PRs** that bring in the same files from bmt-gcloud. You open PRs; upstream maintainers merge. Until they merge, production can drift; you manage that by running **`just diff-core-main`** regularly and opening PRs to align.

**Concrete workflow:**

1. Change workflows/actions in **bmt-gcloud**. Test locally and in sandbox.
2. Run **`just diff-core-main`** (with `CORE_MAIN` set to your core-main clone). See what differs.
3. Open a **PR to core-main** with the bmt-gcloud version of the changed files. In the PR description, note that the change aligns with bmt-gcloud (canonical source).
4. After upstream merges, diff again to confirm no drift. If someone else changed production, either align bmt-gcloud to that or open a follow-up PR to restore alignment.

See [maintaining-sandbox-and-production.md](../maintaining-sandbox-and-production.md) and [drift-core-main-vs-bmt-gcloud.md](../drift-core-main-vs-bmt-gcloud.md) for the file list to diff and how to resolve drift.

---

## Other patterns (for context)

- **Fork + PR:** You could fork core-main and develop there (same layout as production). Canonical repo + sync keeps BMT development in bmt-gcloud and avoids maintaining a full fork; both are valid.
- **Reusable workflow from another repo:** Would remove drift (production would call `uses: owner/repo/.github/workflows/bmt.yml@ref`), but **core-main cannot reference an external repo**, so this option does not apply.

---

### Canonical repo + sync (what we use)

**Pattern:** One repo is the canonical source (bmt-gcloud). Production holds a **copy** of the files and is updated via PRs from that source. You run a diff regularly (`just diff-core-main`) and open PRs to align production with canonical.

**Fit:** Required when production must contain the code (no external workflow reference). This is the approach for this project.

---

### Separate “pipeline” repo (org-level)

**Pattern:** Org has a repo (e.g. `Kardome-org/bmt-workflows`) for shared workflows; production either calls it or copies from it.

**Fit:** Same “must be in core-main” constraint applies if production can’t reference it; then it’s still copy-based sync from that repo.

---

## Summary

| Approach | Use here? | Why |
|----------|-----------|-----|
| **Canonical repo + sync (diff + PR)** | **Yes** | Code must live in core-main; bmt-gcloud is source of truth; we sync via PRs and `just diff-core-main`. |
| **Fork + PR** | Optional | You could fork core-main and develop there; canonical repo + sync keeps BMT in bmt-gcloud and avoids maintaining a full fork. |
| **Reusable workflow from another repo** | **No** | core-main cannot reference an external repo. |
