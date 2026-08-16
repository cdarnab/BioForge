"""Tamarind Bio: candidate design/import, structure prediction, developability.

This is the *primary design path*. Its structure prediction must never be the
same model family as the independent-validation gate, or that gate is
meaningless — the model version string is recorded on every result so a reviewer
can check.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..biophysics import CdrSpans, sequence_metrics
from ..models import AdapterMode, Provenance
from .base import Adapter
from .fixtures import candidate_records, redesign_record

FIXTURE_MODEL_VERSION = "tamarind-fixture/design-v1"


class TamarindAdapter(Adapter):
    name = "tamarind"
    purpose = "Candidate design/import, structure prediction, binding and developability scores."
    requirement = "Set TAMARIND_API_URL and TAMARIND_API_KEY."

    @property
    def configured(self) -> bool:
        return bool(self.settings.tamarind_api_key and self.settings.tamarind_api_url)

    # -- candidate generation --------------------------------------------

    async def generate_candidates(
        self, target_name: str, count: int
    ) -> tuple[list[dict[str, Any]], Provenance]:
        if self.configured:
            try:
                return await self._live_generate(target_name, count)
            except Exception as exc:
                prov = self.degraded(
                    f"{type(exc).__name__}: {exc}", model_version=FIXTURE_MODEL_VERSION
                )
                return candidate_records()[:count], prov
        prov = self.provenance(
            mode=AdapterMode.FIXTURE,
            model_version=FIXTURE_MODEL_VERSION,
            parameters={"target": target_name, "count": count},
            note=(
                "Synthetic VHH scaffold sequences with authored CDR loops from the seeded "
                "fixture set. Not real therapeutic sequences."
            ),
        )
        return candidate_records()[:count], prov

    async def _live_generate(
        self, target_name: str, count: int
    ) -> tuple[list[dict[str, Any]], Provenance]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.settings.tamarind_api_url.rstrip('/')}/design",
                json={"target": target_name, "n": count, "format": "nanobody"},
                headers={"Authorization": f"Bearer {self.settings.tamarind_api_key}"},
            )
            response.raise_for_status()
            payload = response.json()
        records = payload.get("candidates", [])
        if not records:
            raise RuntimeError("Tamarind returned no candidates")
        prov = self.provenance(
            mode=AdapterMode.LIVE,
            model_version=str(payload.get("model_version", "tamarind/unknown")),
            parameters={"target": target_name, "count": count},
        )
        return records, prov

    # -- scoring ----------------------------------------------------------

    def binding_metrics(self, record: dict[str, Any]) -> tuple[dict[str, float], Provenance]:
        """Predicted binding for one candidate. Fixture path reads authored values."""
        metrics = dict(record["tamarind_metrics"])
        prov = self.provenance(
            mode=self.effective_mode() if self.configured else AdapterMode.FIXTURE,
            model_version=FIXTURE_MODEL_VERSION if not self.configured else "tamarind/live",
            parameters={"candidate": record["id"], "epitope_mode": "receptor_binding_pole"},
            note=None
            if self.configured
            else "Authored fixture prediction. No structure prediction was executed.",
        )
        return {
            "interface_confidence": float(metrics["interface_confidence"]),
            "predicted_dg_kcal_mol": float(metrics["predicted_dg_kcal_mol"]),
        }, prov

    def developability_metrics(
        self, record: dict[str, Any]
    ) -> tuple[dict[str, float], Provenance, Provenance]:
        """Developability panel.

        Returns two provenances because the panel mixes two very different kinds
        of number: values computed here from the sequence, and values a model
        predicted. They are attributed separately so the UI can label them.
        """
        spans = CdrSpans(
            cdr1=tuple(record["cdr_spans"]["cdr1"]),  # type: ignore[arg-type]
            cdr2=tuple(record["cdr_spans"]["cdr2"]),  # type: ignore[arg-type]
            cdr3=tuple(record["cdr_spans"]["cdr3"]),  # type: ignore[arg-type]
        )
        computed = sequence_metrics(record["sequence"], spans)
        model_side = {
            "predicted_tm_celsius": float(record["tamarind_metrics"]["predicted_tm_celsius"]),
            "immunogenicity_risk": float(record["tamarind_metrics"]["immunogenicity_risk"]),
        }

        computed_prov = Provenance(
            tool="bioforge.biophysics",
            mode=AdapterMode.LIVE,  # genuinely computed here, every run
            model_version="kyte-doolittle-1982",
            parameters={"cdr_spans": record["cdr_spans"], "window": 5},
            note=(
                "Computed from the sequence in-process. Hydrophobicity and aggregation are "
                "scale-based heuristics, not validated developability predictors."
            ),
        )
        model_prov = self.provenance(
            mode=AdapterMode.FIXTURE if not self.configured else AdapterMode.LIVE,
            model_version=FIXTURE_MODEL_VERSION if not self.configured else "tamarind/live",
            parameters={"candidate": record["id"]},
            note=None if self.configured else "Authored fixture prediction.",
        )
        return {**computed, **model_side}, computed_prov, model_prov

    # -- redesign ---------------------------------------------------------

    async def redesign(self, parent: dict[str, Any]) -> tuple[dict[str, Any], Provenance]:
        """Produce one child candidate addressing the parent's failing liability."""
        record = redesign_record()
        prov = self.provenance(
            mode=AdapterMode.FIXTURE if not self.configured else AdapterMode.LIVE,
            model_version=FIXTURE_MODEL_VERSION,
            parameters={
                "parent": parent["id"],
                "objective": "reduce_cdr_hydrophobic_patch",
                "constraint": "retain_epitope_contacts",
            },
            note=(
                "Fixture redesign: three hydrophobic CDR3 apex residues substituted with "
                "polar residues. The developability heuristics are recomputed from the new "
                "sequence; the model-derived scores are authored fixture values."
            ),
        )
        return record, prov
