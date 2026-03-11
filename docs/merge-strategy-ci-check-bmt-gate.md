# Merge strategy: one branch into ci/check-bmt-gate

## Situation

- **ci/check-bmt-gate** – integration branch; has merge #61 ("test: clean BMT gate validation (Python 3.12)").
- **test/clean-bmt-gate-v2** – 12 commits ahead with the latest work (push trigger, merge conflict fixes, Packer fixes, etc.).

Goal: only the newest, up-to-date changes end up in ci/check-bmt-gate, without duplicate or conflicting history.

## Recommended approach: single source of truth then one merge

Use **test/clean-bmt-gate-v2** as the single source of truth, then merge it into ci/check-bmt-gate once.

### Step 1: Bring ci/check-bmt-gate into test/clean-bmt-gate-v2 (optional but safe)

This picks up any commit that exists only on ci/check-bmt-gate (e.g. the merge #61 and any follow-up) so you resolve conflicts once on the feature branch.

```bash
git checkout test/clean-bmt-gate-v2
git pull origin test/clean-bmt-gate-v2   # ensure up to date
git merge origin/ci/check-bmt-gate -m "Merge ci/check-bmt-gate into test/clean-bmt-gate-v2"
# Resolve conflicts if any (prefer test/clean-bmt-gate-v2 for workflow/packer/tools).
git push origin test/clean-bmt-gate-v2
```

### Step 2: Merge test/clean-bmt-gate-v2 into ci/check-bmt-gate

- **Option A (PR):** Open a PR **test/clean-bmt-gate-v2 → ci/check-bmt-gate**, review, then merge. CI will run from the PR branch.
- **Option B (local):** Merge locally and push (only if you have push access and no PR required):

```bash
git checkout ci/check-bmt-gate
git pull origin ci/check-bmt-gate
git merge origin/test/clean-bmt-gate-v2 -m "Merge test/clean-bmt-gate-v2: push trigger, Packer fixes, merge resolutions"
git push origin ci/check-bmt-gate
```

After this, ci/check-bmt-gate has a single merge with the full v2 state.

## If you use a branch named ci/check-bmt-gate-single

If **ci/check-bmt-gate-single** is meant to be the single integration branch that will be merged into ci/check-bmt-gate:

1. Make it match the desired final state:
   - Either **reset** it to test/clean-bmt-gate-v2:  
     `git checkout ci/check-bmt-gate-single && git reset --hard origin/test/clean-bmt-gate-v2`  
     then push (force if it already exists on the remote).
   - Or **merge** test/clean-bmt-gate-v2 into it:  
     `git checkout ci/check-bmt-gate-single && git merge origin/test/clean-bmt-gate-v2`  
     then push.

2. Then merge **ci/check-bmt-gate-single** into **ci/check-bmt-gate** (via PR or local merge as above).

That way only ci/check-bmt-gate-single (or test/clean-bmt-gate-v2) carries the “newest” changes, and ci/check-bmt-gate gets one merge from that branch.

## Summary

| Branch                    | Role                                      |
|---------------------------|-------------------------------------------|
| test/clean-bmt-gate-v2    | Single source of truth (newest changes)   |
| ci/check-bmt-gate         | Integration target (receives one merge)   |
| ci/check-bmt-gate-single  | Optional; keep in sync with v2 then merge |

Result: only the newest, up-to-date changes are in ci/check-bmt-gate, with a clear, single merge from the chosen source branch.
