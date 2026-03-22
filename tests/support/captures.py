"""Generic call recorder — replaces hand-rolled ``_FooCapture`` dataclasses in tests.

Usage::

    cap = CallRecorder()

    class FakeReporter:
        def __init__(self, *, repository: str, ...) -> None:
            cap.repository = repository

        def some_method(self, *, value: int) -> None:
            cap.value = value

    ...
    assert cap.value == 42
"""

from __future__ import annotations

from typing import Any


class CallRecorder:
    """Stores arbitrary attributes set during test execution.

    Drop-in replacement for ad-hoc ``@dataclass`` capture classes. No field
    pre-declaration needed; just assign attributes inside inline fake classes
    and assert on them afterwards.

    ``__getattr__`` / ``__setattr__`` are typed for static analysis (e.g. ``ty``);
    runtime behavior matches a plain instance namespace.
    """

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)
