"""Runtime ↔ plugin ``api_version`` compatibility (image-baked contract)."""

from __future__ import annotations

from gcp.image.runtime.plugin_errors import PluginLoadError

# ``api_version`` values from ``plugin.json`` that this Cloud Run image supports.
SUPPORTED_PLUGIN_API_VERSIONS: frozenset[str] = frozenset({"v1"})


def ensure_plugin_api_version_supported(api_version: str) -> None:
    """Raise :class:`PluginLoadError` if the loaded plugin's API is not supported by this image."""
    if api_version not in SUPPORTED_PLUGIN_API_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_PLUGIN_API_VERSIONS))
        raise PluginLoadError(
            f"This runtime supports plugin api_version {{{supported}}}; "
            f"plugin.json declares {api_version!r}. Use a matching image or adjust api_version."
        )
