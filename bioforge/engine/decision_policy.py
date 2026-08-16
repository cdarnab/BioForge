"""Configuration-driven gate evaluation and ranking.

This module is the only place a candidate is allowed to pass or fail. It reads
`data/policy/gates.yaml`, compares stored raw metrics against the thresholds
there, and emits `GateOutcome` + `Decision` objects with closed-vocabulary
reason codes.

No language model is involved. Given the same `TestResult` list and the same
policy file, this produces the same verdict every time — which is what makes
the dossier reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..config import POLICY_DIR
from ..models import Candidate, Decision, GateOutcome, TestResult

GATE_ORDER = ["binding", "independent_structure", "developability", "robustness"]


@dataclass(frozen=True)
class MetricSpec:
    name: str
    label: str
    direction: str
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    source: str | None = None
    note: str = ""

    def evaluate(self, value: float) -> bool | None:
        """None means informational — the metric is displayed but never gates."""
        if self.direction == "informational":
            return None
        if self.direction == "higher_is_better":
            return self.minimum is None or value >= self.minimum
        if self.direction == "lower_is_better":
            return self.maximum is None or value <= self.maximum
        if self.direction == "in_range":
            lo_ok = self.minimum is None or value >= self.minimum
            hi_ok = self.maximum is None or value <= self.maximum
            return lo_ok and hi_ok
        raise ValueError(f"unknown direction {self.direction!r} for metric {self.name!r}")


@dataclass(frozen=True)
class GateSpec:
    name: str
    title: str
    order: int
    required: bool
    max_failed_metrics: int
    description: str
    metrics: tuple[MetricSpec, ...]

    def metric(self, name: str) -> MetricSpec | None:
        return next((m for m in self.metrics if m.name == name), None)


@dataclass(frozen=True)
class RankComponent:
    metric: str
    weight: float
    direction: str
    floor: float
    ceiling: float

    def normalise(self, value: float) -> float:
        span = self.ceiling - self.floor
        if span <= 0:
            return 0.0
        x = (value - self.floor) / span
        x = min(1.0, max(0.0, x))
        return 1.0 - x if self.direction == "lower_is_better" else x


@dataclass(frozen=True)
class Policy:
    version: str
    label: str
    gates: tuple[GateSpec, ...]
    ranking: tuple[RankComponent, ...]
    ranking_description: str
    reason_codes: dict[str, str]

    def gate(self, name: str) -> GateSpec:
        found = next((g for g in self.gates if g.name == name), None)
        if found is None:
            raise KeyError(f"gate {name!r} is not defined in the policy file")
        return found

    def as_dict(self) -> dict[str, Any]:
        """Serialised form embedded in the dossier so a reader can recompute."""
        return {
            "version": self.version,
            "label": self.label,
            "ranking_description": self.ranking_description,
            "gates": [
                {
                    "name": g.name,
                    "title": g.title,
                    "required": g.required,
                    "max_failed_metrics": g.max_failed_metrics,
                    "description": g.description.strip(),
                    "metrics": [
                        {
                            "name": m.name,
                            "label": m.label,
                            "direction": m.direction,
                            "unit": m.unit,
                            "minimum": m.minimum,
                            "maximum": m.maximum,
                            "source": m.source,
                            "note": m.note.strip(),
                            "calibrated": m.source is not None,
                        }
                        for m in g.metrics
                    ],
                }
                for g in self.gates
            ],
            "ranking": [
                {
                    "metric": c.metric,
                    "weight": c.weight,
                    "direction": c.direction,
                    "floor": c.floor,
                    "ceiling": c.ceiling,
                }
                for c in self.ranking
            ],
            "reason_codes": self.reason_codes,
        }


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=4)
def load_policy(path: str | None = None) -> Policy:
    target = Path(path) if path else POLICY_DIR / "gates.yaml"
    raw = _load_yaml(target)

    gates: list[GateSpec] = []
    for name, body in raw["gates"].items():
        metrics = tuple(
            MetricSpec(
                name=m["name"],
                label=m.get("label", m["name"]),
                direction=m["direction"],
                unit=m.get("unit", "") or "",
                minimum=m.get("minimum"),
                maximum=m.get("maximum"),
                source=m.get("source"),
                note=(m.get("note") or "").strip(),
            )
            for m in body["metrics"]
        )
        gates.append(
            GateSpec(
                name=name,
                title=body.get("title", name),
                order=int(body.get("order", 99)),
                required=bool(body.get("required", True)),
                max_failed_metrics=int(body.get("max_failed_metrics", 0)),
                description=(body.get("description") or "").strip(),
                metrics=metrics,
            )
        )
    gates.sort(key=lambda g: g.order)

    ranking = tuple(
        RankComponent(
            metric=c["metric"],
            weight=float(c["weight"]),
            direction=c["direction"],
            floor=float(c["floor"]),
            ceiling=float(c["ceiling"]),
        )
        for c in raw["ranking"]["components"]
    )

    return Policy(
        version=str(raw["version"]),
        label=str(raw.get("label", "")),
        gates=tuple(gates),
        ranking=ranking,
        ranking_description=(raw["ranking"].get("description") or "").strip(),
        reason_codes=dict(raw.get("reason_codes", {})),
    )


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

# Maps a failing metric to the reason code the decision engine emits.
_METRIC_REASON: dict[str, str] = {
    "interface_confidence": "BIND_LOW_CONFIDENCE",
    "model_agreement": "STRUCT_DISAGREEMENT",
    "epitope_rmsd_angstrom": "STRUCT_POSE_SHIFT",
    "retained_score_across_mutations": "ROBUST_MUTATION_FRAGILE",
    "decoy_discrimination_margin": "ROBUST_DECOY_BINDING",
}


def apply_thresholds(policy: Policy, tests: list[TestResult]) -> None:
    """Stamp `passed`/`threshold`/`direction` onto raw results, in place.

    Adapters report raw numbers only. The pass/fail judgement is added here so
    that changing the policy file and re-running reproduces the verdict from
    the same stored measurements.
    """
    known = {g.name for g in policy.gates}
    for test in tests:
        # A gate can be absent when running an ablation. Its metrics stay
        # visible but stop gating, which is exactly what the ablation means.
        spec = policy.gate(test.gate).metric(test.metric) if test.gate in known else None
        if spec is None:
            # Metric an adapter reported that the policy does not know about.
            # Keep it visible, but it can never gate.
            test.direction = "informational"
            test.passed = None
            test.rationale = test.rationale or "No policy entry; reported for context only."
            continue
        test.direction = spec.direction  # type: ignore[assignment]
        test.unit = test.unit or spec.unit
        test.threshold = spec.minimum if spec.direction != "lower_is_better" else spec.maximum
        test.threshold_high = spec.maximum if spec.direction == "in_range" else None
        test.passed = spec.evaluate(test.value)
        if not test.rationale:
            test.rationale = _describe(spec, test.value, test.passed)


def _describe(spec: MetricSpec, value: float, passed: bool | None) -> str:
    if passed is None:
        return "Informational metric; no threshold applied."
    if spec.direction == "higher_is_better":
        rel = "at or above" if passed else "below"
        return f"{value:g} is {rel} the minimum of {spec.minimum:g}."
    if spec.direction == "lower_is_better":
        rel = "at or below" if passed else "above"
        return f"{value:g} is {rel} the maximum of {spec.maximum:g}."
    inside = "within" if passed else "outside"
    return f"{value:g} is {inside} the accepted range {spec.minimum:g} to {spec.maximum:g}."


def evaluate_gate(policy: Policy, gate_name: str, tests: list[TestResult]) -> GateOutcome:
    spec = policy.gate(gate_name)
    relevant = [t for t in tests if t.gate == gate_name and t.passed is not None]
    failed = [t.metric for t in relevant if t.passed is False]
    passed_metrics = [t.metric for t in relevant if t.passed is True]

    if not relevant:
        return GateOutcome(
            gate=gate_name,  # type: ignore[arg-type]
            passed=False,
            required=spec.required,
            reason="Gate has not been run yet.",
        )

    ok = len(failed) <= spec.max_failed_metrics
    if ok:
        reason = (
            f"{len(passed_metrics)}/{len(relevant)} metrics within thresholds."
            if not failed
            else (
                f"{len(failed)} flagged metric(s) ({', '.join(failed)}), within the "
                f"tolerance of {spec.max_failed_metrics}."
            )
        )
    else:
        reason = (
            f"{len(failed)} metric(s) outside thresholds ({', '.join(failed)}); "
            f"tolerance is {spec.max_failed_metrics}."
        )

    return GateOutcome(
        gate=gate_name,  # type: ignore[arg-type]
        passed=ok,
        required=spec.required,
        metrics_failed=failed,
        metrics_passed=passed_metrics,
        reason=reason,
    )


def reason_codes_for(policy: Policy, outcome: GateOutcome) -> list[str]:
    if outcome.passed:
        return []
    if outcome.gate == "developability":
        return ["DEV_MULTIPLE_LIABILITIES"]
    codes = [_METRIC_REASON[m] for m in outcome.metrics_failed if m in _METRIC_REASON]
    return codes or ["DEV_MULTIPLE_LIABILITIES"]


def compute_rank_score(policy: Policy, candidate: Candidate) -> tuple[float | None, list[dict]]:
    """Transparent weighted sum. Returns the score and its full working."""
    breakdown: list[dict] = []
    total = 0.0
    total_weight = 0.0
    for component in policy.ranking:
        test = candidate.metric(component.metric)
        if test is None:
            continue
        normalised = component.normalise(test.value)
        contribution = normalised * component.weight
        total += contribution
        total_weight += component.weight
        breakdown.append(
            {
                "metric": component.metric,
                "raw_value": test.value,
                "normalised": round(normalised, 4),
                "weight": component.weight,
                "contribution": round(contribution, 4),
            }
        )
    if total_weight == 0:
        return None, breakdown
    return round(total / total_weight, 4), breakdown


def evaluate_candidate(
    policy: Policy,
    candidate: Candidate,
    gates_to_run: list[str] | None = None,
) -> Candidate:
    """Run every gate that has data, then set the candidate's decision."""
    apply_thresholds(policy, candidate.tests)
    active_gates = [g.name for g in policy.gates]
    gates_to_run = [
        g
        for g in (
            gates_to_run or [g for g in active_gates if any(t.gate == g for t in candidate.tests)]
        )
        if g in active_gates
    ]

    outcomes: list[GateOutcome] = []
    for name in active_gates:
        if name not in gates_to_run:
            existing = candidate.gate(name)
            if existing:
                outcomes.append(existing)
            continue
        outcomes.append(evaluate_gate(policy, name, candidate.tests))
    candidate.gates = outcomes

    first_failure = next((o for o in outcomes if o.required and not o.passed), None)
    if first_failure is not None:
        codes = reason_codes_for(policy, first_failure)
        candidate.status = "rejected"
        candidate.decision = Decision(
            outcome="reject",
            reason_codes=codes,
            summary=f"Rejected at the {policy.gate(first_failure.gate).title.lower()} gate. "
            + first_failure.reason,
            uncertainties=_uncertainties(candidate, first_failure),
            reversal_conditions=_reversal_conditions(first_failure),
            policy_version=policy.version,
        )
        candidate.rank_score, _ = compute_rank_score(policy, candidate)
        return candidate

    ran = [o for o in outcomes if o.gate in gates_to_run]
    all_gates_passed = len([o for o in outcomes if o.passed]) == len(active_gates)
    candidate.rank_score, breakdown = compute_rank_score(policy, candidate)

    if all_gates_passed:
        candidate.status = "survives"
        candidate.decision = Decision(
            outcome="advance",
            reason_codes=["ADVANCED_ALL_GATES"],
            summary=f"Passed all {len(active_gates)} configured gates. "
            + "; ".join(f"{o.gate}: {o.reason}" for o in outcomes),
            uncertainties=_uncertainties(candidate, None),
            reversal_conditions=[
                "A wet-lab binding assay showing no measurable affinity to VEGF-A.",
                "An experimentally determined structure placing the paratope away from the "
                "receptor-binding region.",
                "Expression or SEC data showing aggregation despite the predicted profile.",
            ],
            policy_version=policy.version,
        )
    else:
        candidate.status = "active"
        candidate.decision = Decision(
            outcome="pending",
            reason_codes=[],
            summary="Passed "
            + ", ".join(o.gate for o in ran if o.passed)
            + "; remaining gates not yet run.",
            policy_version=policy.version,
        )
    _ = breakdown
    return candidate


def _uncertainties(candidate: Candidate, failure: GateOutcome | None) -> list[str]:
    out: list[str] = [
        "Every score on this candidate is a computational prediction. None of it is "
        "experimental evidence of binding.",
    ]
    missing_uncertainty = [
        t.metric for t in candidate.tests if t.uncertainty is None and t.passed is not None
    ]
    if missing_uncertainty:
        out.append(
            "No uncertainty estimate was reported for: "
            + ", ".join(sorted(set(missing_uncertainty)))
            + "."
        )
    for test in candidate.tests:
        if test.uncertainty is not None and test.threshold is not None and test.passed is not None:
            margin = abs(test.value - test.threshold)
            if margin < test.uncertainty:
                out.append(
                    f"{test.metric} sits {margin:.3f} from its threshold, inside the reported "
                    f"uncertainty of ±{test.uncertainty:.3f} — this call could flip."
                )
    if failure is not None and failure.gate == "developability":
        out.append(
            "Developability heuristics here are sequence-derived summaries, not validated "
            "predictors of manufacturability."
        )
    return out


def _reversal_conditions(failure: GateOutcome) -> list[str]:
    by_gate = {
        "binding": [
            "A measured binding affinity (SPR/BLI) below 100 nM would overturn this rejection.",
            "A co-structure showing the designed interface would overturn the low confidence call.",
        ],
        "independent_structure": [
            "A third independent structure predictor agreeing with the design-path pose.",
            "An experimental structure matching either predicted pose.",
        ],
        "developability": [
            "Expression and SEC data showing monomeric, well-behaved protein despite the "
            "flagged liabilities.",
            "A DSF melting curve above the configured threshold.",
        ],
        "robustness": [
            "Alanine-scan-equivalent mutational data showing the interface tolerates the "
            "substitutions this scan penalised.",
            "Measured selectivity against the decoy antigen panel.",
        ],
    }
    return by_gate.get(
        failure.gate, ["New experimental evidence contradicting the failing metric."]
    )


def shortlist(policy: Policy, candidates: list[Candidate], max_finalists: int) -> list[Candidate]:
    """Order survivors by the transparent rank score and mark the finalists."""
    survivors = [c for c in candidates if c.status in ("survives", "recommended")]
    survivors.sort(key=lambda c: (-(c.rank_score or 0.0), c.id))

    for index, candidate in enumerate(survivors, start=1):
        candidate.rank = index
        if index <= max_finalists:
            candidate.status = "recommended"
            candidate.decision.outcome = "recommend"
            if "ADVANCED_ALL_GATES" not in candidate.decision.reason_codes:
                candidate.decision.reason_codes.append("ADVANCED_ALL_GATES")
        else:
            candidate.status = "survives"
            candidate.decision.outcome = "advance"
            if "NOT_SHORTLISTED" not in candidate.decision.reason_codes:
                candidate.decision.reason_codes.append("NOT_SHORTLISTED")
            candidate.decision.summary += (
                f" Ranked #{index} by the published ranking function, below the "
                f"finalist cutoff of {max_finalists}."
            )
    return survivors


def pick_redesign_target(policy: Policy, candidates: list[Candidate]) -> Candidate | None:
    """Choose the near-miss: the rejected candidate closest to passing.

    "Closest" is defined as the smallest normalised distance past a threshold,
    among candidates that failed exactly one gate. Deterministic and explainable.
    """
    best: tuple[float, Candidate] | None = None
    for candidate in candidates:
        if candidate.status != "rejected":
            continue
        failed_gates = [g for g in candidate.gates if not g.passed]
        if len(failed_gates) != 1:
            continue
        distance = _threshold_distance(candidate, failed_gates[0])
        if distance is None:
            continue
        if best is None or distance < best[0]:
            best = (distance, candidate)
    return best[1] if best else None


def _threshold_distance(candidate: Candidate, gate: GateOutcome) -> float | None:
    """Mean fractional distance past threshold over the gate's failing metrics."""
    distances: list[float] = []
    for metric_name in gate.metrics_failed:
        test = candidate.metric(metric_name)
        if test is None or test.threshold is None:
            continue
        scale = abs(test.threshold) or 1.0
        distances.append(abs(test.value - test.threshold) / scale)
    if not distances:
        return None
    return sum(distances) / len(distances)
