"""Paperclip: literature, regulatory, trial, UniProt and PDB evidence.

Live mode posts to an operator-supplied endpoint (`PAPERCLIP_API_URL`). This
repository does not hard-code a vendor base URL or invent a request schema for
one — if your team was issued an endpoint, point the adapter at it and the
provenance record will say `operator-configured endpoint`. Without it, the
adapter serves the curated fixture bundle and says so.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..models import AdapterMode, EvidenceItem, Provenance, Target
from .base import Adapter
from .fixtures import evidence_fixture


class PaperclipAdapter(Adapter):
    name = "paperclip"
    purpose = "Cited literature, FDA, clinical-trial, UniProt and PDB evidence."
    requirement = (
        "Set PAPERCLIP_API_URL to the search endpoint your team was issued and "
        "PAPERCLIP_API_KEY to its bearer token."
    )

    @property
    def configured(self) -> bool:
        return bool(self.settings.paperclip_api_key and self.settings.paperclip_api_url)

    async def gather_evidence(self, target: Target) -> tuple[list[EvidenceItem], Provenance]:
        if self.configured:
            try:
                return await self._live(target)
            except Exception as exc:  # degrade visibly, never silently
                prov = self.degraded(f"{type(exc).__name__}: {exc}")
                return self._fixture_items(prov), prov
        return self._fixture_items(self._fixture_provenance()), self._fixture_provenance()

    # -- fixture ----------------------------------------------------------

    def _fixture_provenance(self) -> Provenance:
        return self.provenance(
            mode=AdapterMode.FIXTURE,
            parameters={"bundle": "vegfa_evidence.json"},
            note=(
                "Curated fixture evidence. The citations are real public records but they "
                "were assembled by hand, not retrieved by a live Paperclip query."
            ),
        )

    def _fixture_items(self, prov: Provenance) -> list[EvidenceItem]:
        payload = evidence_fixture()
        items: list[EvidenceItem] = []
        for raw in payload["items"]:
            item_prov = prov.model_copy(update={"tool": raw.get("tool", self.name)})
            items.append(EvidenceItem(**raw, provenance=item_prov))
        return items

    # -- live -------------------------------------------------------------

    async def _live(self, target: Target) -> tuple[list[EvidenceItem], Provenance]:
        query = {
            "query": target.name,
            "uniprot_id": target.uniprot_id,
            "pdb_id": target.pdb_id,
            "epitope": target.epitope_description,
            "source_types": ["paper", "database", "regulatory", "trial"],
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.settings.paperclip_api_url,
                json=query,
                headers={"Authorization": f"Bearer {self.settings.paperclip_api_key}"},
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()

        prov = self.provenance(
            mode=AdapterMode.LIVE,
            parameters=query,
            note="Retrieved from the operator-configured Paperclip endpoint.",
        )
        results = payload.get("results") or payload.get("items") or []
        items: list[EvidenceItem] = []
        for raw in results:
            items.append(
                EvidenceItem(
                    claim=raw.get("claim") or raw.get("summary", ""),
                    source_type=raw.get("source_type", "paper"),
                    source_title=raw.get("title", "Untitled source"),
                    source_url=raw.get("url"),
                    citation_locator=raw.get("locator", ""),
                    support=raw.get("support", "context_only"),
                    # A retrieval service reports what a source says; it does not
                    # observe. Default to "reported" unless it tells us otherwise.
                    evidence_level=raw.get("evidence_level", "reported"),
                    relevance=float(raw.get("relevance", 0.0)),
                    confidence=float(raw.get("confidence", 0.0)),
                    tool=self.name,
                    provenance=prov,
                )
            )
        if not items:
            raise RuntimeError("Paperclip returned no results")
        return items, prov
