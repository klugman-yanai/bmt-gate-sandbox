# Value objects vs primitives / Pydantic models — investigation

**Summary:** Where custom or built-in value objects would improve type safety, reduce duplication, or enforce invariants instead of plain `str` or Pydantic models.

---

## Current state

| Area | Current | Notes |
|------|--------|--------|
| **IDs** | `run_id`, `workflow_run_id`, `bmt_id` as `str` | Sanitization and max length (200) enforced at use sites; logic duplicated in `.github/bmt/ci/core`, `tools/shared/trigger_uris.py`, `tools/shared/verdict.py`. |
| **Decisions / reason codes** | String constants (`DECISION_ACCEPTED`, `REASON_RUNNER_FAILURES`, etc.) and plain `str` fields | Compared with `in (DECISION_ACCEPTED, ...)` or passed through to JSON/GitHub. |
| **Status** | `"pending"`, `"success"`, `"failure"`, etc. as `str` | Used in Check Run API, commit status, and internal aggregates. |
| **GCS URIs** | `str`: `gs://bucket` or `gs://bucket/prefix/path` | Built with f-strings; parsing (bucket vs prefix) done ad hoc with `removeprefix`/`partition`. |
| **Paths** | `pathlib.Path` for filesystem; `str` for GCS prefixes | `StageRuntimePaths` is already a frozen dataclass (value-object-like). |
| **Config / context** | Pydantic `BmtConfig`, `BmtContext`, `WorkflowRequest`, `LegSummary`, etc. | DTOs for boundaries; appropriate. |
| **Runtime SDK** | Frozen dataclasses in `gcp/image/runtime/sdk/results.py` | `PreparedAssets`, `CaseResult`, `VerdictResult` — value objects; fields like `status`, `reason_code` still `str`. |

---

## Recommendations

### 1. RunId / WorkflowRunId (high value)

**Problem:** Sanitization and max length are rules that live in three places; any caller can pass an unsanitized string.

**Options:**

- **Custom value object:** A small immutable wrapper that is constructed only via a factory that sanitizes and truncates. All APIs that today take `workflow_run_id: str` would take `run_id: RunId`; `.raw` or `str(run_id)` for GCS paths and JSON.
- **NewType + factory:** `RunId = NewType("RunId", str)` plus `def run_id(s: str) -> RunId` that sanitizes and returns. No extra type at runtime; nominal typing only.

**Recommendation:** Prefer a **single shared factory** (e.g. in `tools/shared/trigger_uris.py` or a small `gcp.image.config.run_id` module) used by CI, VM, and tools, and consider `NewType("RunId", str)` + factory so that only sanitized IDs are passed. Full value object (frozen dataclass with one field) is optional and adds minimal benefit over NewType.

### 2. Decision / ReasonCode / Check status (medium value)

**Problem:** Magic strings; typos only show at runtime; two constant sets (CI `core.py` vs `gcp/image/config/constants.py`).

**Options:**

- **Keep str + constants:** Current approach; document and keep one canonical list.
- **Literal:** `Decision = Literal["accepted", "accepted_with_warnings", "rejected", "timeout"]` and similarly for reason codes. Pydantic serializes to string; good for validation at boundaries.
- **Enum:** `class Decision(str, Enum): ACCEPTED = "accepted"; ...` — same serialization, clearer exhaustiveness in `match`/`if` and IDE support.

**Recommendation:** Use **Enums** (or `Literal`) for the small closed sets: **Decision** (gate), **ReasonCode** (leg/verdict), and **Check/commit status** (`pending` / `success` / `failure`) where they are set in code. Keep Pydantic models that cross JSON/env boundaries using `str` with validators that accept the enum (or keep string for maximum flexibility and validate only where needed). Consolidate constants so CI and gcp/image share one definition (e.g. in `gcp/image/config/constants.py`).

### 3. GCS URIs (medium value)

**Problem:** Bucket root vs full object URI are both `str`; parsing repeated in a few places (`removeprefix("gs://")`, `partition("/")`).

**Options:**

- **Keep str:** Document pattern (e.g. `bucket_root` is `gs://<bucket>`, object URI is `gs://<bucket>/key`).
- **Small value type:** e.g. `GcsBucketRoot(uri: str)` that parses once and exposes `.bucket`, `.uri`; or `GcsObjectUri` with `.bucket` and `.key`. Construction validates format.

**Recommendation:** Introduce a **tiny helper type** only if parsing grows or bugs appear (e.g. `GcsBucketRoot` wrapping `gs://bucket` with `.bucket` and `.uri`). Otherwise, keep `str` and centralize helpers like `bucket_root_uri(bucket: str)` and one place that parses a full URI into bucket + prefix.

### 4. Results path (implemented)

**Problem:** Bucket-relative result roots were plain `str` and mixed naming with the JSON key `results_prefix`.

**Implemented:** `ResultsPath` (`NewType`) plus `as_results_path()` in `gcp/image/config/value_types.py`; Pydantic models use Python field `results_path` with `validation_alias` / `serialization_alias` `results_prefix` so on-disk JSON is unchanged. Helpers like `tools/shared/verdict.py` take `ResultsPath | str`. A single global bucket name does **not** use `BucketName` NewType (overkill).

### 5. Path (already good)

**Current:** `pathlib.Path` for filesystem paths; `StageRuntimePaths` as frozen dataclass.

**Recommendation:** **No change.** Keep using `Path` and frozen dataclasses for path groups.

### 6. Pydantic models (keep)

**Current:** `BmtConfig`, `BmtContext`, `WorkflowRequest`, `PlanLeg`, `LegSummary`, etc. are Pydantic models for config, API, and workflow boundaries.

**Recommendation:** **Keep.** Value objects are for *small domain concepts* (IDs, codes, URIs). Config and context are DTOs; Pydantic is the right tool. Optional: use `Literal` or `Enum` for specific fields (e.g. `status: Literal["pending", "success", "failure"]`) inside those models if you want validation at parse time.

---

## Implementation status (repo)

1. **Run-id sanitization** — `gcp/image/config/value_types.py` (`sanitize_run_id`, `RUN_ID_MAX_LEN`, `RunId`, `as_run_id`). Used by `.github/bmt/ci/core.py`, `tools/shared/trigger_uris.py`, `tools/shared/verdict.py`.
2. **GateDecision / ReasonCode** — `gcp/image/config/decisions.py`; string re-exports in `constants.py`; `decision_exit()` accepts `str | GateDecision`; `github_checks` uses `ReasonCode` for runner failure reasons.
3. **GcsBucketRoot** — Not added (still `str` + helpers).
4. **ResultsPath** — As above; JSON key remains `results_prefix`.

---

## References

- **Architecture skill:** DDD value objects — immutable, defined by attributes, encapsulate validation.
- **Existing value-object-like code:** `StageRuntimePaths`, `PreparedAssets`, `CaseResult`, `VerdictResult` in `gcp/image/runtime/sdk/results.py`.
- **Constants:** `gcp/image/config/constants.py` (decision/reason/env names); `.github/bmt/ci/core.py` (decision + URI helpers).
