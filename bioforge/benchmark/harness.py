"""Retrospective benchmark harness.

Runs the pipeline blind, then joins the ground-truth control labels back in
afterwards and asks whether the system ranked the positive control above the
negatives.

Blinding is structural, not a promise: the scoring path has no access to
`benchmark_labels.json`. This module is the only non-test consumer of it, and
`tests/unit/test_blinding.py` enforces that by scanning imports.

What this measures and what it does not: it measures whether the *harness*
recovers labels that were assigned in the fixture file. It does not measure
whether the underlying scores are biophysically correct — the fixture scores
were authored, so a good result here says the plumbing works, not that the
science does. See docs/scientific-limitations.md.
"""

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ..adapters.fixtures import benchmark_labels
from ..adapters.registry import AdapterRegistry
from ..config import Settings
from ..engine.audit import EventBus
from ..engine.decision_policy import (
    Policy,
    evaluate_candidate,
    load_policy,
    shortlist,
)
from ..engine.workflow import WorkflowRunner
from ..models import Candidate, Investigation, Target, TargetProductProfile
from ..store import Store

# Published list prices, USD per million tokens. Only used when a live Claude
# call actually happened; fixture runs report zero and say so.
PRICE_PER_MTOK = {"claude-opus-5": (5.0, 25.0), "claude-sonnet-5": (3.0, 15.0)}

STATUS_ORDER = {"recommended": 0, "survives": 1, "active": 2, "rejected": 3}


@dataclass
class BenchmarkResult:
    seed: int
    runtime_seconds: float
    run_id: str
    ranking: list[str]
    positive_control_rank: int | None
    negative_control_ranks: dict[str, int]
    top_k_enrichment: dict[int, float]
    auroc: float | None
    gate_rejections: dict[str, list[str]]
    model_agreement: dict[str, float]
    shortlist: list[str]
    approximate_cost_usd: float
    cost_note: str
    ablations: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "run_id": self.run_id,
            "runtime_seconds": round(self.runtime_seconds, 3),
            "ranking": self.ranking,
            "positive_control_rank": self.positive_control_rank,
            "negative_control_ranks": self.negative_control_ranks,
            "top_k_enrichment": {str(k): v for k, v in self.top_k_enrichment.items()},
            "auroc": self.auroc,
            "gate_rejections": {k: sorted(v) for k, v in self.gate_rejections.items()},
            "model_agreement": self.model_agreement,
            "shortlist": self.shortlist,
            "approximate_cost_usd": self.approximate_cost_usd,
            "cost_note": self.cost_note,
            "ablations": self.ablations,
        }


# --------------------------------------------------------------------------
# Scoring helpers (blind — no label access)
# --------------------------------------------------------------------------


def _discriminative_score(candidate: Candidate) -> float:
    """A single comparable number per candidate for ranking-quality metrics.

    Uses the transparent rank score where the candidate has enough metrics for
    one, and falls back to predicted interface confidence (the only metric every
    candidate has) otherwise. Candidates rejected early necessarily score lower
    because they never accrued the later terms — which is the pipeline's actual
    behaviour, so measuring it is the point.
    """
    if candidate.rank_score is not None and len(candidate.tests) > 4:
        return candidate.rank_score
    binding = candidate.metric("interface_confidence")
    return binding.value if binding else 0.0


def rank_candidates(investigation: Investigation) -> list[Candidate]:
    return sorted(
        investigation.candidates,
        key=lambda c: (
            STATUS_ORDER.get(c.status, 4),
            c.rank if c.rank is not None else 99,
            -_discriminative_score(c),
            c.id,
        ),
    )


def auroc(positives: list[float], negatives: list[float]) -> float | None:
    """Mann-Whitney U / (n_pos * n_neg). Ties count a half."""
    if not positives or not negatives:
        return None
    wins = 0.0
    for p in positives:
        for n in negatives:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return round(wins / (len(positives) * len(negatives)), 4)


# --------------------------------------------------------------------------
# Ablations
# --------------------------------------------------------------------------


def ablate(policy: Policy, drop: str) -> Policy:
    """A copy of the policy with one gate removed. Ranking is left untouched."""
    gates = tuple(g for g in policy.gates if g.name != drop)
    return Policy(
        version=f"{policy.version}+ablate:{drop}",
        label=f"{policy.label} (ablation: {drop} removed)",
        gates=gates,
        ranking=policy.ranking,
        ranking_description=policy.ranking_description,
        reason_codes=policy.reason_codes,
    )


def rerun_offline(policy: Policy, investigation: Investigation) -> list[Candidate]:
    """Re-decide every candidate from its stored raw metrics under a policy.

    This is the property that makes the ablations real rather than illustrative:
    the metrics were measured once, and any policy can be replayed over them.
    """
    candidates = deepcopy(investigation.candidates)
    for candidate in candidates:
        candidate.gates = []
        candidate.rank = None
        evaluate_candidate(policy, candidate)
    shortlist(policy, candidates, investigation.target_product_profile.max_finalists)
    return candidates


def single_model_baseline(investigation: Investigation, k: int) -> dict[str, Any]:
    """What you would ship if you ranked on the design model's score alone.

    This is the comparison the product exists to beat: no independent check, no
    developability panel, no adversarial challenge — just the primary model's
    predicted interface confidence, top-k.
    """
    scored = [
        (c.id, c.metric("interface_confidence").value)  # type: ignore[union-attr]
        for c in investigation.candidates
        if c.metric("interface_confidence") is not None
    ]
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    picked = [cid for cid, _ in scored[:k]]

    rejected_by_pipeline = {}
    for cid in picked:
        candidate = investigation.candidate(cid)
        if candidate is None or candidate.status != "rejected":
            continue
        failed = next((g for g in candidate.gates if not g.passed), None)
        rejected_by_pipeline[cid] = {
            "gate": failed.gate if failed else "unknown",
            "metrics_failed": failed.metrics_failed if failed else [],
            "reason_codes": candidate.decision.reason_codes,
        }

    return {
        "method": "rank by predicted interface_confidence only, take top-k",
        "shortlist": picked,
        "scores": {cid: value for cid, value in scored[:k]},
        "picks_the_full_pipeline_rejected": rejected_by_pipeline,
        "note": (
            "Any candidate listed under picks_the_full_pipeline_rejected would have gone to "
            "the bench on a single-model score and been caught only by an experiment."
        ),
    }


def run_ablations(policy: Policy, investigation: Investigation) -> dict[str, dict[str, Any]]:
    labels = benchmark_labels()
    positives = set(labels["expected_positive"])
    negatives = set(labels["expected_negative"])
    baseline = [c.id for c in investigation.candidates if c.status == "recommended"]
    baseline_rejected = {c.id for c in investigation.candidates if c.status == "rejected"}

    out: dict[str, dict[str, Any]] = {}
    for gate in ("independent_structure", "developability", "robustness"):
        reduced = ablate(policy, gate)
        candidates = rerun_offline(reduced, investigation)
        picked = [c.id for c in candidates if c.status == "recommended"]
        promoted = [cid for cid in picked if cid not in baseline]
        # The more important number than "did the top-3 change" is how many
        # candidates the full policy caught that this one lets through.
        escaped = sorted(
            c.id for c in candidates if c.status != "rejected" and c.id in baseline_rejected
        )
        out[f"without_{gate}"] = {
            "gates_remaining": [g.name for g in reduced.gates],
            "shortlist": picked,
            "shortlist_changed": picked != baseline,
            "newly_promoted": promoted,
            "dropped_from_shortlist": [cid for cid in baseline if cid not in picked],
            "escaped_rejection": escaped,
            "negative_controls_promoted": sorted(set(escaped) & negatives),
            "positive_controls_lost": sorted(positives - set(picked)),
            "total_rejected": sum(1 for c in candidates if c.status == "rejected"),
        }

    out["_baseline"] = {
        "gates_remaining": [g.name for g in policy.gates],
        "shortlist": baseline,
        "total_rejected": len(baseline_rejected),
    }
    out["_single_model_score"] = single_model_baseline(
        investigation, investigation.target_product_profile.max_finalists
    )
    return out


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _cost(store: Store, run_id: str) -> tuple[float, str]:
    total = 0.0
    live_calls = 0
    for event in store.events(run_id):
        params = event.parameters or {}
        if "input_tokens" not in params:
            continue
        live_calls += 1
        model = event.model_version or ""
        rates = PRICE_PER_MTOK.get(model)
        if rates is None:
            continue
        total += params.get("input_tokens", 0) / 1e6 * rates[0]
        total += params.get("output_tokens", 0) / 1e6 * rates[1]
    if live_calls == 0:
        return 0.0, (
            "No live model calls were made — every adapter ran in fixture or "
            "import-handoff mode, so API cost is zero. Compute cost is one process, "
            "no GPU."
        )
    return round(total, 6), f"{live_calls} live model call(s), priced at published list rates."


async def run_benchmark(
    seed: int,
    *,
    settings: Settings,
    database_url: str = "sqlite:///:memory:",
    include_ablations: bool = True,
) -> BenchmarkResult:
    from ..api.main import DEMO_TARGET  # local import to avoid a cycle at module load

    started = time.monotonic()
    store = Store(database_url)
    registry = AdapterRegistry.build(settings)
    policy = load_policy()
    runner = WorkflowRunner(store, EventBus(), registry, settings, policy)

    target = Target(**DEMO_TARGET.model_dump())
    investigation = runner.create(
        target,
        TargetProductProfile(format="nanobody", max_candidates=16, max_finalists=3),
        mode="fixture",
        seed=seed,
    )
    investigation = await runner.run_all(investigation.id)
    runtime = time.monotonic() - started

    # ---- labels are joined only from here down --------------------------
    labels = benchmark_labels()
    positives = set(labels["expected_positive"])
    negatives = set(labels["expected_negative"])

    ordered = rank_candidates(investigation)
    ranking = [c.id for c in ordered]
    positions = {cid: index + 1 for index, cid in enumerate(ranking)}

    positive_rank = next((positions[p] for p in positives if p in positions), None)
    negative_ranks = {n: positions[n] for n in sorted(negatives) if n in positions}

    scores = {c.id: _discriminative_score(c) for c in ordered}
    enrichment: dict[int, float] = {}
    base_rate = len(positives) / len(ranking) if ranking else 0.0
    for k in (1, 3, 5):
        top = set(ranking[:k])
        hit_rate = len(top & positives) / k
        enrichment[k] = round(hit_rate / base_rate, 3) if base_rate else 0.0

    area = auroc(
        [scores[p] for p in positives if p in scores],
        [scores[n] for n in negatives if n in scores],
    )

    gate_rejections: dict[str, list[str]] = {}
    for candidate in investigation.candidates:
        failed = next((g.gate for g in candidate.gates if not g.passed), None)
        if failed:
            gate_rejections.setdefault(failed, []).append(candidate.id)

    agreement = {
        c.id: c.metric("model_agreement").value  # type: ignore[union-attr]
        for c in investigation.candidates
        if c.metric("model_agreement") is not None
    }

    cost, cost_note = _cost(store, investigation.id)

    return BenchmarkResult(
        seed=seed,
        run_id=investigation.id,
        runtime_seconds=runtime,
        ranking=ranking,
        positive_control_rank=positive_rank,
        negative_control_ranks=negative_ranks,
        top_k_enrichment=enrichment,
        auroc=area,
        gate_rejections=gate_rejections,
        model_agreement=agreement,
        shortlist=[c.id for c in investigation.finalists()],
        approximate_cost_usd=cost,
        cost_note=cost_note,
        ablations=run_ablations(policy, investigation) if include_ablations else {},
    )
