# Re-export shim — import from tests.support.testutils instead for new code.
from tests.support.testutils import (
    assert_github_matrix_include_shape,
    assert_matrix_projects_subset,
    combined_output,
    decode_output_json,
    read_github_output,
)

__all__ = [
    "assert_github_matrix_include_shape",
    "assert_matrix_projects_subset",
    "combined_output",
    "decode_output_json",
    "read_github_output",
]
