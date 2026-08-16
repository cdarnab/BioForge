"""Biomni: target biology and bioinformatics context.

Biomni's primary supported path here is a **deliberate import handoff**, which
the build brief prefers over pretending an integration exists:

1. The run emits a task prompt artifact describing exactly what to ask Biomni.
2. A scientist runs it and exports the result.
3. The result file is POSTed back to `/api/investigations/{run_id}/import/biomni`
   and parsed into evidence with `mode=import_handoff` provenance.

If the open-source `biomni` package happens to be importable, the adapter says
so in its status so an operator knows a programmatic path may be available — but
it does not guess at that package's API surface.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from ..config import IMPORT_DIR
from ..models import AdapterMode, EvidenceItem, Provenance, Target
from .base import Adapter

TASK_PROMPT_TEMPLATE = """\
# Biomni task — target context for {target_name}

Run this in Biomni and export the result as JSON to:
    {import_path}

Then POST that file to:
    POST /api/investigations/{run_id}/import/biomni

## Requested analysis

Target: {target_name}
UniProt: {uniprot}
PDB: {pdb}
Epitope region of interest: {epitope}

1. Summarise the target's biology and its role in the relevant disease context.
2. List close homologs and paralogs that a binder could cross-react with, with
   percent identity over the structured domain.
3. Report the isoform landscape and flag any isoform that lacks the epitope
   region above.
4. Report known binding partners and receptors, and which surfaces they use.
5. Flag any conservation or polymorphism in the epitope region that would affect
   a binder's coverage across populations.

## Required output shape

{{
  "target": "{target_name}",
  "analysis_version": "<biomni version string>",
  "findings": [
    {{
      "claim": "<one-sentence finding>",
      "evidence_level": "observed | reported | annotated | predicted",
      "support": "supports | contradicts | context_only",
      "source_title": "<database or paper>",
      "source_url": "<url>",
      "citation_locator": "<accession, section or record id>",
      "relevance": 0.0,
      "confidence": 0.0
    }}
  ]
}}

Every finding must carry its own citation. Findings without a source will be
imported as `evidence_level: predicted` and marked unsupported.
"""


class BiomniAdapter(Adapter):
    name = "biomni"
    purpose = "Target biology, homologs, isoforms and cross-reactivity context."
    requirement = (
        "No automated interface is configured. Run the generated task prompt in Biomni "
        "and POST the exported JSON back to the import endpoint."
    )

    @property
    def configured(self) -> bool:
        # There is no credential that turns this into a live API call in this build.
        return False

    @property
    def live_supported(self) -> bool:
        return False

    def package_available(self) -> bool:
        return importlib.util.find_spec("biomni") is not None

    def status(self):  # type: ignore[override]
        base = super().status()
        if self.package_available():
            base.detail += (
                " The open-source `biomni` package is importable in this environment, so a "
                "programmatic path may be available; this build does not assume its API."
            )
        return base

    # -- handoff ----------------------------------------------------------

    def task_prompt(self, run_id: str, target: Target) -> tuple[str, Provenance]:
        import_path = IMPORT_DIR / f"{run_id}_biomni.json"
        text = TASK_PROMPT_TEMPLATE.format(
            target_name=target.name,
            uniprot=target.uniprot_id or "n/a",
            pdb=target.pdb_id or "n/a",
            epitope=target.epitope_description or "n/a",
            run_id=run_id,
            import_path=import_path,
        )
        prov = self.provenance(
            mode=AdapterMode.IMPORT_HANDOFF,
            parameters={"run_id": run_id, "expected_import_path": str(import_path)},
            note="Task prompt generated. No Biomni analysis has been run yet.",
        )
        return text, prov

    def pending_import_path(self, run_id: str) -> Path:
        return IMPORT_DIR / f"{run_id}_biomni.json"

    def parse_import(
        self, run_id: str, payload: dict[str, Any]
    ) -> tuple[list[EvidenceItem], Provenance]:
        """Parse an exported Biomni result into evidence with import provenance."""
        version = str(payload.get("analysis_version", "unspecified"))
        prov = self.provenance(
            mode=AdapterMode.IMPORT_HANDOFF,
            model_version=version,
            parameters={"run_id": run_id, "findings": len(payload.get("findings", []))},
            note=(
                "Imported from a Biomni export supplied by a human operator. BioForge did "
                "not execute this analysis and cannot attest to how it was produced."
            ),
        )
        items: list[EvidenceItem] = []
        for raw in payload.get("findings", []):
            has_source = bool(raw.get("source_url") or raw.get("citation_locator"))
            items.append(
                EvidenceItem(
                    claim=raw.get("claim", ""),
                    source_type="analysis",
                    source_title=raw.get("source_title") or "Biomni analysis (uncited)",
                    source_url=raw.get("source_url"),
                    citation_locator=raw.get("citation_locator", ""),
                    support=raw.get("support", "context_only"),
                    evidence_level=raw.get("evidence_level", "reported")
                    if has_source
                    else "predicted",
                    relevance=float(raw.get("relevance", 0.0)),
                    confidence=float(raw.get("confidence", 0.0)),
                    tool=self.name,
                    provenance=prov,
                )
            )
        return items, prov

    def load_pending(self, run_id: str) -> dict[str, Any] | None:
        path = self.pending_import_path(run_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
