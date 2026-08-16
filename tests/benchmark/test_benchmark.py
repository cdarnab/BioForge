"""The benchmark must recover the blinded controls and the ablations must bite."""

from __future__ import annotations

import pytest

from bioforge.benchmark.harness import (
    ablate,
    auroc,
    rerun_offline,
    run_benchmark,
    single_model_baseline,
)
from bioforge.engine.decision_policy import load_policy


def test_auroc_maths():
    assert auroc([1.0], [0.0]) == 1.0
    assert auroc([0.0], [1.0]) == 0.0
    assert auroc([0.5], [0.5]) == 0.5
    assert auroc([], [1.0]) is None


async def test_positive_control_outranks_every_negative(settings):
    result = await run_benchmark(1, settings=settings)
    assert result.positive_control_rank == 1
    assert result.negative_control_ranks
    for negative, rank in result.negative_control_ranks.items():
        assert rank > result.positive_control_rank, f"{negative} outranked the positive control"


async def test_auroc_and_enrichment_are_reported(settings):
    result = await run_benchmark(1, settings=settings)
    assert result.auroc == 1.0
    assert result.top_k_enrichment[1] > 1.0
    assert result.top_k_enrichment[3] > 1.0


async def test_negative_controls_are_all_rejected(settings):
    result = await run_benchmark(1, settings=settings)
    rejected = {cid for ids in result.gate_rejections.values() for cid in ids}
    for negative in result.negative_control_ranks:
        assert negative in rejected, f"{negative} was not rejected"


async def test_gate_rejection_counts_are_reported_per_gate(settings):
    result = await run_benchmark(1, settings=settings)
    assert set(result.gate_rejections) == {
        "binding",
        "independent_structure",
        "developability",
        "robustness",
    }


async def test_runtime_seed_and_cost_are_reported(settings):
    result = await run_benchmark(7, settings=settings)
    assert result.seed == 7
    assert result.runtime_seconds > 0
    assert result.approximate_cost_usd == 0.0
    assert "no live model calls" in result.cost_note.lower()


async def test_model_agreement_is_reported_for_the_candidates_that_reached_gate_two(settings):
    result = await run_benchmark(1, settings=settings)
    assert result.model_agreement
    assert all(0.0 <= v <= 1.0 for v in result.model_agreement.values())


async def test_results_are_stable_across_seeds_and_say_why(settings):
    """Fixture data is seed-invariant; the harness must not pretend otherwise."""
    a = await run_benchmark(1, settings=settings, include_ablations=False)
    b = await run_benchmark(2, settings=settings, include_ablations=False)
    c = await run_benchmark(3, settings=settings, include_ablations=False)
    assert a.ranking == b.ranking == c.ranking
    assert a.shortlist == b.shortlist == c.shortlist


# -- ablations --------------------------------------------------------------


def test_ablate_removes_exactly_one_gate():
    policy = load_policy()
    reduced = ablate(policy, "robustness")
    assert [g.name for g in reduced.gates] == [
        "binding",
        "independent_structure",
        "developability",
    ]
    assert "ablate:robustness" in reduced.version
    # The original is untouched.
    assert len(policy.gates) == 4


async def test_each_ablation_lets_previously_rejected_candidates_through(settings):
    result = await run_benchmark(1, settings=settings)
    for gate in ("independent_structure", "developability", "robustness"):
        data = result.ablations[f"without_{gate}"]
        assert data["escaped_rejection"], (
            f"removing the {gate} gate changed nothing, so the gate is not doing work"
        )
        assert data["total_rejected"] < result.ablations["_baseline"]["total_rejected"]


async def test_single_model_score_would_ship_a_candidate_the_pipeline_rejected(settings):
    """This is the product's core claim, so it is asserted rather than described."""
    result = await run_benchmark(1, settings=settings)
    baseline = result.ablations["_single_model_score"]
    assert baseline["picks_the_full_pipeline_rejected"], (
        "on this fixture set a single model score picks the same top-3 as the full "
        "pipeline, which would undercut the whole premise"
    )
    caught = baseline["picks_the_full_pipeline_rejected"]
    assert any(info["gate"] == "robustness" for info in caught.values())


@pytest.mark.parametrize("gate", ["independent_structure", "developability", "robustness"])
async def test_ablation_never_loses_the_positive_control(settings, gate):
    result = await run_benchmark(1, settings=settings)
    assert result.ablations[f"without_{gate}"]["positive_controls_lost"] == []


async def test_offline_replay_reproduces_the_live_verdicts(settings):
    """A policy replayed over stored metrics must reproduce the original decision."""
    from bioforge.adapters.registry import AdapterRegistry
    from bioforge.engine.audit import EventBus
    from bioforge.engine.workflow import WorkflowRunner
    from bioforge.models import TargetProductProfile
    from bioforge.store import Store
    from tests.conftest import DEMO_TARGET

    policy = load_policy()
    runner = WorkflowRunner(
        Store("sqlite:///:memory:"), EventBus(), AdapterRegistry.build(settings), settings, policy
    )
    inv = runner.create(DEMO_TARGET, TargetProductProfile(max_candidates=16, max_finalists=3))
    inv = await runner.run_all(inv.id)

    replayed = rerun_offline(policy, inv)
    original = {c.id: (c.status, c.rank, c.rank_score) for c in inv.candidates}
    for candidate in replayed:
        assert original[candidate.id] == (
            candidate.status,
            candidate.rank,
            candidate.rank_score,
        ), f"{candidate.id} did not replay identically"


async def test_single_model_baseline_reports_its_method(settings):
    result = await run_benchmark(1, settings=settings)
    baseline = single_model_baseline
    assert baseline is not None
    assert "interface_confidence" in result.ablations["_single_model_score"]["method"]
