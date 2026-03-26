"""ContributorDocRefs includes the adding-a-project guide path."""

from __future__ import annotations

from tools.shared.contributor_docs import ContributorDocRefs


def test_adding_a_project_doc_exists() -> None:
    refs = ContributorDocRefs.discover()
    p = refs.adding_a_project
    assert p.name == "adding-a-project.md"
    assert p.is_file()
