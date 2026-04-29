# `kardome-bmt` (CI / handoff CLI)

This directory is the **`kardome-bmt`** workspace member ([`pyproject.toml`](pyproject.toml)).

- **Console:** `uv run kardome-bmt …` from the repo root (after `uv sync`). A legacy alias **`bmt`** points at the same entrypoint.
- **Import package:** `kardome_bmt` — e.g. [`kardome_bmt/handoff.py`](kardome_bmt/handoff.py).

Production GitHub workflows typically use the release **`bmt.pex`** via [`.github/actions/setup-bmt-pex`](../.github/actions/setup-bmt-pex/action.yml) instead of vendoring this tree.

## Matrix snapshot commands

- **`matrix extract-core-main-presets`** — emits `presets_release` / `presets_nonrelease` (same rules as Kardome-org/core-main **extract-presets**; needs `CMakePresets.json`, `bmt/<key>/run-bmt.sh` checks).
- **`matrix ci-snapshot-bmt-gcloud`** — emits `release_presets` / `non_release_presets` (parity with this repo **`build-and-test.yml`** `repo_snapshot`, formerly `jq`).
- **`runner filter-bmt-presets`** — scans `upstream-artifacts/*/metadata.json` (override with `FILTER_BMT_ARTIFACT_ROOT`); writes `matrix`, `count`, `has_presets`.

Use env `BMT_REPO_ROOT` when the presets file paths are relative (default `.`). Outputs require `GITHUB_OUTPUT` except when piping locally.

## Consumer repos (e.g. core-main)

Cross-repo callers depend on **`bmt-gcloud`** as a **git** or **index** source (see root [`pyproject.toml`](../pyproject.toml) `[tool.uv.sources]`). They do **not** install from `.github/bmt`; pin **`rev`** to a tag or full SHA when using git sources.

After configuring sources, run **`uv lock`** / **`uv sync`**, then **`uv run kardome-bmt …`** (or invoke the PEX in CI). Prefer pinning **`uses: klugman-yanai/bmt-gcloud/.../@bmt-v*`** once the snapshot commands you need ship in **`bmt.pex`** built from that tag.
