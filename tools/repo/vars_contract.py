"""GitHub Actions repo vars contract and behavioral defaults.

Source of truth for which vars exist, required vs optional, secrets, and default
values for behavioral vars. Infra-derived values come from Terraform outputs;
behavioral defaults come from gcp.image.config.bmt_config.BmtConfig (single source of truth).

Repo vars are only for values that vary per repo or must be set by the user (e.g. bucket,
project, VM name, status context for branch protection, WIF, GitHub App ID). Constants
that users should not override (e.g. handshake timeout, repo root path) are not repo vars;
code uses BmtConfig defaults. Optional vars (e.g. BMT_REPO_ROOT) have defaults so
repo-vars-check does not require them. Secrets like BMT_DISPATCH_APP_PRIVATE_KEY are not
in the contract when the key is stored in the bucket and CI does not need a repo-level secret.
"""

from __future__ import annotations

from dataclasses import dataclass

from gcp.image.config.constants import DEFAULT_REPO_ROOT

# Defaults for repo-vars check/apply (behavioral vars that remain in contract).


@dataclass(frozen=True)
class RepoVarsContract:
    """Contract for GitHub repo variables: required, optional, secrets, defaults."""

    required: tuple[str, ...]
    optional: tuple[str, ...]
    secrets_not_in_terraform: tuple[str, ...]
    defaults: tuple[tuple[str, str], ...]  # (name, value) for behavioral vars

    def all_var_names(self) -> list[str]:
        """Required then optional, no duplicates."""
        seen: set[str] = set()
        out: list[str] = []
        for name in (*self.required, *self.optional):
            if name not in seen:
                seen.add(name)
                out.append(name)
        return out

    def default_dict(self) -> dict[str, str]:
        return dict(self.defaults)


# Terraform output name (outputs.tf) -> GitHub Actions variable name.
# Only infra-derived vars; behavioral vars use DEFAULTS below.
TERRAFORM_OUTPUT_TO_VAR: dict[str, str] = {
    "gcs_bucket": "GCS_BUCKET",
    "gcp_project": "GCP_PROJECT",
    "gcp_zone": "GCP_ZONE",
    "bmt_vm_name": "BMT_LIVE_VM",
    "bmt_repo_root": "BMT_REPO_ROOT",
    "service_account": "GCP_SA_EMAIL",
}

REPO_VARS_CONTRACT = RepoVarsContract(
    required=(
        "GCS_BUCKET",
        "GCP_PROJECT",
        "GCP_ZONE",
        "BMT_LIVE_VM",
        "GCP_SA_EMAIL",
    ),
    optional=("BMT_REPO_ROOT",),
    secrets_not_in_terraform=(
        "GCP_WIF_PROVIDER",
        "BMT_DISPATCH_APP_ID",
    ),
    defaults=(("BMT_REPO_ROOT", DEFAULT_REPO_ROOT),),
)
