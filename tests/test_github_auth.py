"""
Unit tests for GitHub App authentication module.
"""

import json
import os

# Import the module under test
# Note: We need to add remote/code/lib to the path
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "remote" / "code" / "lib"))
import github_auth  # type: ignore[import-not-found]  # noqa: E402


@pytest.fixture
def test_config():
    """Create a temporary test configuration file."""
    config_data = {
        "version": "1.0",
        "repositories": {
            "test-org/test-repo": {
                "repo_env": "test",
                "description": "Test repository",
                "secret_prefix": "GITHUB_APP_TEST",
                "enabled": True,
            },
            "prod-org/prod-repo": {
                "repo_env": "prod",
                "description": "Production repository",
                "secret_prefix": "GITHUB_APP_PROD",
                "enabled": True,
            },
            "disabled-org/disabled-repo": {
                "repo_env": "disabled",
                "description": "Disabled repository",
                "secret_prefix": "GITHUB_APP_DISABLED",
                "enabled": False,
            },
        },
        "fallback": {
            "use_pat": True,
            "pat_env_var": "GITHUB_STATUS_TOKEN",
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_data, f)
        config_path = f.name

    yield config_path

    # Cleanup
    Path(config_path).unlink(missing_ok=True)


class TestLoadGithubReposConfig:
    """Tests for load_github_repos_config()."""

    def test_load_valid_config(self, test_config):
        """Test loading a valid configuration file."""
        config = github_auth.load_github_repos_config(test_config)
        assert config is not None
        assert "repositories" in config
        assert "test-org/test-repo" in config["repositories"]

    def test_load_nonexistent_config(self):
        """Test loading a non-existent configuration file."""
        config = github_auth.load_github_repos_config("/nonexistent/path.json")
        assert config is None

    def test_load_invalid_json(self):
        """Test loading an invalid JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {")
            invalid_path = f.name

        try:
            config = github_auth.load_github_repos_config(invalid_path)
            assert config is None
        finally:
            Path(invalid_path).unlink(missing_ok=True)

    def test_load_missing_repositories_key(self):
        """Test loading a config without 'repositories' key."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"version": "1.0"}, f)
            invalid_path = f.name

        try:
            config = github_auth.load_github_repos_config(invalid_path)
            assert config is None
        finally:
            Path(invalid_path).unlink(missing_ok=True)


class TestResolveAuthForRepository:
    """Tests for resolve_auth_for_repository()."""

    def test_no_config_falls_back_to_pat(self):
        """Test that missing config falls back to PAT."""
        with mock.patch.dict(os.environ, {"GITHUB_STATUS_TOKEN": "test-pat-token"}):
            token = github_auth.resolve_auth_for_repository(
                "any-repo/any-name",
                config_path="/nonexistent/path.json",
            )
            assert token == "test-pat-token"

    def test_unknown_repository_falls_back_to_pat(self, test_config):
        """Test that unknown repository falls back to PAT."""
        with mock.patch.dict(os.environ, {"GITHUB_STATUS_TOKEN": "test-pat-token"}):
            token = github_auth.resolve_auth_for_repository(
                "unknown-org/unknown-repo",
                config_path=test_config,
            )
            assert token == "test-pat-token"

    def test_disabled_repository_returns_none(self, test_config):
        """Test that disabled repository returns None."""
        with mock.patch.dict(os.environ, {"GITHUB_STATUS_TOKEN": "test-pat-token"}):
            token = github_auth.resolve_auth_for_repository(
                "disabled-org/disabled-repo",
                config_path=test_config,
            )
            assert token is None

    def test_missing_app_secrets_falls_back_to_pat(self, test_config):
        """Test that missing App secrets falls back to PAT."""
        with mock.patch.dict(os.environ, {"GITHUB_STATUS_TOKEN": "test-pat-token"}, clear=True):
            token = github_auth.resolve_auth_for_repository(
                "test-org/test-repo",
                config_path=test_config,
            )
            assert token == "test-pat-token"

    def test_partial_app_secrets_falls_back_to_pat(self, test_config):
        """Test that partial App secrets (missing one) falls back to PAT."""
        with mock.patch.dict(
            os.environ,
            {
                "GITHUB_APP_TEST_ID": "12345",
                "GITHUB_APP_TEST_INSTALLATION_ID": "67890",
                # Missing GITHUB_APP_TEST_PRIVATE_KEY
                "GITHUB_STATUS_TOKEN": "test-pat-token",
            },
            clear=True,
        ):
            token = github_auth.resolve_auth_for_repository(
                "test-org/test-repo",
                config_path=test_config,
            )
            assert token == "test-pat-token"

    def test_no_pat_available_returns_none(self, test_config):
        """Test that missing PAT returns None when App auth unavailable."""
        with mock.patch.dict(os.environ, {}, clear=True):
            token = github_auth.resolve_auth_for_repository(
                "test-org/test-repo",
                config_path=test_config,
            )
            assert token is None

    def test_empty_repository_returns_none(self, test_config):
        """Test that empty repository string returns None."""
        token = github_auth.resolve_auth_for_repository(
            "",
            config_path=test_config,
        )
        assert token is None

    @mock.patch("github_auth.get_installation_token_from_app")
    def test_successful_app_auth(self, mock_get_token, test_config):
        """Test successful GitHub App authentication."""
        mock_get_token.return_value = "test-app-token"

        with mock.patch.dict(
            os.environ,
            {
                "GITHUB_APP_TEST_ID": "12345",
                "GITHUB_APP_TEST_INSTALLATION_ID": "67890",
                "GITHUB_APP_TEST_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
            },
            clear=True,
        ):
            token = github_auth.resolve_auth_for_repository(
                "test-org/test-repo",
                config_path=test_config,
            )
            assert token == "test-app-token"
            mock_get_token.assert_called_once()

    @mock.patch("github_auth.get_installation_token_from_app")
    def test_app_auth_failure_falls_back_to_pat(self, mock_get_token, test_config):
        """Test that App auth failure falls back to PAT."""
        mock_get_token.return_value = None  # Simulate failure

        with mock.patch.dict(
            os.environ,
            {
                "GITHUB_APP_TEST_ID": "12345",
                "GITHUB_APP_TEST_INSTALLATION_ID": "67890",
                "GITHUB_APP_TEST_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
                "GITHUB_STATUS_TOKEN": "test-pat-token",
            },
            clear=True,
        ):
            token = github_auth.resolve_auth_for_repository(
                "test-org/test-repo",
                config_path=test_config,
            )
            assert token == "test-pat-token"


class TestResolveConfigPath:
    """Tests for _resolve_config_path()."""

    def test_explicit_path_wins(self, test_config):
        resolved = github_auth._resolve_config_path(test_config)
        assert resolved == Path(test_config)

    def test_env_override_wins(self, test_config):
        with mock.patch.dict(os.environ, {"BMT_GITHUB_REPOS_CONFIG": test_config}, clear=True):
            resolved = github_auth._resolve_config_path(None)
        assert resolved == Path(test_config)

    def test_default_path_exists(self):
        resolved = github_auth._resolve_config_path(None)
        assert resolved.name == "github_repos.json"


class TestGetInstallationTokenFromApp:
    """Tests for get_installation_token_from_app()."""

    def test_missing_pyjwt_returns_none(self):
        """Test that missing PyJWT library returns None."""
        with mock.patch("github_auth.HAS_JWT", False):
            token = github_auth.get_installation_token_from_app(
                "12345",
                "67890",
                "test-key",
            )
            assert token is None

    def test_missing_credentials_returns_none(self):
        """Test that missing credentials returns None."""
        assert github_auth.get_installation_token_from_app("", "67890", "key") is None
        assert github_auth.get_installation_token_from_app("12345", "", "key") is None
        assert github_auth.get_installation_token_from_app("12345", "67890", "") is None

    @mock.patch("github_auth.HAS_JWT", True)
    @mock.patch("github_auth.jwt")
    @mock.patch("github_auth.urllib.request.urlopen")
    def test_successful_token_exchange(self, mock_urlopen, mock_jwt):
        """Test successful JWT generation and token exchange."""
        # Mock JWT encoding
        mock_jwt.encode.return_value = "mock-jwt-token"

        # Mock API response
        mock_response = mock.MagicMock()
        mock_response.status = 201
        mock_response.read.return_value = json.dumps({"token": "test-installation-token"}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        token = github_auth.get_installation_token_from_app(
            "12345",
            "67890",
            "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        )

        assert token == "test-installation-token"
        mock_jwt.encode.assert_called_once()

    @mock.patch("github_auth.HAS_JWT", True)
    @mock.patch("github_auth.jwt")
    @mock.patch("github_auth.urllib.request.urlopen")
    def test_api_error_returns_none(self, mock_urlopen, mock_jwt):
        """Test that API errors return None."""
        mock_jwt.encode.return_value = "mock-jwt-token"

        # Simulate HTTP error
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            "https://api.github.com",
            401,
            "Unauthorized",
            None,  # type: ignore[arg-type]
            None,
        )

        token = github_auth.get_installation_token_from_app(
            "12345",
            "67890",
            "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        )

        assert token is None


class TestFallbackToPat:
    """Tests for _fallback_to_pat()."""

    def test_pat_available(self):
        """Test PAT fallback when token is available."""
        with mock.patch.dict(os.environ, {"GITHUB_STATUS_TOKEN": "test-pat"}):
            token = github_auth._fallback_to_pat(None)
            assert token == "test-pat"

    def test_pat_unavailable(self):
        """Test PAT fallback when token is not available."""
        with mock.patch.dict(os.environ, {}, clear=True):
            token = github_auth._fallback_to_pat(None)
            assert token is None

    def test_custom_pat_env_var(self):
        """Test PAT fallback with custom environment variable name."""
        config = {
            "fallback": {
                "use_pat": True,
                "pat_env_var": "CUSTOM_TOKEN",
            }
        }
        with mock.patch.dict(os.environ, {"CUSTOM_TOKEN": "custom-pat"}):
            token = github_auth._fallback_to_pat(config)
            assert token == "custom-pat"

    def test_pat_disabled_in_config(self):
        """Test PAT fallback when disabled in config."""
        config = {
            "fallback": {
                "use_pat": False,
            }
        }
        with mock.patch.dict(os.environ, {"GITHUB_STATUS_TOKEN": "test-pat"}):
            token = github_auth._fallback_to_pat(config)
            assert token is None
