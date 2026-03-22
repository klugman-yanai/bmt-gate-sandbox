"""Load infrastructure config from bmt.tfvars.json with defaults matching variables.tf."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILENAME = "bmt.tfvars.json"
EXAMPLE_FILENAME = "bmt.tfvars.example.json"
REQUIRED_KEYS = ("gcp_project", "gcp_zone", "gcs_bucket", "service_account", "gcp_wif_provider")


@dataclass(frozen=True)
class InfraConfig:
    # Required
    gcp_project: str
    gcp_zone: str
    gcs_bucket: str
    service_account: str
    # Optional with defaults (match variables.tf)
    image_family: str = "bmt-runtime"
    image_name: str = ""
    machine_type: str = "n2-standard-8"
    scopes: tuple[str, ...] = ("https://www.googleapis.com/auth/cloud-platform",)
    network: str = "default"
    subnetwork: str = ""
    tags: tuple[str, ...] = ()
    disk_size_gb: int = 100
    disk_type: str = "pd-ssd"
    # Cloud Run
    cloud_run_region: str = "europe-west4"  # Must match gcp.image.config.constants.DEFAULT_CLOUD_RUN_REGION
    cloud_run_memory_standard: str = "8Gi"
    cloud_run_cpu_standard: str = "4"
    cloud_run_memory_heavy: str = "16Gi"
    cloud_run_cpu_heavy: str = "8"
    cloud_run_task_timeout_sec: int = 3600
    cloud_run_workflow_connector_timeout_sec: int = 3900
    cloud_run_job_sa_name: str = "bmt-job-runner"
    cloud_run_workflow_sa_name: str = "bmt-workflow-sa"
    artifact_registry_repo: str = "bmt-images"
    github_repo_owner: str = ""
    github_repo_name: str = ""
    # Workload Identity Federation provider (e.g. for GitHub Actions OIDC). Required; synced to GCP_WIF_PROVIDER.
    gcp_wif_provider: str = ""

    def __post_init__(self) -> None:
        if not self.cloud_run_job_sa_name.strip():
            raise ValueError("cloud_run_job_sa_name must be non-empty")
        if not self.cloud_run_workflow_sa_name.strip():
            raise ValueError("cloud_run_workflow_sa_name must be non-empty")
        if self.cloud_run_workflow_connector_timeout_sec < self.cloud_run_task_timeout_sec:
            raise ValueError(
                "cloud_run_workflow_connector_timeout_sec must be greater than or equal to cloud_run_task_timeout_sec"
            )

    @property
    def cloud_run_image_uri(self) -> str:
        """Derive image URI from Artifact Registry config."""
        return (
            f"{self.cloud_run_region}-docker.pkg.dev/{self.gcp_project}/{self.artifact_registry_repo}/bmt-orchestrator"
        )


def load_config(config_dir: Path | None = None) -> InfraConfig:
    """Load config from bmt.tfvars.json in the given directory (default: this file's directory)."""
    if config_dir is None:
        config_dir = Path(__file__).parent
    config_path = config_dir / CONFIG_FILENAME
    example_path = config_dir / EXAMPLE_FILENAME
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Config not found: {config_path}. "
            f"Copy {example_path.name} to {CONFIG_FILENAME} and set {', '.join(REQUIRED_KEYS)}."
        )
    with config_path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise TypeError(f"{CONFIG_FILENAME} must be a JSON object")
    for key in REQUIRED_KEYS:
        if key not in data or data[key] is None or str(data[key]).strip() == "":
            raise ValueError(f"{CONFIG_FILENAME} must set non-empty '{key}'")
    if "scopes" in data and isinstance(data["scopes"], list):
        data["scopes"] = tuple(data["scopes"])
    if "tags" in data and isinstance(data["tags"], list):
        data["tags"] = tuple(data["tags"])
    known = {f.name for f in InfraConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in known}
    return InfraConfig(**filtered)
