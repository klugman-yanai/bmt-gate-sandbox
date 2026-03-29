"""
Generic Hierarchical State Machine (HSM) base — stdlib only, Pydantic-friendly.

Design
------
- States are objects organised in an inheritance hierarchy; parent classes
  provide shared behaviour, subclasses override only what differs.
- Messages are Enum members; dispatch calls ``on_<message.name.lower()>()``
  on the current state.
- The HSM owns all side-effect methods; states call back via ``self._hsm``.
- ``on_enter`` / ``on_exit`` hooks fire on every transition — use them for
  logging, metrics, or persistence (e.g. writing a Pydantic record to GCS).

Usage
-----
1. Define ``StateKey(Enum)`` and ``Message(Enum)``.
2. Define a ``Protocol`` declaring the action methods and ``transition()``
   that states will call back into — this breaks the forward-reference cycle.
3. Subclass ``State`` for each state (or state group); override the message
   handlers that are valid from that state.
4. Subclass ``HSM[StateKey, Message]``; implement ``_build_states()`` and
   the action methods declared in the protocol.

Project fit
-----------
The best immediate candidate is the *finalization state machine* inside
``backend/src/backend/runtime/entrypoint.py::run_coordinator_mode()``.

That function already defines a ``FinalizationState`` enum and a persistent
``FinalizationRecordV2`` checkpoint — but the transitions are scattered across
~200 lines of sequential if-guards and early returns.  The concrete example
below (``FinalizationMachine``) shows how that logic maps to the HSM.

Hierarchy for the finalization machine:

    CoordinatorState            (rejects all messages by default)
    ├── ActiveCoordinator       (holds leases; ABORT always leads to failure)
    │   ├── Prepared            PLAN_READY → publish-ok/skip/abort
    │   └── GithubPublished     PROMOTE → promote-ok/abort
    └── TerminalCoordinator     (success or error; rejects every message)
        ├── PromotionCommitted  ← idempotent success terminal
        ├── FailedGithubPublish
        └── FailedPromotion
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Protocol, override


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class UnsupportedMessageError(Exception):
    """Current state has no handler for this message."""


class UnsupportedTransitionError(Exception):
    """Message is structurally known but disallowed from the current state."""


class UnsupportedStateError(Exception):
    """Transition target is not a registered state key."""


# ---------------------------------------------------------------------------
# Base state
# ---------------------------------------------------------------------------


class State:
    """Base class for all states in an HSM.

    Every unhandled message raises ``UnsupportedTransitionError`` by default
    (via ``_reject``).  Subclasses override only the handlers that apply;
    parent classes provide the *shared* (hierarchical) behaviour.

    States receive a back-reference to the owning HSM so they can call
    ``self._hsm.transition(key)`` and the HSM's action methods.
    """

    def on_enter(self) -> None:
        """Called immediately after entering this state.  Override for side
        effects such as writing a checkpoint record or emitting a log line."""

    def on_exit(self) -> None:
        """Called immediately before leaving this state."""

    def _reject(self) -> None:
        """Raise UnsupportedTransitionError with the state's class name."""
        raise UnsupportedTransitionError(
            f"{type(self).__name__!r} does not handle this message"
        )


# ---------------------------------------------------------------------------
# HSM base  (Python 3.12 PEP 695 type-parameter syntax)
# ---------------------------------------------------------------------------


class HSM[StateKeyT: Enum, MsgT: Enum](ABC):
    """Generic hierarchical state machine base class.

    Dispatch contract
    ~~~~~~~~~~~~~~~~~
    For a message ``M`` (a ``MsgT`` enum member) the dispatcher calls
    ``on_<M.name.lower()>()`` on ``self._current_state``.

    - Method absent on the state  →  ``UnsupportedMessageError``
    - Method present but raises ``UnsupportedTransitionError``  →  propagated
    - Method present and succeeds  →  side effects + optional transition

    Subclassing
    ~~~~~~~~~~~
    1. Override ``_build_states()`` — return ``{StateKey: State}``; the HSM
       stores the mapping and never re-creates states after ``__init__``.
    2. Define a Protocol for the action methods that states call back into
       (see ``FinalizationActions`` below).  This avoids forward references
       and lets states be tested against lightweight fakes.
    """

    def __init__(self, initial: StateKeyT) -> None:
        self._states: dict[StateKeyT, State] = self._build_states()
        if initial not in self._states:
            raise UnsupportedStateError(f"Unknown initial state: {initial!r}")
        self._current_key: StateKeyT = initial
        self._current_state: State = self._states[initial]
        self._current_state.on_enter()

    @abstractmethod
    def _build_states(self) -> dict[StateKeyT, State]:
        """Return the complete ``{StateKey → State}`` mapping.

        Called once from ``__init__``.  Each ``State`` instance receives
        ``self`` (the HSM) so it can call back for transitions and actions.
        """

    # -- public API -----------------------------------------------------------

    @property
    def state(self) -> StateKeyT:
        """Current state key (read-only)."""
        return self._current_key

    def on_message(self, message: MsgT) -> None:
        """Dispatch *message* to the current state.

        Raises ``UnsupportedMessageError`` if the current state has no handler.
        """
        handler_name = f"on_{message.name.lower()}"
        handler = getattr(self._current_state, handler_name, None)
        if handler is None:
            raise UnsupportedMessageError(
                f"State {type(self._current_state).__name__!r} has no handler for {message!r}"
            )
        handler()

    def transition(self, next_key: StateKeyT) -> None:
        """Exit the current state and enter *next_key*.

        Calls ``on_exit()`` on the old state and ``on_enter()`` on the new
        one.  Raises ``UnsupportedStateError`` for unknown keys.
        """
        if next_key not in self._states:
            raise UnsupportedStateError(f"Unknown target state: {next_key!r}")
        self._current_state.on_exit()
        self._current_key = next_key
        self._current_state = self._states[next_key]
        self._current_state.on_enter()


# ===========================================================================
# Concrete example: BMT finalization lifecycle
# ===========================================================================
#
# Maps to the FinalizationState enum + run_coordinator_mode() in
#   backend/src/backend/runtime/entrypoint.py
#
# State hierarchy
# ---------------
#
#   CoordinatorState            (rejects all messages by default)
#   ├── ActiveCoordinator       (holds leases; ABORT always leads to FAILED)
#   │   ├── Prepared            PLAN_READY → publish-ok/skip/abort
#   │   └── GithubPublished     PROMOTE → promote-ok/abort
#   └── TerminalCoordinator     (all messages rejected — no further work)
#       ├── PromotionCommitted  ← idempotent success terminal
#       ├── FailedGithubPublish
#       └── FailedPromotion
#
# ===========================================================================


class FinalizationKey(Enum):
    PREPARED = auto()
    GITHUB_PUBLISHED = auto()
    PROMOTION_COMMITTED = auto()
    FAILED_GITHUB_PUBLISH = auto()
    FAILED_PROMOTION = auto()


class FinalizationEvent(Enum):
    PUBLISH_OK = auto()
    PUBLISH_SKIP = auto()
    PROMOTE_OK = auto()
    ABORT = auto()


# ---------------------------------------------------------------------------
# Action protocol  — defined before the state hierarchy so states can depend
# on it without a forward reference to the concrete FinalizationMachine.
# Matches the project's pattern in backend/src/backend/runtime/sdk/protocols.py.
# ---------------------------------------------------------------------------


class FinalizationActions(Protocol):
    """Actions that states call back into the machine to perform."""

    def transition(self, next_key: FinalizationKey) -> None: ...
    def persist_state(self, key: FinalizationKey) -> None: ...
    def finalize_check_run(self) -> None: ...
    def post_final_github_status(self) -> None: ...
    def post_failure_github_status(self) -> None: ...
    def promote_results(self) -> None: ...
    def release_leases(self) -> None: ...
    def cleanup_ephemeral_triggers(self) -> None: ...


# --- state hierarchy --------------------------------------------------------


class CoordinatorState(State):
    """Base for all finalization states.  Holds the HSM back-reference."""

    def __init__(self, hsm: FinalizationActions) -> None:
        self._hsm: FinalizationActions = hsm

    # All messages rejected unless a subclass overrides.
    def on_publish_ok(self) -> None:
        self._reject()

    def on_publish_skip(self) -> None:
        self._reject()

    def on_promote_ok(self) -> None:
        self._reject()

    def on_abort(self) -> None:
        self._reject()


class ActiveCoordinator(CoordinatorState):
    """Shared behaviour for in-progress states: ABORT always leads to failure."""

    @override
    def on_abort(self) -> None:
        self._hsm.release_leases()
        self._hsm.transition(FinalizationKey.FAILED_PROMOTION)


class Prepared(ActiveCoordinator):
    @override
    def on_enter(self) -> None:
        self._hsm.persist_state(FinalizationKey.PREPARED)

    @override
    def on_publish_ok(self) -> None:
        self._hsm.finalize_check_run()
        self._hsm.post_final_github_status()
        self._hsm.transition(FinalizationKey.GITHUB_PUBLISHED)

    @override
    def on_publish_skip(self) -> None:
        # publish_required=False — jump straight to promotion.
        self._hsm.promote_results()
        self._hsm.transition(FinalizationKey.PROMOTION_COMMITTED)


class GithubPublished(ActiveCoordinator):
    @override
    def on_enter(self) -> None:
        self._hsm.persist_state(FinalizationKey.GITHUB_PUBLISHED)

    @override
    def on_promote_ok(self) -> None:
        self._hsm.promote_results()
        self._hsm.transition(FinalizationKey.PROMOTION_COMMITTED)


class TerminalCoordinator(CoordinatorState):
    """All messages rejected — the run is done."""

    @override
    def on_abort(self) -> None:
        self._reject()  # already terminal


class PromotionCommitted(TerminalCoordinator):
    """Idempotent success terminal: on_enter is safe to call multiple times."""

    @override
    def on_enter(self) -> None:
        self._hsm.persist_state(FinalizationKey.PROMOTION_COMMITTED)
        self._hsm.cleanup_ephemeral_triggers()


class FailedGithubPublish(TerminalCoordinator):
    @override
    def on_enter(self) -> None:
        self._hsm.persist_state(FinalizationKey.FAILED_GITHUB_PUBLISH)
        self._hsm.post_failure_github_status()


class FailedPromotion(TerminalCoordinator):
    @override
    def on_enter(self) -> None:
        self._hsm.persist_state(FinalizationKey.FAILED_PROMOTION)
        self._hsm.post_failure_github_status()


# --- concrete machine -------------------------------------------------------


class FinalizationMachine(HSM[FinalizationKey, FinalizationEvent]):
    """
    State machine for one BMT coordinator run (finalization lifecycle).

    Instantiate with the *current persisted state* so re-entrant runs
    (Cloud Run retries) resume from the correct point:

        machine = FinalizationMachine(
            initial=existing_record.state or FinalizationKey.PREPARED
        )

    Then drive it with events:

        if publish_required:
            _run_publish_stage(...)        # may raise
            machine.on_message(FinalizationEvent.PUBLISH_OK)
        else:
            machine.on_message(FinalizationEvent.PUBLISH_SKIP)

        machine.on_message(FinalizationEvent.PROMOTE_OK)

    Replace the stub action methods with real calls to the existing
    HandoffManager, GCS writers, lease manager, and GitHub status client.
    """

    @override
    def _build_states(self) -> dict[FinalizationKey, State]:
        return {
            FinalizationKey.PREPARED: Prepared(self),
            FinalizationKey.GITHUB_PUBLISHED: GithubPublished(self),
            FinalizationKey.PROMOTION_COMMITTED: PromotionCommitted(self),
            FinalizationKey.FAILED_GITHUB_PUBLISH: FailedGithubPublish(self),
            FinalizationKey.FAILED_PROMOTION: FailedPromotion(self),
        }

    # --- action stubs (wire to real collaborators in entrypoint.py) ---------

    def persist_state(self, key: FinalizationKey) -> None:
        """Write FinalizationRecordV2 checkpoint → GCS / local disk."""

    def finalize_check_run(self) -> None:
        """Call githubkit to complete the GitHub Actions check run."""

    def post_final_github_status(self) -> None:
        """Post PASS/FAIL commit status + upsert summary comment."""

    def post_failure_github_status(self) -> None:
        """Post failure commit status with error_message."""

    def promote_results(self) -> None:
        """Write current.json pointers, prune old snapshots, release leases."""

    def release_leases(self) -> None:
        """Release GCS lease files on abort before entering a terminal state."""

    def cleanup_ephemeral_triggers(self) -> None:
        """Delete progress records and other ephemeral trigger files."""
