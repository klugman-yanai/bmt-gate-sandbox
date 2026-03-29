"""Errors raised while resolving or loading BMT plugins."""

from __future__ import annotations


class ManifestValidationError(RuntimeError):
    pass


class PluginLoadError(RuntimeError):
    pass


class WorkspacePluginRefError(RuntimeError):
    pass
