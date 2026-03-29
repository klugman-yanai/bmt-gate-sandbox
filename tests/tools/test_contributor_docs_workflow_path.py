"""ContributorDocRefs includes the consolidated contributors guide path."""

from __future__ import annotations

from tools.shared.contributor_docs import ContributorDocRefs


def test_contributors_guide_doc_exists() -> None:
    refs = ContributorDocRefs.discover()
    p = refs.contributors_guide
    assert p.name == "contributors.md"
    assert p.is_file()
