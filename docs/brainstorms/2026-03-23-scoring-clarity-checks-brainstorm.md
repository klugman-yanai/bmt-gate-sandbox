# Brainstorm: Clearer scoring explanation in GitHub Checks (BMT Gate)

**Date:** 2026-03-23  
**Scope:** Reporting UX only (especially Check Run `summary` / `text`), not changing SK math unless a later plan says so.

## What we're building

Operators should **understand what the number in the Score column means** without reading source code: which metric it is, how it was combined across files, whether higher or lower is better for *this* leg, and how that relates to pass/fail (baseline vs bootstrap).

Today the implementation can show:

- A numeric aggregate, optionally suffixed with `(lower better)` or `(higher better)` for SK legs.
- Per-case failure tables and optional Check annotations for failed cases.

**Remaining confusion** often comes from:

- Treating the aggregate like a **percentage or fixed target** (e.g. “goal 0” vs “goal 100”) when it is usually a **mean of per-file counters** (`namuh_count`).
- Comparing **false_alarms** and **false_rejects** scores side by side as if they were the same scale.
- **Bootstrap** runs where baseline wording is easy to misread.

## Why this matters

The Checks tab is the first place many people look. A short, consistent **“How to read this run”** block reduces mis-triage (“scoring bug” vs “expected mean”) and aligns support with the actual contract (metric + reducer + comparison).

## Approaches (pick one primary; others optional)

### A — Inline legend in every final Check output (recommended)

Add a small **Markdown section** near the top of `text` (below the summary lines or above the table), e.g. **“How scores work (SK)”**, with bullets:

- What the number is (e.g. mean of `namuh_count` over **OK** cases).
- Direction: lower vs higher better for this leg (tie to `comparison` / manifest).
- That failed cases are listed separately and do not contribute to the mean.
- One line on bootstrap vs baseline when `verdict_summary` / reason implies it.

**Pros:** Self-contained; no external doc dependency; works in email/exports.  
**Cons:** Slightly longer Check output; wording must stay accurate when non-SK projects appear in the same run.

**Mitigation:** Show the legend only when the row (or plan) is SK / when `scoring_policy` is present.

### B — Rename or qualify the table column

Replace or augment **Score** with **Aggregate** or **Mean (NAMUH)** when metadata is available.

**Pros:** Immediate clarity in the table.  
**Cons:** Wide columns on mobile; needs short labels for non-SK legs (“Score” fallback).

### C — Summary line + doc link

Add one sentence in `summary` and a link to a stable docs anchor (e.g. configuration or architecture) for full detail.

**Pros:** Minimal UI churn.  
**Cons:** Extra click; docs must stay in sync.

## Recommendation

**Lead with A**, optionally add **B** for the column header only (short label), and use **C** only if the legend grows too long—then trim bullets and link out.

## Key decisions (proposed)

| Decision | Proposal |
| -------- | -------- |
| Legend placement | Fixed subsection in final `text`, above the main results table (or immediately after summary block). |
| SK vs generic | Legend title/body keyed off presence of `scoring_policy` / project; generic runs keep a one-line “Score = leg aggregate” note or omit. |
| Baseline language | Reuse existing reason codes / `verdict_summary` to say “first run / baseline stored” vs “compared to previous” in plain language. |

## Open questions

1. Should the legend **name the metric explicitly** (`NAMUH` / `namuh_count`) for all SK legs, or use a friendlier label (“keyword hit count”) with a footnote?
2. For **multi-project** Check runs, is one shared legend enough, or do we need a **per-row footnote** when legs use different policies?
3. Is **localization** (non-English) a requirement for this text?

## Resolved questions

_(None yet.)_

---

**Next step:** If this direction looks right, run `/workflows:plan` (or the repo’s planning flow) to implement legend copy + placement and any column rename, with presentation tests.
