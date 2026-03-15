"""Load infrastructure config from bmt.tfvars.json with defaults matching variables.tf."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILENAME = "bmt.tfvars.json"
EXAMPLE_FILENAME = "bmt.tfvars.example.json"
REQUIRED_KEYS = ("gcp_project", "gcp_zone", "gcs_bucket", "service_account")


@dataclass(frozen=True)
class InfraConfig:
    # Required
    gcp_project: str
    gcp_zone: str
    gcs_bucket: str
    service_account: str
    # Optional with defaults (match variables.tf)
    bmt_vm_name: str = "bmt-gate-blue"
    image_family: str = "bmt-runtime"
    image_name: str = ""
    machine_type: str = "n2-standard-8"
    scopes: tuple[str, ...] = ("https://www.googleapis.com/auth/cloud-platform",)
    network: str = "default"
    subnetwork: str = ""
    tags: tuple[str, ...] = ()
    disk_size_gb: int = 100
    disk_type: str = "pd-ssd"
    bmt_repo_root: str = "/opt/bmt"
    startup_wrapper_script_path: str = "../../.github/bmt/ci/resources/startup_entrypoint.sh"

    @property
    def bmt_vm_base(self) -> str:
        return self.bmt_vm_name.replace("-green", "").replace("-blue", "").strip()

    @property
    def is_blue_green(self) -> bool:
        return self.bmt_vm_name.endswith("-blue") or self.bmt_vm_name.endswith("-green")

    @property
    def bmt_vm_pool(self) -> str:
        if not self.is_blue_green:
            return ""
        return f"{self.bmt_vm_base}-blue,{self.bmt_vm_base}-green"


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
    # Convert list fields to tuples for frozen dataclass
    if "scopes" in data and isinstance(data["scopes"], list):
        data["scopes"] = tuple(data["scopes"])
    if "tags" in data and isinstance(data["tags"], list):
        data["tags"] = tuple(data["tags"])
    # Filter to only known fields
    known = {f.name for f in InfraConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in known}
    return InfraConfig(**filtered)
