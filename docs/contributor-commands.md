# Contributor commands (Just)

Short answers for recipes that look cryptic in `just list` or `just tools --help`. For the full scaffold flow, still read [adding-a-project.md](adding-a-project.md).

---

## Why `just onboard` uses `*args`

The recipe runs `bash tools/scripts/bootstrap_dev_env.sh` and **forwards every extra token** you type after `onboard` to that script.

- **Reason:** Bootstrap flags can change (e.g. `--dry-run`) without editing the Justfile for each one.
- **Example:** `just onboard --dry-run` → script sees `--dry-run`.

The **Rich summary** (`uv sync`, hook story) comes from **`uv run python -m tools onboard`**, which the bootstrap script runs at the end. For **only** that summary (e.g. after a dry run), use **`just tools onboard --dry-run`** — that is the Typer command, not the shell script.

---

## `just add <project>`

Runs **`uv run python -m tools add`** — one entry point to:

- create **`benchmarks/projects/<project>/`** (if it does not exist yet), and optionally
- add **`--bmt=<folder>`** (new `bmts/<folder>/bmt.json`), and/or
- upload a dataset with **`--data=<path>`** (directory, `.zip`, or `.tar`/`.tar.gz`/`.tgz`; 7z is not supported—extract first).

Combine flags in one line, e.g. **`just add sk --bmt=false_alarms --data=./audio.zip`**.

Lower-level equivalents: **`just stage project`**, **`just stage bmt`**, **`just upload-wav`**. Private Just aliases **`add-project`** / **`add-bmt`** still map to **`stage project`** / **`stage bmt`**.

---

## `just publish` and `just test-local`

- **`just test-local`** — fast **`pytest tests/tools`** + **`ruff`** on `tools/bmt` and `tools/cli`. Run before publish; see [local-bmt-testing.md](local-bmt-testing.md).
- **`just publish`** — **`uv run python -m tools publish`**. Builds the plugin bundle, sets **`enabled`: true** in `bmt.json` (unless **`--no-enable`**), and syncs the project subtree to GCS (unless **`--no-sync`**). With **exactly one** BMT under `benchmarks/projects/`, no arguments are needed; otherwise pass **`project`** and **benchmark folder**, or set **`BMT_PROJECT`** and **`BMT_BENCHMARK`**. **`just tools bmt verify <project> <folder>`** loads the workspace plugin locally first.

Typer equivalents: **`just tools bmt stage publish …`** (explicit args) or **`just tools publish …`**.

---

## When to use `just stage`

`just stage` is **`uv run python -m tools bmt stage`** — the **low-level** group for editing the staged tree. Prefer **`just add`** / **`just publish`** for the common path.

| Subcommand | Role |
| ---------- | ---- |
| **`stage project`** | Same as **`just add <name>`** with no flags. |
| **`stage bmt`** | Same as **`just add <project> --bmt=<folder>`** (no upload). |
| **`stage publish`** | Same idea as **`just publish <project> <folder>`** (Typer also has root **`tools publish`**). |

Pushing the **full** `benchmarks/` mirror to the bucket is **`just sync-to-bucket`**, not `stage publish` (that syncs **one project** subtree during publish).

Run **`just stage --help`** or **`just tools bmt stage --help`** for flags (e.g. `--dry-run` on `project`).

---

## `just upload-wav <project> <source>`

Arguments are **positional** (Typer: `tools bucket upload-wav`):

| Argument | Meaning |
| -------- | ------- |
| **`project`** | The **project name** — same segment as in `benchmarks/projects/<project>/` (e.g. `myproject`). Data lands under `projects/<project>/inputs/<dataset>/` in GCS. |
| **`source`** | A **local path**: either a **`.zip`** archive of WAVs or a **directory** containing WAV files. Not a `gs://` URI. |

Common options (after the two positionals):

- **`--dataset <name>`** — Override the dataset folder name under `inputs/`. If omitted, it is inferred (e.g. from the zip basename).
- **`--local`** — Also mirror into `benchmarks/` (default is **GCS only**; datasets can be huge).

See **`just tools bucket upload-wav --help`** for `--force` and details.

---

## What `just workspace` is

`just workspace` runs **`uv run python -m tools workspace`**. It is an **umbrella** for several **subcommands** — there is no single “workspace” action until you pick one:

| Subcommand | What it does (typical use) |
| ---------- | -------------------------- |
| **`deploy`** | Upload local **`benchmarks/`** to your **GCS bucket** and verify — run after you change staged config and need CI to see it. Shorthand: **`just sync-to-bucket`**. |
| **`pulumi`** | Pulumi apply + push GitHub repo vars (infra). |
| **`validate`** | Compare GitHub repo variables to what Pulumi expects. |
| **`preflight`** | Bucket vs **backend** / image checks (and optional image build); heavy sanity check before ship. |
| **`e2e`** | Local E2E readiness / preflight toward a real handoff (see help). |

**Most contributors upload to the bucket often** once a project exists: edit under `benchmarks/…`, then **`just sync-to-bucket`** (same as **`just workspace deploy`**) so the cloud copy matches your repo.

Run **`just workspace --help`** for the full list and flags.

---

## See also

- [adding-a-project.md](adding-a-project.md) — ordered steps for a new project or BMT.
- [local-bmt-testing.md](local-bmt-testing.md) — checks before `just publish`.
- [CONTRIBUTING.md](../CONTRIBUTING.md) — install order, hooks, `just test`.
