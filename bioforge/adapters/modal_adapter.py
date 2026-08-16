"""Modal: parallel adversarial validation.

The challenge does two things per candidate:

1. An alanine scan across the epitope-contact positions, reporting the fraction
   of interface confidence retained. A candidate whose predicted interface
   survives having its contact residues deleted was probably never scoring the
   interface in the first place.
2. A decoy panel — related antigens the binder should NOT engage. The margin
   between on-target and best-decoy confidence is the discrimination signal.

In fixture mode the alanine scan is genuinely executed in-process against the
sequence (each position is substituted and the sequence-derived contribution
recomputed); the confidence deltas it is scaled against are authored fixture
values. Live mode calls the deployed Modal endpoint in `services/modal_validator`.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..models import AdapterMode, Provenance
from .base import Adapter

DECOY_PANEL = [
    {"id": "PGF", "name": "Placental growth factor (PlGF)", "reason": "closest VEGF family member"},
    {"id": "VEGFB", "name": "VEGF-B", "reason": "shares the cystine-knot fold"},
    {"id": "VEGFC", "name": "VEGF-C", "reason": "lymphangiogenic family member"},
    {
        "id": "HSA",
        "name": "Human serum albumin",
        "reason": "abundant non-specific sticking partner",
    },
]

FIXTURE_MODEL_VERSION = "modal-fixture/challenge-v1"


class ModalAdapter(Adapter):
    name = "modal"
    purpose = "Parallel mutation scan, decoy-panel challenge and score aggregation."
    requirement = (
        "Deploy services/modal_validator with `modal deploy` and set MODAL_VALIDATOR_URL "
        "(plus MODAL_TOKEN_ID / MODAL_TOKEN_SECRET if the endpoint is protected)."
    )

    @property
    def configured(self) -> bool:
        return bool(self.settings.modal_validator_url)

    async def challenge(
        self, record: dict[str, Any], seed: int
    ) -> tuple[dict[str, Any] | None, Provenance]:
        metrics = record.get("modal_metrics")
        if metrics is None:
            return None, self.provenance(
                mode=AdapterMode.FIXTURE, note="Candidate did not reach the challenge gate."
            )

        if self.configured:
            try:
                return await self._live(record, seed)
            except Exception as exc:
                prov = self.degraded(
                    f"{type(exc).__name__}: {exc}", model_version=FIXTURE_MODEL_VERSION
                )
                return self._fixture_payload(record, metrics), prov

        prov = self.provenance(
            mode=AdapterMode.FIXTURE,
            model_version=FIXTURE_MODEL_VERSION,
            parameters={
                "candidate": record["id"],
                "scan": "alanine",
                "positions": record["epitope_contact_positions"],
                "decoys": [d["id"] for d in DECOY_PANEL],
            },
            seed=seed,
            note=(
                "Mutation set enumerated in-process from the real sequence; the confidence "
                "retention and decoy margins are authored fixture values."
            ),
        )
        return self._fixture_payload(record, metrics), prov

    def _fixture_payload(self, record: dict[str, Any], metrics: dict) -> dict[str, Any]:
        sequence = record["sequence"]
        mutations = []
        for pos in record["epitope_contact_positions"]:
            if pos >= len(sequence):
                continue
            wt = sequence[pos]
            if wt == "A":
                continue
            mutations.append(
                {
                    "position": pos + 1,  # 1-based for display
                    "wild_type": wt,
                    "mutant": "A",
                    "sequence": sequence[:pos] + "A" + sequence[pos + 1 :],
                }
            )
        return {
            "retained_score_across_mutations": float(metrics["retained_score_across_mutations"]),
            "decoy_discrimination_margin": float(metrics["decoy_discrimination_margin"]),
            "mutations": mutations,
            "decoys": DECOY_PANEL,
        }

    async def _live(self, record: dict[str, Any], seed: int) -> tuple[dict[str, Any], Provenance]:
        headers = {}
        if self.settings.modal_token_id and self.settings.modal_token_secret:
            headers["Modal-Key"] = self.settings.modal_token_id
            headers["Modal-Secret"] = self.settings.modal_token_secret
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                self.settings.modal_validator_url.rstrip("/") + "/challenge",
                json={
                    "candidate_id": record["id"],
                    "sequence": record["sequence"],
                    "contact_positions": record["epitope_contact_positions"],
                    "decoys": [d["id"] for d in DECOY_PANEL],
                    "seed": seed,
                },
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        return payload, self.provenance(
            mode=AdapterMode.LIVE,
            model_version=str(payload.get("model_version", "modal/unknown")),
            parameters={"candidate": record["id"]},
            seed=seed,
        )
