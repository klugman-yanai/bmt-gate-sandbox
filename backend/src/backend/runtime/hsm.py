"""Generic hierarchical state machine base (stdlib only).

States form an inheritance hierarchy; dispatch uses ``on_<message.name.lower>()``
on the current state. The machine owns transitions and calls ``on_exit`` /
``on_enter`` around each change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum


class UnsupportedMessageError(Exception):
    """Current state has no handler for this message."""


class UnsupportedTransitionError(Exception):
    """Message is structurally known but disallowed from the current state."""


class UnsupportedStateError(Exception):
    """Transition target is not a registered state key."""


class State:
    """Base class for HSM states."""

    def on_enter(self) -> None:
        """Side effects when entering (e.g. persist checkpoint)."""

    def on_exit(self) -> None:
        """Called before leaving this state."""

    def _reject(self) -> None:
        raise UnsupportedTransitionError(f"{type(self).__name__!r} does not handle this message")


class HierarchicalStateMachine[StateKeyT: Enum, MsgT: Enum](ABC):
    """Generic HSM: dispatch ``on_message`` to ``on_<msg.name.lower>()`` on current state."""

    def __init__(self, initial: StateKeyT) -> None:
        self._states: dict[StateKeyT, State] = self._build_states()
        if initial not in self._states:
            raise UnsupportedStateError(f"Unknown initial state: {initial!r}")
        self._current_key: StateKeyT = initial
        self._current_state: State = self._states[initial]
        self._current_state.on_enter()

    @abstractmethod
    def _build_states(self) -> dict[StateKeyT, State]:
        """Return the full ``{StateKey → State}`` map (once at init)."""

    @property
    def state(self) -> StateKeyT:
        return self._current_key

    def on_message(self, message: MsgT) -> None:
        handler_name = f"on_{message.name.lower()}"
        handler = getattr(self._current_state, handler_name, None)
        if handler is None:
            raise UnsupportedMessageError(
                f"State {type(self._current_state).__name__!r} has no handler for {message!r}"
            )
        handler()

    def transition(self, next_key: StateKeyT) -> None:
        if next_key not in self._states:
            raise UnsupportedStateError(f"Unknown target state: {next_key!r}")
        self._current_state.on_exit()
        self._current_key = next_key
        self._current_state = self._states[next_key]
        self._current_state.on_enter()
