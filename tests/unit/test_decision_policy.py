"""Gate logic. These tests are the contract for what passes and what does not."""

from __future__ import annotations

import pytest

from bioforge.engine.decision_policy import (
    GATE_ORDER,
    apply_thresholds,
    compute_rank_score,
    evaluate_candidate,
    evaluate_gate,
    load_policy,
    pick_redesign_target,
    shortlist,
)
from bioforge.models import AdapterMode, Candidate, Provenance, TestResult


def prov(tool: str = "test") -> Provenance:
    return Provenance(tool=tool, mode=AdapterMode.FIXTURE, model_version="test/v1")


def make_test(gate: str, metric: str, value: float) -> TestResult:
    return TestResult(
        gate=gate,  # type: ignore[arg-type]
        metric=metric,
        value=value,
        direction="informational",
        tool="test",
        provenance=prov(),
    )


def make_candidate(cid: str, metrics: dict[str, float]) -> Candidate:
    gate_of = {
        "interface_confidence": "binding",
        "predicted_dg_kcal_mol": "binding",
        "model_agreement": "independent_structure",
        "epitope_rmsd_angstrom": "independent_structure",
        "surface_hydrophobicity": "developability",
        "aggregation_propensity": "developability",
        "net_charge_at_ph7": "developability",
        "unpaired_cysteines": "developability",
        "n_glyc_sequons": "developability",
        "predicted_tm_celsius": "developability",
        "immunogenicity_risk": "developability",
        "retained_score_across_mutations": "robustness",
        "decoy_discrimination_margin": "robustness",
    }
    return Candidate(
        id=cid,
        name=cid,
        sequence="QVQLVESGGG",
        tests=[make_test(gate_of[m], m, v) for m, v in metrics.items()],
    )


PASSING = {
    "interface_confidence": 0.85,
    "predicted_dg_kcal_mol": -10.0,
    "model_agreement": 0.80,
    "epitope_rmsd_angstrom": 1.5,
    "surface_hydrophobicity": 0.40,
    "aggregation_propensity": 0.10,
    "net_charge_at_ph7": 2.0,
    "unpaired_cysteines": 0.0,
    "n_glyc_sequons": 0.0,
    "predicted_tm_celsius": 72.0,
    "immunogenicity_risk": 0.15,
    "retained_score_across_mutations": 0.80,
    "decoy_discrimination_margin": 0.35,
}


@pytest.fixture
def policy():
    return load_policy()


# -- thresholds ------------------------------------------------------------


def test_thresholds_come_from_the_policy_file_not_code(policy):
    tests = [make_test("binding", "interface_confidence", 0.70)]
    apply_thresholds(policy, tests)
    spec = policy.gate("binding").metric("interface_confidence")
    assert tests[0].threshold == spec.minimum
    assert tests[0].direction == "higher_is_better"


def test_higher_is_better_boundary_is_inclusive(policy):
    minimum = policy.gate("binding").metric("interface_confidence").minimum
    tests = [make_test("binding", "interface_confidence", minimum)]
    apply_thresholds(policy, tests)
    assert tests[0].passed is True


def test_lower_is_better_boundary_is_inclusive(policy):
    maximum = policy.gate("developability").metric("surface_hydrophobicity").maximum
    tests = [make_test("developability", "surface_hydrophobicity", maximum)]
    apply_thresholds(policy, tests)
    assert tests[0].passed is True


def test_in_range_metric_fails_on_both_sides(policy):
    spec = policy.gate("developability").metric("net_charge_at_ph7")
    low = [make_test("developability", "net_charge_at_ph7", spec.minimum - 0.1)]
    high = [make_test("developability", "net_charge_at_ph7", spec.maximum + 0.1)]
    apply_thresholds(policy, low)
    apply_thresholds(policy, high)
    assert low[0].passed is False
    assert high[0].passed is False


def test_informational_metric_never_gates(policy):
    tests = [make_test("binding", "predicted_dg_kcal_mol", 999.0)]
    apply_thresholds(policy, tests)
    assert tests[0].passed is None
    outcome = evaluate_gate(policy, "binding", tests)
    # With only an informational metric there is nothing to judge.
    assert outcome.metrics_failed == []


def test_unknown_metric_is_kept_but_cannot_gate(policy):
    tests = [make_test("binding", "some_new_metric_the_policy_has_never_heard_of", 0.1)]
    apply_thresholds(policy, tests)
    assert tests[0].passed is None
    assert tests[0].direction == "informational"


# -- gate outcomes ---------------------------------------------------------


def test_all_passing_candidate_advances(policy):
    candidate = evaluate_candidate(policy, make_candidate("C1", PASSING))
    assert candidate.status == "survives"
    assert candidate.decision.outcome == "advance"
    assert all(g.passed for g in candidate.gates)


def test_binding_failure_rejects_with_the_right_code(policy):
    metrics = {**PASSING, "interface_confidence": 0.40}
    candidate = evaluate_candidate(policy, make_candidate("C2", metrics))
    assert candidate.status == "rejected"
    assert candidate.decision.reason_codes == ["BIND_LOW_CONFIDENCE"]


def test_structure_disagreement_rejects(policy):
    metrics = {**PASSING, "model_agreement": 0.40}
    candidate = evaluate_candidate(policy, make_candidate("C3", metrics))
    assert candidate.status == "rejected"
    assert "STRUCT_DISAGREEMENT" in candidate.decision.reason_codes


def test_developability_tolerates_exactly_one_liability(policy):
    tolerance = policy.gate("developability").max_failed_metrics
    assert tolerance == 1, "this test encodes the configured tolerance"

    one_bad = {**PASSING, "n_glyc_sequons": 3.0}
    assert evaluate_candidate(policy, make_candidate("C4", one_bad)).status == "survives"

    two_bad = {**PASSING, "n_glyc_sequons": 3.0, "unpaired_cysteines": 2.0}
    rejected = evaluate_candidate(policy, make_candidate("C5", two_bad))
    assert rejected.status == "rejected"
    assert rejected.decision.reason_codes == ["DEV_MULTIPLE_LIABILITIES"]


def test_robustness_failures_are_distinguishable(policy):
    fragile = {**PASSING, "retained_score_across_mutations": 0.20}
    decoy = {**PASSING, "decoy_discrimination_margin": 0.02}
    assert (
        "ROBUST_MUTATION_FRAGILE"
        in evaluate_candidate(policy, make_candidate("C6", fragile)).decision.reason_codes
    )
    assert (
        "ROBUST_DECOY_BINDING"
        in evaluate_candidate(policy, make_candidate("C7", decoy)).decision.reason_codes
    )


def test_rejection_reports_the_first_failing_gate_in_order(policy):
    metrics = {**PASSING, "interface_confidence": 0.1, "model_agreement": 0.1}
    candidate = evaluate_candidate(policy, make_candidate("C8", metrics))
    assert candidate.decision.summary.lower().startswith("rejected at the predicted binding")


def test_partial_run_stays_pending_not_advanced(policy):
    partial = make_candidate("C9", {"interface_confidence": 0.9, "predicted_dg_kcal_mol": -9.0})
    candidate = evaluate_candidate(policy, partial, gates_to_run=["binding"])
    assert candidate.status == "active"
    assert candidate.decision.outcome == "pending"


# -- decision content ------------------------------------------------------


def test_every_decision_carries_reversal_conditions(policy):
    for metrics in ({**PASSING, "interface_confidence": 0.1}, PASSING):
        candidate = evaluate_candidate(policy, make_candidate("CX", metrics))
        assert candidate.decision.reversal_conditions, "a decision must be falsifiable"
        assert candidate.decision.uncertainties


def test_decision_always_says_the_scores_are_predictions(policy):
    candidate = evaluate_candidate(policy, make_candidate("C10", PASSING))
    joined = " ".join(candidate.decision.uncertainties).lower()
    assert "prediction" in joined


def test_decision_records_the_policy_version(policy):
    candidate = evaluate_candidate(policy, make_candidate("C11", PASSING))
    assert candidate.decision.policy_version == policy.version


def test_near_threshold_call_is_flagged_as_flippable(policy):
    metrics = {**PASSING, "interface_confidence": 0.66}  # threshold 0.65, uncertainty is larger
    candidate = make_candidate("C12", metrics)
    for test in candidate.tests:
        if test.metric == "interface_confidence":
            test.uncertainty = 0.06
    evaluate_candidate(policy, candidate)
    assert any("could flip" in u for u in candidate.decision.uncertainties)


# -- ranking ---------------------------------------------------------------


def test_rank_score_is_reproducible_from_raw_metrics(policy):
    candidate = evaluate_candidate(policy, make_candidate("C13", PASSING))
    recomputed, breakdown = compute_rank_score(policy, candidate)
    assert recomputed == candidate.rank_score
    assert sum(row["contribution"] for row in breakdown) == pytest.approx(
        recomputed * sum(c.weight for c in policy.ranking), abs=1e-3
    )


def test_ranking_orders_by_score_and_marks_finalists(policy):
    strong = evaluate_candidate(policy, make_candidate("A", PASSING))
    middle = evaluate_candidate(
        policy, make_candidate("B", {**PASSING, "interface_confidence": 0.75})
    )
    weak = evaluate_candidate(
        policy, make_candidate("C", {**PASSING, "interface_confidence": 0.68})
    )
    extra = evaluate_candidate(
        policy, make_candidate("D", {**PASSING, "interface_confidence": 0.66})
    )

    ordered = shortlist(policy, [extra, weak, middle, strong], max_finalists=3)
    assert [c.id for c in ordered] == ["A", "B", "C", "D"]
    assert strong.status == "recommended" and strong.rank == 1
    assert extra.status == "survives" and extra.rank == 4
    assert "NOT_SHORTLISTED" in extra.decision.reason_codes


def test_ranking_never_promotes_a_rejected_candidate(policy):
    rejected = evaluate_candidate(
        policy, make_candidate("R", {**PASSING, "interface_confidence": 0.1})
    )
    ordered = shortlist(policy, [rejected], max_finalists=3)
    assert ordered == []
    assert rejected.status == "rejected"


# -- redesign selection -----------------------------------------------------


def test_near_miss_is_the_smallest_margin(policy):
    narrow = evaluate_candidate(
        policy, make_candidate("NARROW", {**PASSING, "model_agreement": 0.59})
    )
    wide = evaluate_candidate(policy, make_candidate("WIDE", {**PASSING, "model_agreement": 0.10}))
    assert pick_redesign_target(policy, [wide, narrow]).id == "NARROW"


def test_no_redesign_target_when_nothing_was_rejected(policy):
    passing = evaluate_candidate(policy, make_candidate("OK", PASSING))
    assert pick_redesign_target(policy, [passing]) is None


def test_gate_order_matches_the_policy_file(policy):
    assert [g.name for g in policy.gates] == GATE_ORDER


def test_thresholds_are_marked_uncalibrated(policy):
    """If someone calibrates a threshold they must cite it; the UI reads this."""
    exported = policy.as_dict()
    for gate in exported["gates"]:
        for metric in gate["metrics"]:
            assert metric["calibrated"] == (metric["source"] is not None)
