# Defaults consolidation: single source of truth

Many default values are repeated across Python, Terraform, workflow YAML, and shell scripts. This doc maps the redundancies and defines the consolidation strategy.

## Redundancy map

### Repo root: `/opt/bmt`

| Location | How it appears |
|----------|----------------|
| **Source of truth** | `gcp/image/config/constants.py` → `DEFAULT_REPO_ROOT` |
| Terraform | `variables.tf` `bmt_repo_root` default `"/opt/bmt"` (parity test) |
| vars_contract | `BMT_REPO_ROOT` default from `DEFAULT_REPO_ROOT` |
| startup_entrypoint.sh | `BMT_REPO_ROOT_DEFAULT="/opt/bmt"` (literal) |
| .github/bmt/cli/resources/startup_entrypoint.sh | same literal |
| create_bmt_green_vm.py | `meta_items.get("BMT_REPO_ROOT", "/opt/bmt")` |
| run_watcher.py, ssh_install.py, audit_vm_and_bucket.py, set_startup_script_url.py | `os.environ.get("BMT_REPO_ROOT", "") or DEFAULT_BMT_REPO_ROOT` (script-level constant) |
| infra/scripts/build_bmt_image.py (inline) | hardcoded `/opt/bmt` in script body |

**Consolidation:** Constants + Terraform + vars_contract are already aligned via parity tests. Scripts under `gcp/image/` should use `constants.DEFAULT_REPO_ROOT` (or a shared `DEFAULT_BMT_REPO_ROOT` imported from config). Shell entrypoints cannot import Python; keep literal with a comment that it must match `constants.DEFAULT_REPO_ROOT` (or generate from Python at build time if we ever want to remove the literal).

---

### Status context: `BMT Gate`

| Location | How it appears |
|----------|----------------|
| **Source of truth** | `gcp/image/config/constants.py` → `STATUS_CONTEXT` |
| BmtConfig | `bmt_status_context` default `constants.STATUS_CONTEXT` |
| Terraform | `variables.tf` `bmt_status_context` default `"BMT Gate"` (parity test) |
| bmt-failure-fallback action | input default `"BMT Gate"` |
| Tests | various `"BMT Gate"` literals |

**Consolidation:** Code and Terraform already use parity tests. Action input default is a literal; acceptable if documented, or set from workflow step that reads from Python.

---

### Image family / base image

| Value | Locations (all literals) |
|-------|---------------------------|
| **bmt-runtime** | Terraform `image_family` default; workflow `inputs.image_family` default and all `\|\| 'bmt-runtime'`; infra/scripts/build_bmt_image.py (BMT_IMAGE_FAMILY, BMT_EXPECTED_IMAGE_FAMILY); create_bmt_green_vm.py; enforce-image-family-policy.sh; bmt-vm-provision.yml |
| **ubuntu-2204-lts** | Workflow inputs + vars fallbacks; infra/scripts/build_bmt_image.py (BMT_BASE_IMAGE_FAMILY, BMT_EXPECTED_BASE_IMAGE_FAMILY); enforce-image-family-policy.sh |
| **ubuntu-os-cloud** | Same pattern as ubuntu-2204-lts |

**Consolidation:** Add `DEFAULT_IMAGE_FAMILY`, `DEFAULT_BASE_IMAGE_FAMILY`, `DEFAULT_BASE_IMAGE_PROJECT` to `gcp/image/config/constants.py`. Use them in Python scripts (infra/scripts/build_bmt_image.py, create_bmt_green_vm.py). Add parity test for Terraform `image_family` default. Workflow can either (a) run a step that sets env from Python (single source) or (b) keep input/vars fallback literals and add a test that they match constants.

---

### Handshake / idle timeouts

| Value | Locations |
|-------|-----------|
| **420** (handshake) | BmtConfig `bmt_handshake_timeout_sec`; Terraform `bmt_handshake_timeout_sec` (parity test) |
| **600** (handshake reuse / idle) | BmtConfig `bmt_handshake_timeout_sec_reuse_running`; bmt_config `IDLE_TIMEOUT_SEC`; run_watcher.py `BMT_IDLE_TIMEOUT_SEC` default `"600"` |

**Consolidation:** Handshake 420 is already parity-tested. Idle 600: run_watcher.py should use `str(IDLE_TIMEOUT_SEC)` from bmt_config as default instead of literal `"600"` (if the script can import from config; otherwise document and optionally add a test).

---

### Other Terraform-only defaults (no code constant)

These live only in Terraform and are not duplicated in code: `machine_type`, `scopes`, `network`, `subnetwork`, `tags`, `disk_size_gb`, `disk_type`, `bmt_trigger_stale_sec`, `bmt_runtime_context`, `bmt_trigger_metadata_keep_recent`. No change needed unless we later want to drive them from code.

---

## Implementation status

| Item | Status |
|------|--------|
| Repo root: constants + Terraform + parity | Done |
| Status context: constants + Terraform + parity | Done |
| Topic name: constants + main.tf + parity | Done |
| Handshake 420 / 600: BmtConfig + Terraform parity for 420 | Done |
| Image family/base defaults in constants | Done |
| infra/scripts/build_bmt_image.py / create_bmt_green_vm.py use constants | Done |
| Terraform image_family parity test | Done |
| Workflow image defaults from Python or parity test | Optional |
| Shell script literals (startup_entrypoint, enforce-image-family-policy) | Comment-only or generate at build; low priority |

---

## Principles

1. **Code-first for shared product defaults:** Constants used by both Python and Terraform live in `gcp/image/config/constants.py` or `bmt_config.py`. Terraform keeps literals and `tests/infra/test_terraform_bmt_config_parity.py` fails if they diverge.
2. **No new literals:** When adding a default that might be used in more than one place, add it to constants (or BmtConfig) first, then reference it everywhere possible; use parity tests where the consumer cannot import Python (Terraform, YAML, shell).
3. **Workflow:** Prefer a step that runs Python to set env (e.g. image defaults, status context) so the workflow has zero literals for those values; otherwise document and test parity.
