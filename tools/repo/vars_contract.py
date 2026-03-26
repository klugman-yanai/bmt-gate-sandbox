"""GitHub Actions repo vars contract for the direct-Workflow Cloud Run pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from backend.config.constants import (
    ENV_BMT_CONTROL_JOB,
    ENV_BMT_STATUS_CONTEXT,
    ENV_BMT_TASK_HEAVY_JOB,
    ENV_BMT_TASK_STANDARD_JOB,
    ENV_CLOUD_RUN_REGION,
    ENV_GCP_PROJECT,
    ENV_GCP_SA_EMAIL,
    ENV_GCP_WIF_PROVIDER,
    ENV_GCP_ZONE,
    ENV_GCS_BUCKET,
    PULUMI_KEY_CLOUD_RUN_JOB_CONTROL,
    PULUMI_KEY_CLOUD_RUN_JOB_HEAVY,
    PULUMI_KEY_CLOUD_RUN_JOB_STANDARD,
    PULUMI_KEY_CLOUD_RUN_REGION,
    PULUMI_KEY_GCP_PROJECT,
    PULUMI_KEY_GCP_WIF_PROVIDER,
    PULUMI_KEY_GCP_ZONE,
    PULUMI_KEY_GCS_BUCKET,
    PULUMI_KEY_SERVICE_ACCOUNT,
)


@dataclass(frozen=True)
class RepoVarsContract:
    """Contract for GitHub repo variables: required, optional, manual, defaults."""

    required: tuple[str, ...]
    optional: tuple[str, ...]
    manual_vars: tuple[str, ...]  # set directly via gh variable set, not exported by Pulumi
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


# Pulumi output name -> GitHub repo var name. Cloud Run job names are consumed by local
# dev tools; the GCP Workflow YAML resolves job names directly from infra.
INFRA_OUTPUT_TO_VAR: dict[str, str] = {
    PULUMI_KEY_GCS_BUCKET: ENV_GCS_BUCKET,
    PULUMI_KEY_GCP_PROJECT: ENV_GCP_PROJECT,
    PULUMI_KEY_GCP_ZONE: ENV_GCP_ZONE,
    PULUMI_KEY_CLOUD_RUN_REGION: ENV_CLOUD_RUN_REGION,
    PULUMI_KEY_CLOUD_RUN_JOB_CONTROL: ENV_BMT_CONTROL_JOB,
    PULUMI_KEY_CLOUD_RUN_JOB_STANDARD: ENV_BMT_TASK_STANDARD_JOB,
    PULUMI_KEY_CLOUD_RUN_JOB_HEAVY: ENV_BMT_TASK_HEAVY_JOB,
    PULUMI_KEY_SERVICE_ACCOUNT: ENV_GCP_SA_EMAIL,
    PULUMI_KEY_GCP_WIF_PROVIDER: ENV_GCP_WIF_PROVIDER,
}

REPO_VARS_CONTRACT = RepoVarsContract(
    required=(
        ENV_GCS_BUCKET,
        ENV_GCP_PROJECT,
        ENV_GCP_ZONE,
        ENV_CLOUD_RUN_REGION,
        ENV_BMT_CONTROL_JOB,
        ENV_BMT_TASK_STANDARD_JOB,
        ENV_BMT_TASK_HEAVY_JOB,
        ENV_GCP_SA_EMAIL,
        ENV_GCP_WIF_PROVIDER,  # Required for handoff (OIDC); set gcp_wif_provider in bmt.config.json, synced by Pulumi.
    ),
    optional=(),
    manual_vars=(ENV_BMT_STATUS_CONTEXT,),
    defaults=(),
)
