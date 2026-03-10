# Sample BMT output

Reference for workflow logs, PR comment, and Checks tab.

| Term | Meaning |
|------|---------|
| **BMT** | Batch test across projects (each project + BMT = one run) |
| **BMT Gate** | Status check required to merge |
| **Checks tab** | "Checks" at top of PR |

| Pass/fail | Summary + links | VM started |
|-----------|-----------------|------------|
| Checks tab → BMT Gate | PR comment | Actions → Prepare + Handoff |

---

## 1. Workflow (Actions)

Workflow writes trigger to GCS, starts VM, waits for ack. BMT runs on the VM; pass/fail is in Checks tab, not in the workflow log. **Workflow success** = trigger written + VM acked (not BMT pass/fail).

**Step summary:**

```
## BMT Handoff

PR [#52](url) · [Workflow run](url) · `abc1234` on `feature/foo`

| | |
|---|---|
| Trigger written | ✅ |
| VM started | ✅ |
| Handshake acked | ✅ |
| Legs handed off | **2** |

Handoff complete: VM acknowledged trigger.

_BMT result will appear in the PR **Checks** tab and **Comments** — not here._
```

**Failure example** (handshake did not ack):

```
| Handshake acked | ❌ |
...
Handoff failed: VM did not acknowledge trigger.

_Handoff failed — inspect the trigger and handshake steps above for details._
```

---

## 2. PR comment

One comment per tested commit, updated in place. Inline links, no table.

**Pass:**

```
## ✅ BMT passed

[`abc1234`](url) · [Workflow run](url) · [Checks](url)

All tests passed.
```

**Fail:**

```
## ❌ BMT failed

[`abc1234`](url) · [Workflow run](url) · [Checks](url)

Failed: **SK · False Reject Namuh**
For details, open the **Checks** tab on this PR.
```

**Superseded:**

```
## ⏭️ BMT superseded

[`abc1234`](url) · [Workflow run](url) · [Checks](url)

A newer commit arrived — this run was cancelled.

Superseded by [`def5678`](url)
```

**Did not run:**

```
## ⚠️ BMT did not run

[`abc1234`](url) · [Workflow run](url) · [Checks](url)

The test runner could not start.
For details, open the **Checks** tab on this PR.
```

---

## 3. Checks tab (BMT Gate)

**In progress** — title e.g. `Running — 0/1 complete`; updates ~30s:

```
**0/1 complete** · 1m 30s elapsed · ~3m left

| Project | BMT | Status | Progress | Duration |
|---------|-----|--------|----------|----------|
| sk | false_reject_namuh | 🔵 running | 412/800 | — |

_Updated 12:05 UTC_
```

**Pass** — title `BMT Gate`:

```
| Project | BMT | Verdict | Score | Baseline | Delta | Reason | Duration |
|---------|-----|---------|-------|----------|-------|--------|----------:|
| sk | false_reject_namuh | ✅ PASS | 42.5 | 42.2 | +0.30 | Score at or above baseline | 3m 45s |
```

**Fail** — same table with ❌ FAIL row + next steps:

```
| sk | false_reject_namuh | ❌ FAIL | 41.0 | 42.2 | -1.20 | Score dropped below baseline | 3m 50s |

**Next steps**

- Score dropped below baseline — see delta above. Baseline updates on next passing merge.
```

**Error** — ⚠️ ERROR row; Score/Baseline/Delta = —. If runner failed:

```
| sk | false_reject_namuh | ❌ FAIL | — | — | — | One or more runner processes exited non-zero or timed out | — |

**Next steps**

- Runner failed — check per-file logs:
  - `sk.false_reject_namuh`: `gs://bucket/runtime/.../logs/`
```
