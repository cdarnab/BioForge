"""The workflow runner.

Drives an `Investigation` through the state machine, calling adapters, handing
their raw numbers to the decision policy, and writing an audit event for every
step. Nothing here decides a pass or a fail — that is `decision_policy`'s job —
and nothing here asks a model for a score.

The run pauses after INDEPENDENT_VALIDATION. Advancing past that point requires
a human to press Challenge Survivors, because the adversarial gate is the claim
the product is making and a person should be the one to invoke it.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ..adapters.modal_adapter import DECOY_PANEL
from ..adapters.registry import AdapterRegistry
from ..biophysics import METRIC_KIND
from ..config import Settings
from ..ids import reset_ids
from ..models import (
    AdapterMode,
    Artifact,
    Candidate,
    Hypothesis,
    Investigation,
    Provenance,
    Target,
    TargetProductProfile,
    TestResult,
    WorkflowState,
    utcnow,
)
from ..store import Store
from . import packaging
from .audit import Auditor, EventBus
from .decision_policy import (
    GATE_ORDER,
    Policy,
    evaluate_candidate,
    load_policy,
    pick_redesign_target,
    shortlist,
)
from .state_machine import assert_transition, progress_fraction

METRIC_GATE: dict[str, str] = {
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

# Metrics for which the fixture/live tools report a spread. Anything absent from
# this map surfaces as "no uncertainty reported", which the decision record says
# out loud rather than implying the estimate is exact.
METRIC_UNCERTAINTY: dict[str, float] = {
    "interface_confidence": 0.06,
    "model_agreement": 0.08,
    "epitope_rmsd_angstrom": 0.9,
    "predicted_tm_celsius": 3.5,
    "immunogenicity_risk": 0.07,
    "retained_score_across_mutations": 0.07,
    "decoy_discrimination_margin": 0.05,
}


class WorkflowRunner:
    def __init__(
        self,
        store: Store,
        bus: EventBus,
        registry: AdapterRegistry,
        settings: Settings,
        policy: Policy | None = None,
    ) -> None:
        self.store = store
        self.bus = bus
        self.registry = registry
        self.settings = settings
        self.policy = policy or load_policy()

    # -- helpers ----------------------------------------------------------

    def auditor(self, run_id: str) -> Auditor:
        return Auditor(self.store, self.bus, run_id)

    async def _pace(self, multiplier: float = 1.0) -> None:
        ms = self.settings.demo_pace_ms * multiplier
        if ms > 0:
            await asyncio.sleep(ms / 1000.0)

    def _save(self, inv: Investigation) -> None:
        inv.updated_at = utcnow()
        self.store.save(inv)
        self.bus.publish(
            inv.id,
            {
                "type": "investigation",
                "status": inv.status.value,
                "status_detail": inv.status_detail,
                "progress": progress_fraction(inv.status),
                "counts": self._counts(inv),
            },
        )

    @staticmethod
    def _counts(inv: Investigation) -> dict[str, int]:
        return {
            "evidence": len(inv.evidence),
            "hypotheses": len(inv.hypotheses),
            "candidates": len(inv.candidates),
            "rejected": sum(1 for c in inv.candidates if c.status == "rejected"),
            "surviving": sum(1 for c in inv.candidates if c.status in ("survives", "recommended")),
            "recommended": sum(1 for c in inv.candidates if c.status == "recommended"),
        }

    def _goto(
        self,
        inv: Investigation,
        state: WorkflowState,
        summary: str,
        *,
        detail: str = "",
        actor: str = "system",
    ) -> None:
        assert_transition(inv.status, state)
        prev = inv.status
        inv.status = state
        inv.status_detail = detail or summary
        self.auditor(inv.id).record(
            "state_transition", summary, prev_state=prev, next_state=state, actor=actor
        )
        self._save(inv)

    def _push_candidate(self, inv: Investigation, candidate: Candidate) -> None:
        self.bus.publish(
            inv.id,
            {"type": "candidate", "candidate": candidate.model_dump(mode="json")},
        )

    def _make_test(
        self,
        metric: str,
        value: float,
        tool: str,
        provenance: Provenance,
        artifact_ids: list[str] | None = None,
    ) -> TestResult:
        return TestResult(
            gate=METRIC_GATE[metric],  # type: ignore[arg-type]
            metric=metric,
            value=float(value),
            direction="informational",  # overwritten by apply_thresholds
            tool=tool,
            model_version=provenance.model_version,
            uncertainty=METRIC_UNCERTAINTY.get(metric),
            artifact_ids=artifact_ids or [],
            provenance=provenance,
        )

    def _artifact(
        self,
        inv: Investigation,
        kind: str,
        filename: str,
        content: str,
        media_type: str,
        description: str,
        provenance: Provenance | None = None,
    ) -> Artifact:
        artifact = Artifact(
            id=f"{inv.id}-art-{len(inv.artifacts) + 1:03d}",
            run_id=inv.id,
            kind=kind,  # type: ignore[arg-type]
            filename=filename,
            media_type=media_type,
            size_bytes=len(content.encode("utf-8")),
            description=description,
            provenance=provenance,
        )
        self.store.put_artifact(artifact, content)
        inv.artifacts.append(artifact)
        return artifact

    # -- creation ---------------------------------------------------------

    def create(
        self,
        target: Target,
        profile: TargetProductProfile,
        mode: str = "fixture",
        seed: int | None = None,
    ) -> Investigation:
        # Per-run reset keeps evidence/hypothesis ids stable between identical
        # runs. Those ids live inside the run's own JSON blob, so resetting them
        # cannot collide with another run. Ids that share a table across runs
        # (audit events, artifacts) are namespaced by run id instead.
        reset_ids()
        inv = Investigation(
            id=self.store.next_run_id(),
            target=target,
            target_product_profile=profile,
            mode="live" if mode == "live" else "fixture",
            seed=seed if seed is not None else self.settings.random_seed,
            policy_version=self.policy.version,
            integrations=self.registry.statuses(),
        )
        self.store.save(inv)
        self.auditor(inv.id).record(
            "state_transition",
            f"Investigation created for {target.name}.",
            next_state=WorkflowState.CREATED,
            actor="human",
            parameters={
                "target": target.name,
                "epitope": target.epitope_description,
                "format": profile.format,
                "seed": inv.seed,
                "policy_version": self.policy.version,
            },
        )
        return inv

    # -- phases -----------------------------------------------------------

    async def run_to_validation(self, run_id: str) -> Investigation:
        """CREATED through INDEPENDENT_VALIDATION, then stop and wait for a human."""
        inv = self._require(run_id)
        try:
            await self._evidence(inv)
            await self._hypotheses(inv)
            await self._candidates(inv)
            await self._primary_testing(inv)
            await self._independent_validation(inv)
        except Exception as exc:
            self._fail(inv, exc)
            raise
        return inv

    async def _evidence(self, inv: Investigation) -> None:
        self._goto(inv, WorkflowState.EVIDENCE_GATHERING, "Gathering evidence.")
        started = time.monotonic()
        aud = self.auditor(inv.id)

        items, prov = await self.registry.paperclip.gather_evidence(inv.target)
        inv.evidence.extend(items)
        aud.record(
            "tool_call",
            f"Paperclip returned {len(items)} evidence items "
            f"({sum(1 for i in items if i.support == 'contradicts')} contradicting).",
            provenance=prov,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        for item in items:
            self.bus.publish(inv.id, {"type": "evidence", "item": item.model_dump(mode="json")})
            await self._pace(0.06)

        # Biomni handoff: emit the task prompt as an artifact so the run has a
        # concrete next action rather than a missing integration.
        prompt, biomni_prov = self.registry.biomni.task_prompt(inv.id, inv.target)
        artifact = self._artifact(
            inv,
            "task_prompt",
            f"{inv.id}_biomni_task.md",
            prompt,
            "text/markdown",
            "Biomni task prompt. Run this and POST the export back to the import endpoint.",
            biomni_prov,
        )
        aud.record(
            "tool_call",
            "Biomni runs as an import handoff in this build; task prompt generated.",
            provenance=biomni_prov,
            output_artifact_ids=[artifact.id],
        )

        # If an operator already dropped an export in the import directory, pick
        # it up now rather than making them re-trigger the phase.
        pending = self.registry.biomni.load_pending(inv.id)
        if pending:
            imported, import_prov = self.registry.biomni.parse_import(inv.id, pending)
            inv.evidence.extend(imported)
            aud.record(
                "tool_call",
                f"Imported {len(imported)} Biomni findings from an operator-supplied export.",
                provenance=import_prov,
            )

        synthesis, synth_prov = await self.registry.anthropic.synthesise_evidence(
            inv.target.name, inv.evidence
        )
        inv.narrative["evidence"] = synthesis["summary"]
        inv.narrative["evidence_contradiction"] = synthesis["strongest_contradiction"]
        inv.narrative["evidence_support"] = synthesis["strongest_support"]
        inv.narrative["evidence_open_questions"] = "\n".join(synthesis["open_questions"])
        inv.narrative["evidence_mode"] = synth_prov.mode.value
        aud.record("tool_call", "Evidence synthesised.", provenance=synth_prov)
        self._save(inv)
        await self._pace()

    async def _hypotheses(self, inv: Investigation) -> None:
        from ..adapters.fixtures import hypotheses_fixture

        self._goto(inv, WorkflowState.HYPOTHESES_CREATED, "Forming falsifiable hypotheses.")
        prov = Provenance(
            tool="bioforge.hypothesis_ledger",
            mode=AdapterMode.FIXTURE,
            model_version="seeded-hypotheses/v1",
            note="Hypothesis statements and falsification criteria are seeded for the demo.",
        )
        for raw in hypotheses_fixture()["items"]:
            supporting = self._match_evidence(inv, raw.get("supporting_evidence_claims", []))
            contradicting = self._match_evidence(inv, raw.get("contradicting_evidence_claims", []))
            hypothesis = Hypothesis(
                statement=raw["statement"],
                falsification_criteria=raw["falsification_criteria"],
                supporting_evidence_ids=supporting,
                contradicting_evidence_ids=contradicting,
                planned_tests=raw["planned_tests"],
                prior_confidence=raw["prior_confidence"],
                posterior_confidence=raw["prior_confidence"],
                status="proposed",
                provenance=prov,
            )
            inv.hypotheses.append(hypothesis)
            self.bus.publish(
                inv.id, {"type": "hypothesis", "item": hypothesis.model_dump(mode="json")}
            )
            await self._pace(0.3)
        self.auditor(inv.id).record(
            "info", f"{len(inv.hypotheses)} falsifiable hypotheses registered.", provenance=prov
        )
        self._save(inv)

    @staticmethod
    def _match_evidence(inv: Investigation, prefixes: list[str]) -> list[str]:
        ids: list[str] = []
        for prefix in prefixes:
            for item in inv.evidence:
                if item.claim.startswith(prefix[:40]):
                    ids.append(item.id)
                    break
        return ids

    async def _candidates(self, inv: Investigation) -> None:
        self._goto(inv, WorkflowState.CANDIDATES_READY, "Generating candidates.")
        records, prov = await self.registry.tamarind.generate_candidates(
            inv.target.name, inv.target_product_profile.max_candidates
        )
        for record in records:
            candidate = Candidate(
                id=record["id"],
                name=record["name"],
                sequence=record["sequence"],
                format=record.get("format", inv.target_product_profile.format),
                parent_id=record.get("parent_id"),
                generation_tool=self.registry.tamarind.name,
                generation_note=record.get("generation_note", ""),
                provenance=prov,
            )
            inv.candidates.append(candidate)
            self._push_candidate(inv, candidate)
            await self._pace(0.08)
        self.auditor(inv.id).record(
            "tool_call",
            f"{len(records)} candidates generated in {inv.target_product_profile.format} format.",
            provenance=prov,
        )
        self._save(inv)

    async def _primary_testing(self, inv: Investigation) -> None:
        from ..adapters.fixtures import by_id

        self._goto(inv, WorkflowState.PRIMARY_TESTING, "Gate 1 — predicted binding.")
        aud = self.auditor(inv.id)
        for candidate in inv.candidates:
            record = by_id(candidate.id)
            if record is None:
                continue
            metrics, prov = self.registry.tamarind.binding_metrics(record)
            for metric, value in metrics.items():
                candidate.tests.append(
                    self._make_test(metric, value, self.registry.tamarind.name, prov)
                )
            evaluate_candidate(self.policy, candidate, gates_to_run=["binding"])
            self._push_candidate(inv, candidate)
            await self._pace(0.12)
        rejected = sum(1 for c in inv.candidates if c.status == "rejected")
        aud.record(
            "decision",
            f"Binding gate complete: {rejected} of {len(inv.candidates)} rejected.",
            parameters={"gate": "binding", "rejected": rejected},
        )
        self._save(inv)

    async def _independent_validation(self, inv: Investigation) -> None:
        from ..adapters.fixtures import by_id

        self._goto(
            inv,
            WorkflowState.INDEPENDENT_VALIDATION,
            "Gates 2 and 3 — independent structure and developability.",
        )
        aud = self.auditor(inv.id)
        aud.record(
            "info",
            self.registry.model_hub.independence_note(),
            provenance=self.registry.model_hub.provenance(),
        )

        pool = [c for c in inv.candidates if c.status != "rejected"]
        for candidate in pool:
            record = by_id(candidate.id)
            if record is None:
                continue

            agreement, agree_prov = await self.registry.model_hub.structure_agreement(record)
            if agreement:
                for metric, value in agreement.items():
                    candidate.tests.append(
                        self._make_test(metric, value, self.registry.model_hub.name, agree_prov)
                    )

            dev, computed_prov, model_prov = self.registry.tamarind.developability_metrics(record)
            for metric, value in dev.items():
                is_computed = METRIC_KIND.get(metric, "").endswith("sequence_derived")
                prov = computed_prov if is_computed else model_prov
                tool = "bioforge.biophysics" if is_computed else self.registry.tamarind.name
                candidate.tests.append(self._make_test(metric, value, tool, prov))

            evaluate_candidate(
                self.policy,
                candidate,
                gates_to_run=["binding", "independent_structure", "developability"],
            )
            self._push_candidate(inv, candidate)
            await self._pace(0.12)

        struct_rejects = [
            c.id
            for c in pool
            if c.status == "rejected"
            and "independent_structure" in [g.gate for g in c.gates if not g.passed]
        ]
        dev_rejects = [
            c.id
            for c in pool
            if c.status == "rejected"
            and c.id not in struct_rejects
            and "developability" in [g.gate for g in c.gates if not g.passed]
        ]
        aud.record(
            "decision",
            f"Independent structure rejected {len(struct_rejects)}; developability rejected "
            f"{len(dev_rejects)}. {sum(1 for c in inv.candidates if c.status != 'rejected')} "
            "candidates reach the adversarial challenge.",
            parameters={
                "independent_structure_rejected": struct_rejects,
                "developability_rejected": dev_rejects,
            },
        )
        inv.status_detail = (
            "Awaiting human action: press Challenge Survivors to run the adversarial gate."
        )
        self._save(inv)

    # -- human-triggered actions ------------------------------------------

    async def challenge(self, run_id: str) -> Investigation:
        from ..adapters.fixtures import by_id

        inv = self._require(run_id)
        if inv.challenge_run:
            return inv
        self._goto(
            inv,
            WorkflowState.ADVERSARIAL_CHALLENGE,
            "Gate 4 — mutation robustness and decoy challenge.",
            actor="human",
        )
        aud = self.auditor(inv.id)
        pool = [c for c in inv.candidates if c.status != "rejected"]

        async def one(candidate: Candidate) -> None:
            record = by_id(candidate.id)
            if record is None:
                return
            payload, prov = await self.registry.modal.challenge(record, inv.seed)
            if payload is None:
                return
            artifact = self._artifact(
                inv,
                "raw_tool_output",
                f"{inv.id}_{candidate.id}_challenge.json",
                packaging.dumps(payload),
                "application/json",
                f"Alanine scan and decoy panel raw output for {candidate.id}.",
                prov,
            )
            for metric in ("retained_score_across_mutations", "decoy_discrimination_margin"):
                candidate.tests.append(
                    self._make_test(
                        metric,
                        payload[metric],
                        self.registry.modal.name,
                        prov,
                        artifact_ids=[artifact.id],
                    )
                )
            evaluate_candidate(self.policy, candidate, gates_to_run=GATE_ORDER)

        # Modal's whole point is parallelism; run the pool concurrently.
        await asyncio.gather(*(one(c) for c in pool))
        for candidate in pool:
            self._push_candidate(inv, candidate)
            await self._pace(0.2)

        inv.challenge_run = True
        shortlist(self.policy, inv.candidates, inv.target_product_profile.max_finalists)
        killed = [c.id for c in pool if c.status == "rejected"]
        aud.record(
            "decision",
            f"Adversarial challenge rejected {len(killed)} previously-surviving candidate(s): "
            f"{', '.join(killed) or 'none'}.",
            actor="human",
            parameters={"rejected": killed, "decoy_panel": [d["id"] for d in DECOY_PANEL]},
        )
        for candidate in inv.candidates:
            self._push_candidate(inv, candidate)
        inv.status_detail = "Challenge complete. Redesign the near-miss, or finalise the dossier."
        self._save(inv)
        return inv

    async def redesign(self, run_id: str, candidate_id: str | None = None) -> Investigation:
        inv = self._require(run_id)
        if inv.redesign_run:
            return inv  # MVP allows exactly one iteration
        self._goto(
            inv, WorkflowState.REDESIGNING, "Redesigning the selected near-miss.", actor="human"
        )
        aud = self.auditor(inv.id)

        parent = (
            inv.candidate(candidate_id)
            if candidate_id
            else pick_redesign_target(self.policy, inv.candidates)
        )
        if parent is None:
            aud.record("info", "No near-miss candidate qualified for redesign.")
            inv.redesign_run = True
            self._save(inv)
            return inv

        failing = [g for g in parent.gates if not g.passed]
        aud.record(
            "decision",
            f"Selected {parent.id} for redesign: it failed only the "
            f"{failing[0].gate if failing else 'unknown'} gate, by the smallest margin of any "
            "rejected candidate.",
            actor="human",
            parameters={
                "parent": parent.id,
                "failing_metrics": failing[0].metrics_failed if failing else [],
            },
        )

        from ..adapters.fixtures import by_id

        parent_record = by_id(parent.id) or {}
        record, prov = await self.registry.tamarind.redesign(parent_record)
        child = Candidate(
            id=record["id"],
            name=record["name"],
            sequence=record["sequence"],
            format=parent.format,
            parent_id=parent.id,
            generation_tool=self.registry.tamarind.name,
            generation_note=record.get("generation_note", ""),
            provenance=prov,
        )
        inv.candidates.append(child)
        inv.redesign_parent_id = parent.id
        self._push_candidate(inv, child)
        await self._pace()

        # Re-run every gate on the child. A redesign that is only re-scored on
        # the gate it failed would be exactly the kind of thing this product
        # exists to catch.
        binding, bind_prov = self.registry.tamarind.binding_metrics(record)
        for metric, value in binding.items():
            child.tests.append(
                self._make_test(metric, value, self.registry.tamarind.name, bind_prov)
            )

        agreement, agree_prov = await self.registry.model_hub.structure_agreement(record)
        if agreement:
            for metric, value in agreement.items():
                child.tests.append(
                    self._make_test(metric, value, self.registry.model_hub.name, agree_prov)
                )

        dev, computed_prov, model_prov = self.registry.tamarind.developability_metrics(record)
        for metric, value in dev.items():
            is_computed = METRIC_KIND.get(metric, "").endswith("sequence_derived")
            child.tests.append(
                self._make_test(
                    metric,
                    value,
                    "bioforge.biophysics" if is_computed else self.registry.tamarind.name,
                    computed_prov if is_computed else model_prov,
                )
            )

        payload, modal_prov = await self.registry.modal.challenge(record, inv.seed)
        if payload:
            for metric in ("retained_score_across_mutations", "decoy_discrimination_margin"):
                child.tests.append(
                    self._make_test(metric, payload[metric], self.registry.modal.name, modal_prov)
                )

        evaluate_candidate(self.policy, child, gates_to_run=GATE_ORDER)
        inv.narrative["redesign_delta"] = packaging.render_redesign_delta(parent, child)
        shortlist(self.policy, inv.candidates, inv.target_product_profile.max_finalists)

        aud.record(
            "decision",
            f"{child.id} {'passed' if child.status != 'rejected' else 'failed'} all four gates "
            f"after redesign of {parent.id}.",
            provenance=prov,
            parameters={"parent": parent.id, "child": child.id, "outcome": child.decision.outcome},
        )
        inv.redesign_run = True
        for candidate in inv.candidates:
            self._push_candidate(inv, candidate)
        self._save(inv)
        return await self.finalise(run_id)

    async def finalise(self, run_id: str) -> Investigation:
        inv = self._require(run_id)
        if inv.status is WorkflowState.COMPLETED:
            return inv
        self._goto(inv, WorkflowState.FINAL_REVIEW, "Final review.", actor="human")
        aud = self.auditor(inv.id)

        shortlist(self.policy, inv.candidates, inv.target_product_profile.max_finalists)

        gate_summary = {
            "survivors": sum(1 for c in inv.candidates if c.status in ("survives", "recommended")),
            "rejected_independent_structure": sum(
                1
                for c in inv.candidates
                if any(g.gate == "independent_structure" and not g.passed for g in c.gates)
            ),
            "rejected_robustness": sum(
                1
                for c in inv.candidates
                if any(g.gate == "robustness" and not g.passed for g in c.gates)
            ),
            "challenge_run": inv.challenge_run,
            "redesign_run": inv.redesign_run,
            "redesign_passed": any(
                c.parent_id and c.status in ("survives", "recommended") for c in inv.candidates
            ),
        }
        updates, hyp_prov = await self.registry.anthropic.update_hypotheses(
            inv.hypotheses, gate_summary
        )
        by_index = {h.id: h for h in inv.hypotheses}
        for update in updates.get("updates", []):
            hypothesis = by_index.get(update["hypothesis_id"])
            if hypothesis is None:
                continue
            hypothesis.status = update["status"]
            hypothesis.posterior_confidence = float(update["posterior_confidence"])
            hypothesis.result_summary = update["result_summary"]
            self.bus.publish(
                inv.id, {"type": "hypothesis", "item": hypothesis.model_dump(mode="json")}
            )
        aud.record(
            "tool_call", "Hypothesis ledger updated from gate outcomes.", provenance=hyp_prov
        )

        for candidate in inv.candidates:
            if candidate.status in ("recommended", "survives") or candidate.parent_id:
                rationale, rat_prov = await self.registry.anthropic.decision_rationale(
                    candidate, inv.target.name
                )
                candidate.decision.summary = rationale["why_it_survived"]
                candidate.decision.uncertainties = (
                    rationale["remaining_uncertainty"] + candidate.decision.uncertainties
                )
                candidate.decision.reversal_conditions = rationale["what_would_reverse_this"]
                inv.narrative[f"next_step_{candidate.id}"] = rationale[
                    "suggested_wet_lab_next_step"
                ]
                inv.narrative[f"headline_{candidate.id}"] = rationale["headline"]
                _ = rat_prov
                self._push_candidate(inv, candidate)
        self._save(inv)
        await self._pace()

        # -- package -------------------------------------------------------
        self._goto(inv, WorkflowState.PACKAGE_CREATED, "Building the experiment-ready package.")
        bundle = packaging.build_bundle(inv, self.policy, self.store.events(inv.id))
        for kind, filename, content, media, description in bundle:
            self._artifact(inv, kind, filename, content, media, description)
        aud.record(
            "info",
            f"Dossier package created: {len(bundle)} artifacts.",
            output_artifact_ids=[a.id for a in inv.artifacts[-len(bundle) :]],
        )
        self._save(inv)

        self._goto(inv, WorkflowState.COMPLETED, "Investigation complete.")
        return inv

    # -- benchling approval ------------------------------------------------

    async def request_benchling_write(self, run_id: str) -> Investigation:
        inv = self._require(run_id)
        inv.benchling.requested = True
        inv.benchling.records = self.registry.benchling.build_records(inv)
        inv.benchling.note = (
            f"{len(inv.benchling.records)} record(s) prepared. Nothing has been written."
        )
        self.auditor(inv.id).record(
            "human_action",
            "Benchling write requested. Awaiting explicit approval.",
            actor="human",
            provenance=self.registry.benchling.provenance(),
        )
        self._save(inv)
        return inv

    async def approve_benchling_write(self, run_id: str, approver: str) -> Investigation:
        inv = self._require(run_id)
        if not inv.benchling.requested:
            await self.request_benchling_write(run_id)
            inv = self._require(run_id)
        inv.benchling.approved = True
        inv.benchling.approved_by = approver
        inv.benchling.approved_at = utcnow()
        aud = self.auditor(inv.id)
        aud.record(
            "human_action",
            f"Benchling write approved by {approver}.",
            actor=approver,
        )
        records, prov = await self.registry.benchling.write_records(inv, approved=True)
        inv.benchling.records = records
        inv.benchling.written = prov.mode is AdapterMode.LIVE
        inv.benchling.write_mode = prov.mode
        inv.benchling.note = prov.note or ""
        aud.record(
            "tool_call",
            f"Benchling write executed in {prov.mode.value} mode.",
            provenance=prov,
            actor=approver,
        )
        self._save(inv)
        return inv

    # -- imports ------------------------------------------------------------

    def import_biomni(self, run_id: str, payload: dict[str, Any]) -> Investigation:
        inv = self._require(run_id)
        items, prov = self.registry.biomni.parse_import(run_id, payload)
        inv.evidence.extend(items)
        artifact = self._artifact(
            inv,
            "import_manifest",
            f"{run_id}_biomni_import.json",
            packaging.dumps(payload),
            "application/json",
            "Operator-supplied Biomni export as received.",
            prov,
        )
        self.auditor(inv.id).record(
            "tool_call",
            f"Imported {len(items)} Biomni findings via the handoff path.",
            actor="human",
            provenance=prov,
            output_artifact_ids=[artifact.id],
        )
        for item in items:
            self.bus.publish(inv.id, {"type": "evidence", "item": item.model_dump(mode="json")})
        self._save(inv)
        return inv

    # -- failure ------------------------------------------------------------

    def _fail(self, inv: Investigation, exc: BaseException) -> None:
        inv.error = f"{type(exc).__name__}: {exc}"
        prev = inv.status
        if inv.status not in (WorkflowState.COMPLETED, WorkflowState.FAILED):
            inv.status = WorkflowState.FAILED
        inv.status_detail = inv.error
        self.auditor(inv.id).record(
            "error",
            f"Run failed during {prev.value}.",
            prev_state=prev,
            next_state=inv.status,
            error=inv.error,
        )
        self._save(inv)

    def _require(self, run_id: str) -> Investigation:
        inv = self.store.load(run_id)
        if inv is None:
            raise KeyError(f"investigation {run_id} not found")
        return inv

    # -- convenience --------------------------------------------------------

    async def run_all(self, run_id: str) -> Investigation:
        """Full unattended run. Used by `make demo-headless` and the tests."""
        await self.run_to_validation(run_id)
        await self.challenge(run_id)
        return await self.redesign(run_id)
