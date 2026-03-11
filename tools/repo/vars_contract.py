"""GitHub Actions repo vars contract and behavioral defaults.

Source of truth for which vars exist, required vs optional, secrets, and default
values for behavioral vars. Infra-derived values come from Terraform outputs;
behavioral defaults come from gcp/code/lib/bmt_config.BmtConfig (single source of truth).
"""

from __future__ import annotations

from dataclasses import dataclass

from gcp.code.config.bmt_config import BmtConfig

# Defaults for repo-vars check/apply: from BmtConfig model (single source of truth).
_BMT_DEFAULTS = BmtConfig()


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
    "bmt_vm_name": "BMT_VM_NAME",
    "bmt_repo_root": "BMT_REPO_ROOT",
    "service_account": "GCP_SA_EMAIL",
    "pubsub_subscription": "BMT_PUBSUB_SUBSCRIPTION",
    "pubsub_topic": "BMT_PUBSUB_TOPIC",
}

REPO_VARS_CONTRACT = RepoVarsContract(
    required=(
        "GCS_BUCKET",
        "GCP_PROJECT",
        "GCP_ZONE",
        "BMT_VM_NAME",
        "BMT_REPO_ROOT",
        "GCP_SA_EMAIL",
        "BMT_PUBSUB_SUBSCRIPTION",
        "BMT_STATUS_CONTEXT",
        "BMT_HANDSHAKE_TIMEOUT_SEC",
    ),
    optional=(
        "BMT_PUBSUB_TOPIC",
    ),
    secrets_not_in_terraform=(
        "GCP_WIF_PROVIDER",
        "BMT_DISPATCH_APP_ID",
        "BMT_DISPATCH_APP_PRIVATE_KEY",
    ),
    defaults=(
        ("BMT_STATUS_CONTEXT", _BMT_DEFAULTS.bmt_status_context),
        ("BMT_HANDSHAKE_TIMEOUT_SEC", str(_BMT_DEFAULTS.bmt_handshake_timeout_sec)),
    ),
)
