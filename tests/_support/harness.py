# Re-export shim — import from tests.support.fakes instead for new code.
from tests.support.fakes.gcs import FakeGcsStore, JSONDict, JSONValue
from tests.support.fakes.github import FakeGithubBackend

__all__ = [
    "FakeGcsStore",
    "FakeGithubBackend",
    "JSONDict",
    "JSONValue",
]
