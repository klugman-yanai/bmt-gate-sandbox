# ADR 0003: `ScorePayload.extra` reporting contract (multi-plugin)

## Status

Accepted (2026-03-23)

## Context

BMT legs produce [`LegSummary`](../../runtime/models.py) with [`ScorePayload`](../../runtime/models.py): `aggregate_score`, `metrics`, and `extra`. Multiple projects and BMTs can coexist; each [`BmtPlugin`](../../sdk/bmt_sdk/plugin.py) may attach **plugin-specific** metadata for GitHub Checks and GCS snapshots.

The presentation layer must stay **generic**: it should branch on **declared structure** in `extra`, not on `project` or `bmt_slug`.

## Decision

1. **Namespaced blobs** — Plugins SHOULD place machine-readable reporting data under stable keys:
   - `scoring_policy` — policy snapshot (comparison, reducer, direction labels, optional `schema_version`, optional `reporting_hints`).
   - Other keys MUST be namespaced or documented here before wide use (e.g. `baseline_present`, `unavailable` coordinator flags).

2. **Versioning** — `scoring_policy` SHOULD include `schema_version` (string) so formatters can evolve. Consumers MUST treat unknown versions as opaque or fall back to generic display.

3. **Optional `reporting_hints` in manifest** — [`plugin_config`](../../gcp/stage/projects/sk/bmts/) MAY include a `reporting_hints` object copied into `scoring_policy` for operator-facing copy. This does not change gating math.

   Documented optional keys (plugins MAY add more; formatters SHOULD ignore unknown keys):

   - `utterances_per_file` — declared cardinality for labels / drift (integer or as documented by the plugin).
   - `dataset_note` — methodology line (e.g. how the aggregate is computed).
   - `metric_short_label` — short human label for the aggregate (e.g. “keyword hits per file (avg.)”) so Checks tables are not anonymous numbers.
   - `success_in_words` — one or two sentences: what “good” looks like **for this leg**, including asymmetry vs other legs (e.g. lower-is-better vs higher-is-better). Use this to avoid misleading “x/100” framing when aggregates are raw counts.
   - `aggregate_explainer` — optional longer prose; may overlap `dataset_note`; prefer not to duplicate in the same run.

   **Declared vs observed:** Manifests MAY declare dataset cardinality; legs MAY record observed counts in `metrics`. Presentation MAY surface drift when both exist and the plugin opts in (future convention).

4. **Per-case rows** — When present, `metrics.case_outcomes` is a list of objects with at least `case_id`, `status`, and plugin-defined metric fields; used for Checks tables and `case_digest.json`.

5. **Cross-leg comparability** — Aggregates are **not** assumed comparable across legs unless a plugin documents a normalized field. Checks copy MAY state this when multiple legs are shown.

## Consequences

- New plugins SHOULD document their `extra` / `metrics` shapes (short appendix or follow-up ADR).
- GitHub Checks output MUST respect API size limits; [`github_checks`](../../runtime/github/github_checks.py) clamps UTF-8 byte length for `summary` / `text`.

## References

- [`docs/architecture.md`](../architecture.md) — pipeline and storage
- [`runtime/github/presentation.py`](../../runtime/github/presentation.py) — Check Run Markdown
