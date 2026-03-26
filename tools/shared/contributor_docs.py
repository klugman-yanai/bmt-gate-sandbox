"""Resolved paths and stderr copy for contributor setup (venv, dev deps, external CLIs).

Uses `repo_root()` — not environment variables — so documentation pointers match the checkout on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tools.repo.paths import repo_root


@dataclass(frozen=True)
class ContributorDocRefs:
    """Canonical docs under the repository root."""

    root: Path
    contributing: Path
    readme: Path
    docs_index: Path
    configuration: Path
    adding_a_project: Path

    @classmethod
    def discover(cls) -> ContributorDocRefs:
        r = repo_root()
        return cls(
            root=r,
            contributing=r / "CONTRIBUTING.md",
            readme=r / "README.md",
            docs_index=r / "docs" / "README.md",
            configuration=r / "docs" / "configuration.md",
            adding_a_project=r / "docs" / "adding-a-project.md",
        )

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def configuration_rel(self) -> str:
        """Repo-relative path to docs/configuration.md (for stderr one-liners)."""
        return self._rel(self.configuration)

    def adding_a_project_rel(self) -> str:
        """Repo-relative path to docs/adding-a-project.md."""
        return self._rel(self.adding_a_project)

    def setup_reminder_line(self) -> str:
        """One stderr line: onboarding + quick start + docs index (repo-relative paths)."""
        return (
            f"See {self._rel(self.contributing)} for one-time setup (`just onboard`, `uv sync`). "
            f"{self._rel(self.readme)} for quick start; {self._rel(self.docs_index)} for the documentation index."
        )

    def gcloud_missing_line(self) -> str:
        return (
            "gcloud was not found on PATH. Install the Google Cloud SDK, then see "
            f"{self._rel(self.configuration)} and {self._rel(self.contributing)}. " + self.setup_reminder_line()
        )

    def missing_dev_dependency_line(self, *, what: str) -> str:
        return (
            f"{what} is not available — install the repo dev environment from the repository root "
            f"(`just onboard` or `uv sync` includes dev dependencies). " + self.setup_reminder_line()
        )

    def external_cli_missing_line(self, *, cli: str, hint: str) -> str:
        """e.g. gh, pulumi — `hint` is one short sentence (upstream install or recipe)."""
        return f"{cli} was not found on PATH. {hint} {self.setup_reminder_line()}"


def setup_docs_one_line() -> str:
    """Standard reminder line (paths from repo root via `repo_root()`)."""
    return ContributorDocRefs.discover().setup_reminder_line()


def missing_dev_dependency_message(*, what: str) -> str:
    return ContributorDocRefs.discover().missing_dev_dependency_line(what=what)


def gcloud_cli_missing_message() -> str:
    return ContributorDocRefs.discover().gcloud_missing_line()


# Cached import-time string; same text as `setup_docs_one_line()` (call the function for tests/mocks).
SETUP_DOCS_ONE_LINE = setup_docs_one_line()
