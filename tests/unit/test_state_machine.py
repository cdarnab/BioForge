import pytest

from bioforge.engine.state_machine import (
    MAIN_SEQUENCE,
    TERMINAL,
    TRANSITIONS,
    InvalidTransition,
    assert_transition,
    can_transition,
    progress_fraction,
)
from bioforge.models import WorkflowState as S


def test_happy_path_is_fully_connected():
    for current, following in zip(MAIN_SEQUENCE, MAIN_SEQUENCE[1:], strict=False):
        assert can_transition(current, following), f"{current} -> {following} should be allowed"


def test_cannot_skip_a_phase():
    assert not can_transition(S.CREATED, S.CANDIDATES_READY)
    assert not can_transition(S.EVIDENCE_GATHERING, S.PRIMARY_TESTING)
    assert not can_transition(S.PRIMARY_TESTING, S.COMPLETED)


def test_cannot_run_backwards():
    assert not can_transition(S.PRIMARY_TESTING, S.EVIDENCE_GATHERING)
    assert not can_transition(S.COMPLETED, S.FINAL_REVIEW)


def test_every_non_terminal_state_can_escalate():
    for state in S:
        if state in TERMINAL:
            continue
        assert can_transition(state, S.NEEDS_REVIEW), f"{state} must be able to reach NEEDS_REVIEW"
        assert can_transition(state, S.FAILED), f"{state} must be able to reach FAILED"


def test_terminal_states_have_no_exit():
    assert TRANSITIONS[S.COMPLETED] == set()
    assert TRANSITIONS[S.FAILED] == set()


def test_redesign_is_optional():
    # The challenge may go straight to review when nothing is worth redesigning.
    assert can_transition(S.ADVERSARIAL_CHALLENGE, S.FINAL_REVIEW)
    assert can_transition(S.ADVERSARIAL_CHALLENGE, S.REDESIGNING)


def test_challenge_is_skippable_from_validation():
    assert can_transition(S.INDEPENDENT_VALIDATION, S.FINAL_REVIEW)


def test_needs_review_can_resume():
    assert can_transition(S.NEEDS_REVIEW, S.FINAL_REVIEW)
    assert can_transition(S.NEEDS_REVIEW, S.PACKAGE_CREATED)


def test_assert_transition_raises_with_the_allowed_set():
    with pytest.raises(InvalidTransition) as excinfo:
        assert_transition(S.CREATED, S.COMPLETED)
    assert "EVIDENCE_GATHERING" in str(excinfo.value)


def test_progress_is_monotonic():
    values = [progress_fraction(state) for state in MAIN_SEQUENCE]
    assert values == sorted(values)
    assert values[0] == 0.0
    assert values[-1] == 1.0
