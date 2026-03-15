"""GitHub Actions repo vars contract and behavioral defaults.

Minimum user config (declarative):
- **bmt.tfvars.json** must set four required variables (no Terraform default):
  gcp_project, gcp_zone, gcs_bucket, service_account.
- **Optional** in tfvars: bmt_vm_name (default bmt-gate-blue). Terraform exports
  gcs_bucket, gcp_project, bmt_vm_name, service_account to GitHub as
  GCS_BUCKET, GCP_PROJECT, BMT_LIVE_VM, GCP_SA_EMAIL. Zone is not exported;
  at runtime zone is fixed in code (not overridable via env).

Manual in GitHub: GCP_WIF_PROVIDER, BMT_DISPATCH_APP_ID (and BMT_DISPATCH_APP_PRIVATE_KEY
when this repo mints the dispatch token). Subscription, topic, repo root, VM pool
are derived in code from BMT_LIVE_VM and constants.
"""

from __future__ import annotations

from dataclasses import dataclass

# Defaults for repo-vars check/apply (behavioral vars that remain in contract).
# Repo root, subscription, topic, pool are in declarative config / derived in code; not repo vars.


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
# YAGNI: only vars users or deployments need to set. Subscription, topic, repo_root, pool
# are derived in code from BMT_LIVE_VM and constants (see bmt_config, vm.py).
TERRAFORM_OUTPUT_TO_VAR: dict[str, str] = {
    "gcs_bucket": "GCS_BUCKET",
    "gcp_project": "GCP_PROJECT",
    "bmt_vm_name": "BMT_LIVE_VM",
    "service_account": "GCP_SA_EMAIL",
}

REPO_VARS_CONTRACT = RepoVarsContract(
    required=(
        "GCS_BUCKET",
        "GCP_PROJECT",
        "BMT_LIVE_VM",
        "GCP_SA_EMAIL",
    ),
    optional=(),
    secrets_not_in_terraform=(
        "GCP_WIF_PROVIDER",
        "BMT_DISPATCH_APP_ID",
    ),
    defaults=(),
)
