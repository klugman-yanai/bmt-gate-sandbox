# Agent-Native Audit: Image Build, Variables, and Workflow

Focused review of **image build**, **variables** (design and flow), and **how they relate to workflow code**, assessed against agent-native architecture principles. "Agent" here means an AI coding agent (e.g. Cursor/Claude) working in this repo.

---

## 1. Design Summary

### Image build

- **Workflow:** `.github/workflows/bmt-vm-image-build.yml` (Packer + SLSA provenance).
- **Inputs:** `vars.GCP_PROJECT`, `vars.GCP_ZONE`, `vars.GCS_BUCKET`, `vars.GCP_SA_EMAIL`, `vars.GCP_WIF_PROVIDER`; optional `vars.BMT_EXPECTED_IMAGE_FAMILY`, `vars.BMT_EXPECTED_BASE_IMAGE_FAMILY`, `vars.BMT_EXPECTED_BASE_IMAGE_PROJECT`; workflow_dispatch inputs (image_family, base_image_*, machine_type).
- **Gate:** Handoff workflow runs `check-image-up-to-date`, which verifies a successful image build exists for the ref when `infra/packer` or `gcp/image` changed.
- **Relationship to workflow:** Handoff does **not** pass image family or build ID to later jobs; it only checks “image build ran.” VM is started with whatever image Terraform/VM metadata specify; image build workflow is decoupled from handoff env.

### Variables

- **Sources of truth:**
  - **Terraform** (infra/terraform): outputs → `terraform_repo_vars.py` → GitHub repo vars. Defines GCS bucket, project, zone, VM name, service account, repo root.
  - **constants.py** (gcp/image/config): `PUBSUB_TOPIC_NAME`, `STATUS_CONTEXT`, `DEFAULT_REPO_ROOT`. Code and fallback workflow step read these; Terraform keeps a matching literal for topic name (parity test).
  - **bmt_config.py**: Schema and defaults for runtime config; env keys whitelist; no second source of truth for values that live in Terraform/constants.
- **Contract:** `tools/repo/vars_contract.py` — required (GCS_BUCKET, GCP_PROJECT, GCP_ZONE, BMT_LIVE_VM, GCP_SA_EMAIL), optional (BMT_REPO_ROOT), secrets not in Terraform (GCP_WIF_PROVIDER, BMT_DISPATCH_APP_ID). Defaults from constants/BmtConfig for optional vars.
- **actionlint:** `.github/actionlint.yaml` lists allowed config-variables (includes BMT_EXPECTED_* and BMT_VM_POOL, BMT_VM_POOL_LABEL, etc.) so actionlint doesn’t flag them. Handoff workflow **env** only sets a subset (no BMT_STATUS_CONTEXT, BMT_PUBSUB_TOPIC — those come from constants/code).

### Workflow code

- **Handoff** (`bmt-handoff.yml`): Top-level `env` from `vars.*` (GCS_BUCKET, GCP_*, BMT_LIVE_VM, BMT_VM_POOL). Jobs pass these (and step outputs) into composite actions. Constants (e.g. status context for failure fallback) are read from Python at runtime in one step (`Set BMT constants for fallback`).
- **Image build** (`bmt-vm-image-build.yml`): Reads vars for PKR_VAR_* and optional BMT_EXPECTED_*; no shared env with handoff beyond the same repo vars.
- **Relationship:** Shared repo variables (GCP_*, GCS_BUCKET, BMT_LIVE_VM) so both workflows and CLI use the same GCP identity and bucket. Image build has its own optional vars (BMT_EXPECTED_*) not in vars_contract; handoff doesn’t need image family in env.

---

## 2. Principle-by-Principle Assessment

### Action parity — “Whatever the user can do, the agent can do”

| User action | How agent can do it | Status |
|------------|----------------------|--------|
| Trigger image build | `gh workflow run bmt-vm-image-build.yml` or `just build` | ✅ Same commands |
| Check/apply repo vars | `just validate`, `just terraform` | ✅ Same commands |
| Run BMT handoff | Trigger workflow via UI or `gh workflow run` with inputs | ✅ Same |
| Change a constant (e.g. topic name) | Edit `gcp/image/config/constants.py` and `infra/terraform/main.tf`, run parity test | ✅ Parity test enforces both |
| Set optional image-build vars (BMT_EXPECTED_*) | `gh variable set`; not in vars_contract so not applied by terraform-export-vars | ⚠️ Agent can set them, but discovery is only via actionlint / workflow YAML, not contract |
| See which vars the handoff uses | Read bmt-handoff.yml `env:` and actions; or CLAUDE.md / docs | ✅ No single “handoff env spec” doc; agent infers from workflow + contract |

**Score: 5/6 (83%) — Good.** One gap: optional image-build vars (BMT_EXPECTED_*) are not part of the contract or Terraform export, so “expected” values for image policy are only in workflow and actionlint. Agent can still set them via `gh variable set` if it finds them in YAML.

---

### Tools as primitives — “Tools provide capability, not behavior”

| Capability | Implemented as | Primitive? |
|------------|----------------|------------|
| Build VM image | Workflow (Packer + steps) | Yes — single outcome “build image” |
| Export Terraform → repo vars | `terraform_repo_vars.py` (read outputs, set vars) | Yes — capability “sync Terraform to GitHub vars” |
| Check repo vars vs contract | `gh_repo_vars.py` | Yes — read + compare |
| Run handoff pipeline | Workflow + composite actions | Orchestration — but agent doesn’t need to reimplement it; agent triggers workflow or runs CLI steps |
| Get config in CLI/actions | `get_config(runtime=env)` from bmt_config | Yes — read config from env whitelist + defaults |

Variables and image build are consumed by workflows and CLI as **inputs** (env, vars). The “tools” an agent uses are: edit files, run `just`/`uv`/`gh`/`gcloud`. No workflow-shaped “do the whole handoff” tool; handoff is triggered, not reimplemented. So design is primitive-friendly.

**Score: 5/5 (100%)** for this subsystem — variables and image build are used as data/config, not as bundled workflows exposed to an agent.

---

### Context injection — “System prompt includes dynamic context about app state”

- **For a human/agent:** CLAUDE.md, infra/README.md, docs/configuration.md, and .github/bmt/config/README.md describe vars, Terraform, and that workflow gets env from repo variables. No single “at runtime, these are the exact env keys the handoff job sees” document.
- **For the workflow:** Job env is static (vars.* and inputs). The only “injected” dynamic context is step outputs (e.g. selected_vm, handshake_ok) passed between jobs and into composite actions. Constants (STATUS_CONTEXT) are injected by a step that runs Python.
- **Gap:** A new contributor (or agent) might not know that BMT_STATUS_CONTEXT and BMT_PUBSUB_TOPIC are **not** in workflow env and come from constants/code. That’s documented in constants.py and in the workflow comment, but not in one “variables and constants” section in CLAUDE.md.

**Score: 3/5 (60%).** Context exists but is spread across several files; no single “variables + constants + workflow env” map in the main agent-facing doc.

---

### Shared workspace — “Agent and user work in the same data space”

- Repo (files, `gcp/`, `infra/`, `.github/`) is the shared workspace. GitHub repo variables and Terraform state are shared too — agent and human both use the same vars and same workflows.
- Image build writes to GCS (bucket from vars) and to workflow artifacts; handoff reads from vars and from GCS. No separate “agent sandbox” for variables or image.

**Score: 5/5 (100%).**

---

### CRUD completeness — “Every entity has full CRUD”

| Entity | Create | Read | Update | Delete |
|--------|--------|------|--------|--------|
| Repo variables | `gh variable set` (via `just terraform`) | `gh variable list` / `just validate` | `gh variable set` | `gh variable delete` (manual or prune) |
| Terraform outputs | Terraform apply | `terraform output` / terraform_repo_vars | N/A (outputs mirror state) | N/A |
| VM image | Image build workflow | `gh run list` / check-image-up-to-date; GCS provenance | New build (new image name) | Not automated (GCE images are immutable; old ones can be deleted manually) |
| Workflow run | `gh workflow run` / UI | `gh run list` / `gh run view` | N/A | Cancel only |

Repo variables: full CRUD. Image: Create + Read; Update = new build; Delete is manual. Workflow runs: Create + Read + Cancel. For “image” and “workflow run” the model is appropriate (immutable/audit trail). No missing primitive for variables.

**Score: 4/5 (80%)** — Variables are complete; image/runs are intentionally create+read-oriented.

---

### UI integration — “Agent actions immediately reflected in UI”

- **GitHub Actions UI:** Triggering a workflow, setting repo vars, or pushing changes to workflow YAML is reflected in the Actions tab and repo settings. No “agent does something and UI doesn’t update.”
- **Local edits:** Editing `vars_contract.py`, `constants.py`, or workflow YAML is on disk; “UI” for that is the editor and the next run. No silent divergence.

**Score: 5/5 (100%).**

---

### Capability discovery — “Users can discover what the agent can do”

| Mechanism | Exists? | Location |
|-----------|---------|----------|
| Justfile recipes | Yes | `just` (image build, terraform, deploy, validate) |
| Allowed vars list | Yes | actionlint.yaml (for lint); vars_contract.py (for semantics) |
| Docs for vars and flow | Yes | CLAUDE.md, infra/README.md, docs/configuration.md, .github/bmt/config/README.md |
| Single “handoff env vs constants” map | Partial | constants.py + workflow comments; not summarized in one place for agents |

An agent can discover “what can I do?” via `just`, grep for `vars.`, and docs. Discovery is good but could be improved by one short section in CLAUDE.md: “Workflow env: these keys come from vars; these come from constants/code.”

**Score: 4/5 (80%).**

---

### Prompt-native features — “Features are prompts defining outcomes, not code”

This repo is infrastructure/CI: “features” are workflows and scripts. Behavior is defined in YAML and code, not in natural-language prompts. So prompt-native doesn’t apply in the same way as for a user-facing agent app. The closest analogue is: “Can we change behavior by editing docs/descriptions instead of code?” — only partially (e.g. workflow inputs and descriptions are in YAML; constants are in code). No change needed for this audit focus.

**Score: N/A** for this subsystem.

---

## 3. Summary Table

| Principle | Score | Status |
|-----------|-------|--------|
| Action parity | 5/6 (83%) | ✅ |
| Tools as primitives | 5/5 (100%) | ✅ |
| Context injection | 3/5 (60%) | ⚠️ |
| Shared workspace | 5/5 (100%) | ✅ |
| CRUD completeness | 4/5 (80%) | ✅ |
| UI integration | 5/5 (100%) | ✅ |
| Capability discovery | 4/5 (80%) | ✅ |
| Prompt-native features | N/A | — |

**Overall (for image build, variables, workflow): ~87%** (excluding N/A).

---

## 4. Top Recommendations

| Priority | Action | Principle | Effort |
|----------|--------|-----------|--------|
| 1 | Add to CLAUDE.md a short subsection **“Workflow env and constants”**: list env keys set from `vars.*` in bmt-handoff and bmt-vm-image-build; state that BMT_STATUS_CONTEXT and BMT_PUBSUB_TOPIC come from `gcp/image/config/constants.py` (and where they’re used). | Context injection, Capability discovery | Low |
| 2 | Optionally add BMT_EXPECTED_IMAGE_FAMILY, BMT_EXPECTED_BASE_IMAGE_FAMILY, BMT_EXPECTED_BASE_IMAGE_PROJECT to vars_contract as optional (with defaults) so `just validate` / terraform know about them, or document in infra/README that image-build optional vars are set manually and listed in actionlint. | Action parity, Capability discovery | Low |
| 3 | In docs/configuration.md (or infra/README), add a one-sentence note that “check-image-up-to-date” gates handoff on image build when infra/packer or gcp/image change, and that image build uses the same repo vars (GCP_*, GCS_BUCKET) as handoff. | Context injection | Low |

---

## 5. What’s Working Well

1. **Single source of truth:** Terraform for infra-backed vars; constants.py for product constants; bmt_config for schema and defaults. Parity tests prevent drift (e.g. topic name in main.tf vs constants).
2. **Clear variable flow:** Terraform outputs → terraform_repo_vars → GitHub vars → workflow env → get_config(). Agent can follow the chain in code and docs.
3. **Image build decoupled from handoff env:** Handoff doesn’t need image family or build ID in its env; it only checks “image build ran” when relevant paths change. Keeps workflow env minimal.
4. **Action parity:** Agent can trigger image build, set/check vars, run handoff, and edit constants+TF with the same commands and edits a human would use.
5. **Shared workspace:** One repo, one set of vars, one workflow definition; no agent-specific copy of variables or workflows.

---

*Audit date: 2025-03-12. Scope: image build, variables design/flow, and their relation to workflow code.*
