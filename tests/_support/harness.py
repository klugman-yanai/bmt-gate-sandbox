# Re-export shim — import from tests.support.fakes instead for new code.
from tests.support.fakes.gcs import FakeGcsStore, JSONDict, JSONValue
from tests.support.fakes.github import FakeGithubBackend
from tests.support.fakes.vm import FakeVmBackend, VmDescribeStatus, VmMetadataCallRecord

__all__ = [
    "FakeGcsStore",
    "FakeGithubBackend",
    "FakeVmBackend",
    "JSONDict",
    "JSONValue",
    "VmDescribeStatus",
    "VmMetadataCallRecord",
]
