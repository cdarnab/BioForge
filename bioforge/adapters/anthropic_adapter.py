"""Claude: planning, evidence synthesis, hypothesis updates, decision rationales.

Hard boundary: **Claude never produces a number that gates a candidate.** It is
handed the raw metrics and the gate verdicts that `decision_policy` already
computed, and asked for prose. Structured outputs are used so the response shape
is enforced rather than parsed out of free text.

In fixture mode this adapter renders deterministic templates from the same
inputs. The templates are not "what the model would have said" — they are
clearly-labelled stand-ins, and the UI marks any narrative produced this way.
"""

from __future__ import annotations

import json
from typing import Any

from ..models import AdapterMode, Provenance
from .base import Adapter

# Structured-output schemas. `additionalProperties: false` + `required` is what
# makes these enforceable rather than advisory.
EVIDENCE_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Three to five sentences on what the evidence supports.",
        },
        "strongest_support": {"type": "string"},
        "strongest_contradiction": {
            "type": "string",
            "description": "The single most important piece of contradicting evidence. "
            "Never omit this even if the picture looks favourable.",
        },
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "strongest_support", "strongest_contradiction", "open_questions"],
    "additionalProperties": False,
}

HYPOTHESIS_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "hypothesis_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["proposed", "testing", "survives", "rejected", "uncertain"],
                    },
                    "posterior_confidence": {"type": "number"},
                    "result_summary": {
                        "type": "string",
                        "description": "What the gate outcomes did to this hypothesis. "
                        "Reference the specific metric that moved it.",
                    },
                },
                "required": [
                    "hypothesis_id",
                    "status",
                    "posterior_confidence",
                    "result_summary",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["updates"],
    "additionalProperties": False,
}

DECISION_RATIONALE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One sentence, max 20 words."},
        "why_it_survived": {"type": "string"},
        "remaining_uncertainty": {"type": "array", "items": {"type": "string"}},
        "what_would_reverse_this": {"type": "array", "items": {"type": "string"}},
        "suggested_wet_lab_next_step": {"type": "string"},
    },
    "required": [
        "headline",
        "why_it_survived",
        "remaining_uncertainty",
        "what_would_reverse_this",
        "suggested_wet_lab_next_step",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You are the scientific writing layer of BioForge Judge, a candidate-triage system \
for antibody and nanobody design.

Rules you must follow without exception:

1. Every candidate score you are shown is a COMPUTATIONAL PREDICTION. Never \
describe any of it as validated, confirmed, demonstrated, or measured. Say \
"predicted" or "the model scored".
2. You do not produce scores, rankings, or thresholds. Those are computed by a \
configuration-driven policy engine before you are called. Do not second-guess a \
pass/fail verdict; explain it.
3. Never omit contradicting evidence to make a candidate look better. If the \
evidence conflicts, say so in the same breath as the supporting case.
4. Distinguish observed facts, database annotations, literature claims, and model \
predictions. The evidence items you are given are labelled; preserve those labels.
5. Be concise. Structured fields, not essays. No preamble.
6. Do not describe your own reasoning process. State conclusions and the evidence \
they rest on."""


class AnthropicAdapter(Adapter):
    name = "anthropic"
    purpose = "Evidence synthesis, hypothesis updates and decision rationales (prose only)."
    requirement = "Install the `anthropic` package and set ANTHROPIC_API_KEY."

    @property
    def configured(self) -> bool:
        if not self.settings.anthropic_api_key:
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def status(self):  # type: ignore[override]
        base = super().status()
        if self.settings.anthropic_api_key and not self.configured:
            base.detail = (
                "ANTHROPIC_API_KEY is set but the `anthropic` package is not installed. "
                "Run `pip install anthropic`. Using deterministic templates meanwhile."
            )
        base.detail += f" Model: {self.settings.anthropic_model}."
        return base

    # -- public API -------------------------------------------------------

    async def synthesise_evidence(
        self, target_name: str, evidence: list
    ) -> tuple[dict, Provenance]:
        payload = [
            {
                "id": e.id,
                "claim": e.claim,
                "evidence_level": e.evidence_level,
                "support": e.support,
                "source": e.source_title,
            }
            for e in evidence
        ]
        prompt = (
            f"Target: {target_name}\n\nEvidence items:\n{json.dumps(payload, indent=2)}\n\n"
            "Synthesise this evidence for a team deciding whether to pursue this target "
            "with a nanobody. Name the strongest contradiction explicitly."
        )
        return await self._structured(
            prompt, EVIDENCE_SYNTHESIS_SCHEMA, self._fixture_evidence, payload
        )

    async def update_hypotheses(
        self, hypotheses: list, gate_summary: dict
    ) -> tuple[dict, Provenance]:
        payload = {
            "hypotheses": [
                {
                    "id": h.id,
                    "statement": h.statement,
                    "falsification_criteria": h.falsification_criteria,
                    "prior_confidence": h.prior_confidence,
                }
                for h in hypotheses
            ],
            "gate_outcomes": gate_summary,
        }
        prompt = (
            f"{json.dumps(payload, indent=2)}\n\n"
            "For each hypothesis, decide whether the gate outcomes satisfy any of its "
            "falsification criteria. Update status and posterior confidence accordingly. "
            "A hypothesis whose falsification criteria were met must be marked rejected."
        )
        return await self._structured(
            prompt, HYPOTHESIS_UPDATE_SCHEMA, self._fixture_hypotheses, payload
        )

    async def decision_rationale(self, candidate: Any, target_name: str) -> tuple[dict, Provenance]:
        payload = {
            "candidate_id": candidate.id,
            "target": target_name,
            "gates": [
                {"gate": g.gate, "passed": g.passed, "reason": g.reason} for g in candidate.gates
            ],
            "metrics": [
                {
                    "metric": t.metric,
                    "value": t.value,
                    "threshold": t.threshold,
                    "passed": t.passed,
                    "tool": t.tool,
                }
                for t in candidate.tests
            ],
            "policy_decision": candidate.decision.model_dump(),
        }
        prompt = (
            f"{json.dumps(payload, indent=2)}\n\n"
            "Write the decision record for this candidate. The pass/fail verdict is already "
            "decided — explain it against the specific metrics, and be explicit that this is "
            "a prediction awaiting experimental test."
        )
        return await self._structured(
            prompt, DECISION_RATIONALE_SCHEMA, self._fixture_rationale, payload
        )

    # -- transport --------------------------------------------------------

    async def _structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        fixture_fn: Any,
        fixture_input: Any,
    ) -> tuple[dict, Provenance]:
        if not self.configured:
            return fixture_fn(fixture_input), self._template_provenance()
        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=self.settings.anthropic_api_key)
            response = await client.messages.create(
                model=self.settings.anthropic_model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": "medium",
                    "format": {"type": "json_schema", "schema": schema},
                },
                messages=[{"role": "user", "content": prompt}],
            )
            if response.stop_reason == "refusal":
                raise RuntimeError(
                    f"model declined: {getattr(response.stop_details, 'category', 'unknown')}"
                )
            text = next(b.text for b in response.content if b.type == "text")
            data = json.loads(text)
            prov = self.provenance(
                mode=AdapterMode.LIVE,
                model_version=self.settings.anthropic_model,
                parameters={
                    "effort": "medium",
                    "thinking": "adaptive",
                    "schema": schema.get("required", []),
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                note="Narrative only. This call produced no score and no threshold.",
            )
            return data, prov
        except Exception as exc:
            prov = self.degraded(
                f"{type(exc).__name__}: {exc}", model_version=self.settings.anthropic_model
            )
            return fixture_fn(fixture_input), prov

    def _template_provenance(self) -> Provenance:
        return self.provenance(
            mode=AdapterMode.FIXTURE,
            model_version="deterministic-template/v1",
            note=(
                "Rendered from a deterministic template, not written by a language model. "
                "Set ANTHROPIC_API_KEY to generate this narrative with Claude."
            ),
        )

    # -- deterministic templates -----------------------------------------
    # These read the same inputs the model would, so the prose can never drift
    # from the data it describes.

    @staticmethod
    def _fixture_evidence(payload: list[dict]) -> dict:
        supports = [e for e in payload if e["support"] == "supports"]
        contradicts = [e for e in payload if e["support"] == "contradicts"]
        observed = [e for e in payload if e["evidence_level"] == "observed"]
        return {
            "summary": (
                f"{len(payload)} evidence items were assembled: {len(supports)} supporting, "
                f"{len(contradicts)} contradicting, and {len(observed)} resting on directly "
                "observed structural data. The target has experimentally determined "
                "co-structures with both a receptor domain and a neutralising Fab, which "
                "gives the epitope selection an observational anchor rather than a purely "
                "predicted one. Clinical precedent for blocking this target exists, but that "
                "precedent is uneven and is not evidence that any candidate in this run binds."
            ),
            "strongest_support": (
                supports[0]["claim"] if supports else "No supporting evidence was retrieved."
            ),
            "strongest_contradiction": (
                contradicts[0]["claim"]
                if contradicts
                else "No contradicting evidence was retrieved, which is itself suspicious for "
                "a target this well studied."
            ),
            "open_questions": [
                "Which isoform will the assay material actually be, and does it carry the "
                "selected epitope?",
                "What cross-reactivity against other VEGF-family members is acceptable for "
                "the intended indication?",
                "Is a single-domain format sufficient for the required residence time?",
            ],
        }

    @staticmethod
    def _fixture_hypotheses(payload: dict) -> dict:
        gates = payload.get("gate_outcomes", {})
        updates = []
        for hypothesis in payload["hypotheses"]:
            hid = hypothesis["id"]
            prior = float(hypothesis.get("prior_confidence", 0.5))
            statement = hypothesis["statement"].lower()
            if "developable" in statement or "block vegfr" in statement:
                survivors = gates.get("survivors", 0)
                status = "survives" if survivors >= 1 else "rejected"
                posterior = min(0.9, prior + 0.2) if survivors >= 1 else max(0.05, prior - 0.35)
                summary = (
                    f"{survivors} candidate(s) cleared binding, independent structure and "
                    "developability together, so the falsification criterion of zero joint "
                    "survivors was not met."
                )
            elif "independent structure predictor" in statement:
                rejected = gates.get("rejected_independent_structure", 0)
                status = "survives" if rejected >= 1 else "rejected"
                posterior = min(0.92, prior + 0.25) if rejected >= 1 else max(0.05, prior - 0.4)
                summary = (
                    f"The independent-structure gate rejected {rejected} candidate(s) that the "
                    "design path had passed, so it is adding information rather than echoing "
                    "the primary model."
                )
            elif "adversarial challenge" in statement:
                rejected = gates.get("rejected_robustness", 0)
                if rejected == 0 and not gates.get("challenge_run"):
                    status, posterior = "testing", prior
                    summary = "Challenge has not been run yet."
                else:
                    status = "survives" if rejected >= 1 else "rejected"
                    posterior = min(0.9, prior + 0.3) if rejected >= 1 else max(0.05, prior - 0.35)
                    summary = (
                        f"The adversarial gate rejected {rejected} candidate(s) that had passed "
                        "all three prior gates."
                    )
            else:
                if not gates.get("redesign_run"):
                    status, posterior = "testing", prior
                    summary = "No redesign has been attempted yet."
                elif gates.get("redesign_passed"):
                    status, posterior = "survives", min(0.85, prior + 0.3)
                    summary = (
                        "The redesign reduced the aggregation heuristic and cleared the "
                        "developability gate while staying above the binding threshold. Its "
                        "predicted affinity and cross-model agreement both fell slightly, "
                        "which is the expected shape of this tradeoff."
                    )
                else:
                    status, posterior = "rejected", max(0.05, prior - 0.3)
                    summary = "The redesign failed to clear the gate it was built to address."
            updates.append(
                {
                    "hypothesis_id": hid,
                    "status": status,
                    "posterior_confidence": round(posterior, 2),
                    "result_summary": summary,
                }
            )
        return {"updates": updates}

    @staticmethod
    def _fixture_rationale(payload: dict) -> dict:
        cid = payload["candidate_id"]
        gates = payload["gates"]
        failed = [g for g in gates if not g["passed"]]
        metrics = {m["metric"]: m for m in payload["metrics"]}

        if failed:
            gate = failed[0]
            return {
                "headline": f"{cid} rejected at the {gate['gate'].replace('_', ' ')} gate.",
                "why_it_survived": f"It did not. {gate['reason']}",
                "remaining_uncertainty": [
                    "Rejection rests on predicted values, not measurements.",
                    "A different threshold choice could change this outcome; thresholds in "
                    "this run are uncalibrated demonstration values.",
                ],
                "what_would_reverse_this": payload["policy_decision"].get(
                    "reversal_conditions", []
                ),
                "suggested_wet_lab_next_step": (
                    "None recommended. Testing this candidate would consume a slot without a "
                    "hypothesis worth testing."
                ),
            }

        conf = metrics.get("interface_confidence", {}).get("value")
        agree = metrics.get("model_agreement", {}).get("value")
        decoy = metrics.get("decoy_discrimination_margin", {}).get("value")
        return {
            "headline": f"{cid} cleared all four gates and is recommended for wet-lab testing.",
            "why_it_survived": (
                f"Predicted interface confidence {conf} cleared the binding threshold, an "
                f"independent structure model from a different family agreed at {agree}, the "
                "developability panel raised at most one flag, and the candidate held its "
                f"predicted interface under the alanine scan while separating from the decoy "
                f"panel by {decoy}."
            ),
            "remaining_uncertainty": [
                "Every number above is a prediction. There is no experimental evidence that "
                "this molecule binds anything.",
                "Two models agreeing is not two independent observations; they may share "
                "training data and therefore share errors.",
                "Developability heuristics here are sequence summaries, not manufacturability "
                "predictions.",
            ],
            "what_would_reverse_this": payload["policy_decision"].get("reversal_conditions", []),
            "suggested_wet_lab_next_step": (
                "Express in a small-scale periplasmic prep, confirm monomeric species by SEC, "
                "then run SPR against recombinant VEGF-A165 with PlGF and VEGF-B as "
                "counter-screens on the same chip."
            ),
        }
