"""
GitHub App authentication module for multi-repository support.

Provides minimal GitHub App authentication:
- Generates JWT from App credentials
- Exchanges JWT for installation token
- Resolves repository-specific auth from declarative config
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Optional PyJWT import (graceful degradation if not installed)
try:
    import jwt

    HAS_JWT = True
except ImportError:
    HAS_JWT = False

_ALIAS_WARNING_EMITTED: set[tuple[str, str]] = set()


def _resolve_env_value(
    *,
    canonical_prefix: str,
    suffix: str,
    repository: str,
    repo_env: str,
) -> tuple[str, str]:
    """Resolve canonical env var first, then GH_APP alias fallback."""
    canonical_name = f"{canonical_prefix}_{suffix}"
    value = os.environ.get(canonical_name, "").strip()
    if value:
        return value, canonical_name

    if canonical_prefix.startswith("GITHUB_APP_"):
        alias_prefix = f"GH_APP_{canonical_prefix[len('GITHUB_APP_'):]}"
        alias_name = f"{alias_prefix}_{suffix}"
        alias_value = os.environ.get(alias_name, "").strip()
        if alias_value:
            warning_key = (repository, canonical_prefix)
            if warning_key not in _ALIAS_WARNING_EMITTED:
                print(
                    "  Warning: Using alias GitHub App env prefix "
                    f"'{alias_prefix}_*' for '{repository}' (env: {repo_env}); "
                    f"prefer canonical '{canonical_prefix}_*'."
                )
                _ALIAS_WARNING_EMITTED.add(warning_key)
            return alias_value, alias_name

    return "", canonical_name


def get_installation_token_from_app(  # noqa: PLR0911
    app_id: str,
    installation_id: str,
    private_key: str,
) -> str | None:
    """
    Generate installation token from GitHub App credentials.

    Args:
        app_id: GitHub App ID
        installation_id: GitHub App Installation ID
        private_key: GitHub App private key (PEM format)

    Returns:
        Installation token string, or None on failure
    """
    if not HAS_JWT:
        print("  Warning: PyJWT not available; cannot use GitHub App auth")
        return None

    if not app_id or not installation_id or not private_key:
        print("  Warning: Missing GitHub App credentials")
        return None

    try:
        # Generate JWT (valid for 10 minutes)
        now = int(time.time())
        payload = {
            "iat": now - 60,  # Issued 60s ago (clock skew tolerance)
            "exp": now + (10 * 60),  # Expires in 10 minutes
            "iss": app_id,
        }
        jwt_token = jwt.encode(payload, private_key, algorithm="RS256")  # type: ignore[possibly-unbound]

        # Exchange JWT for installation token
        url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        req = urllib.request.Request(
            url,
            data=b"",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {jwt_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 201:
                print(f"  Warning: GitHub App token endpoint returned status {resp.status}")
                return None
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("token")

    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        print(f"  Warning: Failed to exchange JWT for installation token: {exc}")
        return None
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"  Warning: Invalid response from GitHub App token endpoint: {exc}")
        return None
    except Exception as exc:  # Catch PyJWT errors and any other unexpected errors
        print(f"  Warning: Failed to generate installation token: {exc}")
        return None


def load_github_repos_config(config_path: str | Path) -> dict[str, Any] | None:
    """
    Load repository configuration from github_repos.json.

    Args:
        config_path: Path to github_repos.json

    Returns:
        Parsed config dict, or None on failure
    """
    try:
        config_file = Path(config_path)
        if not config_file.is_file():
            print(f"  Warning: Repository config not found at {config_path}")
            return None

        with config_file.open(encoding="utf-8") as f:
            config = json.load(f)

        # Basic validation
        if not isinstance(config, dict):
            print(f"  Warning: Invalid config format in {config_path}")
            return None

        if "repositories" not in config or not isinstance(config["repositories"], dict):
            print(f"  Warning: Missing or invalid 'repositories' key in {config_path}")
            return None

        return config

    except (OSError, json.JSONDecodeError) as exc:
        print(f"  Warning: Failed to load repository config from {config_path}: {exc}")
        return None


def _resolve_config_path(config_path: str | Path | None) -> Path:
    """Resolve repository-config path with layout-aware defaults."""
    if config_path is not None and str(config_path).strip():
        return Path(config_path)

    env_override = os.environ.get("BMT_GITHUB_REPOS_CONFIG", "").strip()
    if env_override:
        return Path(env_override)

    # Preferred path in current layout: <repo_root>/config/github_repos.json
    preferred = Path(__file__).resolve().parents[1] / "config" / "github_repos.json"
    if preferred.is_file():
        return preferred

    # VM fallbacks: /opt/bmt must match config/env_contract.json defaults.BMT_REPO_ROOT.
    repo_root = os.environ.get("BMT_REPO_ROOT", "").strip() or "/opt/bmt"
    legacy = Path(repo_root) / "remote" / "config" / "github_repos.json"
    if legacy.is_file():
        return legacy

    return Path(repo_root) / "config" / "github_repos.json"


def list_enabled_repositories(config_path: str | Path | None = None) -> list[str] | None:
    """
    List repositories that are enabled in github_repos.json.

    Args:
        config_path: Optional path override for github_repos.json. If unset, uses
            BMT_GITHUB_REPOS_CONFIG env override, then layout-aware defaults.

    Returns:
        List of enabled repository names, or None if config cannot be loaded.
    """
    resolved_config_path = _resolve_config_path(config_path)
    config = load_github_repos_config(resolved_config_path)
    if not config:
        print(f"  Error: repository config is required but could not be loaded ({resolved_config_path})")
        return None

    repositories = config.get("repositories", {})
    if not isinstance(repositories, dict):
        print(f"  Error: invalid repository config shape in {resolved_config_path}")
        return None

    enabled: list[str] = []
    for repo_name, repo_config in repositories.items():
        if not isinstance(repo_config, dict):
            continue
        if repo_config.get("enabled", True):
            enabled.append(str(repo_name))
    return enabled


def resolve_auth_for_repository(  # noqa: PLR0911
    repository: str,
    config_path: str | Path | None = None,
) -> str | None:
    """
    Resolve GitHub authentication token for a repository.

    Primary entry point for VM watcher. Uses GitHub App auth only.

    Args:
        repository: Repository in "owner/repo" format
        config_path: Optional path override for github_repos.json. If unset, uses
            BMT_GITHUB_REPOS_CONFIG env override, then layout-aware defaults.

    Returns:
        GitHub token string, or None if no auth available
    """
    if not repository:
        print("  Warning: No repository provided for auth resolution")
        return None

    # Load repository configuration
    resolved_config_path = _resolve_config_path(config_path)
    config = load_github_repos_config(resolved_config_path)
    if not config:
        print(f"  Error: Repository config is required and could not be loaded ({resolved_config_path})")
        return None

    # Look up repository in config
    repositories = config.get("repositories", {})
    repo_config = repositories.get(repository)

    if not repo_config:
        print(f"  Error: Repository '{repository}' not found in config; cannot resolve GitHub App auth")
        return None

    # Check if repository is enabled
    if not repo_config.get("enabled", True):
        print(f"  Warning: Repository '{repository}' is disabled in config")
        return None

    # Try GitHub App authentication
    secret_prefix = repo_config.get("secret_prefix", "")
    repo_env = repo_config.get("repo_env", "unknown")

    if not secret_prefix:
        print(f"  Error: No secret_prefix for '{repository}' (env: {repo_env}); cannot resolve GitHub App auth")
        return None

    # Read App credentials from canonical env vars with GH_APP_* alias fallback.
    app_id, app_id_var = _resolve_env_value(
        canonical_prefix=secret_prefix,
        suffix="ID",
        repository=repository,
        repo_env=repo_env,
    )
    installation_id, installation_id_var = _resolve_env_value(
        canonical_prefix=secret_prefix,
        suffix="INSTALLATION_ID",
        repository=repository,
        repo_env=repo_env,
    )
    private_key, private_key_var = _resolve_env_value(
        canonical_prefix=secret_prefix,
        suffix="PRIVATE_KEY",
        repository=repository,
        repo_env=repo_env,
    )

    if not (app_id and installation_id and private_key):
        checked = f"{app_id_var}/{installation_id_var}/{private_key_var}"
        print(f"  Error: Missing GitHub App credentials for '{repository}' (env: {repo_env}). Checked: {checked}")
        return None

    # Try to get installation token
    token = get_installation_token_from_app(app_id, installation_id, private_key)
    if token:
        print(f"  ✓ Using GitHub App auth for '{repository}' (env: {repo_env}, prefix: {secret_prefix})")
        return token

    print(f"  Error: Failed to generate GitHub App token for '{repository}' (env: {repo_env})")
    return None
