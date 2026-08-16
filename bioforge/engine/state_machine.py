"""Explicit workflow state machine.

An investigation is not a chat loop. It is a finite set of states with a
declared transition table, and every move through it writes an immutable audit
event. `NEEDS_REVIEW` and `FAILED` are reachable from every non-terminal state,
which is what lets a tool failure surface as a state rather than an exception
that vanishes into a log.
"""

from __future__ import annotations

from ..models import WorkflowState as S

#: The happy path, in order.
MAIN_SEQUENCE: list[S] = [
    S.CREATED,
    S.EVIDENCE_GATHERING,
    S.HYPOTHESES_CREATED,
    S.CANDIDATES_READY,
    S.PRIMARY_TESTING,
    S.INDEPENDENT_VALIDATION,
    S.ADVERSARIAL_CHALLENGE,
    S.REDESIGNING,
    S.FINAL_REVIEW,
    S.PACKAGE_CREATED,
    S.COMPLETED,
]

TERMINAL: frozenset[S] = frozenset({S.COMPLETED, S.FAILED})

#: Any non-terminal state may escalate.
_ESCALATIONS: set[S] = {S.NEEDS_REVIEW, S.FAILED}

TRANSITIONS: dict[S, set[S]] = {
    S.CREATED: {S.EVIDENCE_GATHERING},
    S.EVIDENCE_GATHERING: {S.HYPOTHESES_CREATED},
    S.HYPOTHESES_CREATED: {S.CANDIDATES_READY},
    S.CANDIDATES_READY: {S.PRIMARY_TESTING},
    S.PRIMARY_TESTING: {S.INDEPENDENT_VALIDATION},
    # The challenge is a human-triggered action, so validation can also park at
    # FINAL_REVIEW if the operator never presses the button.
    S.INDEPENDENT_VALIDATION: {S.ADVERSARIAL_CHALLENGE, S.FINAL_REVIEW},
    # Redesign is optional and capped at one iteration for the MVP.
    S.ADVERSARIAL_CHALLENGE: {S.REDESIGNING, S.FINAL_REVIEW},
    S.REDESIGNING: {S.FINAL_REVIEW},
    S.FINAL_REVIEW: {S.PACKAGE_CREATED},
    S.PACKAGE_CREATED: {S.COMPLETED},
    S.COMPLETED: set(),
    # A reviewed investigation can be resumed into review or packaging.
    S.NEEDS_REVIEW: {S.FINAL_REVIEW, S.ADVERSARIAL_CHALLENGE, S.REDESIGNING, S.PACKAGE_CREATED},
    S.FAILED: set(),
}

for _state, _targets in TRANSITIONS.items():
    if _state not in TERMINAL:
        _targets |= _ESCALATIONS


class InvalidTransition(ValueError):
    def __init__(self, current: S, requested: S) -> None:
        allowed = ", ".join(sorted(t.value for t in TRANSITIONS.get(current, set()))) or "none"
        super().__init__(
            f"cannot move from {current.value} to {requested.value}; allowed: {allowed}"
        )
        self.current = current
        self.requested = requested


def can_transition(current: S, requested: S) -> bool:
    return requested in TRANSITIONS.get(current, set())


def assert_transition(current: S, requested: S) -> None:
    if not can_transition(current, requested):
        raise InvalidTransition(current, requested)


def progress_fraction(state: S) -> float:
    """0..1 for the timeline widget. Escalations report the last known position."""
    if state in (S.NEEDS_REVIEW, S.FAILED):
        return 1.0
    try:
        index = MAIN_SEQUENCE.index(state)
    except ValueError:
        return 0.0
    return round(index / (len(MAIN_SEQUENCE) - 1), 3)
