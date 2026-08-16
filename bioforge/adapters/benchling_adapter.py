"""Benchling: system of record, plus Benchling Model Hub as the independent check.

Two adapters live here because they are two different trust roles:

`BenchlingModelHubAdapter` runs the *independent* structure prediction. It must
use a different model family from the design path or gate 2 is theatre; the
model version string it reports is what a reviewer checks.

`BenchlingAdapter` writes candidate records, prediction results, lineage and a
notebook entry. Every live write is blocked behind an explicit human approval —
`write_records` raises unless `approved=True` is passed by the API layer, which
only sets it after a human hits the approve button.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..models import AdapterMode, Provenance
from .base import Adapter, AdapterError

INDEPENDENT_MODEL_VERSION = "benchling-model-hub-fixture/structure-v2"
DESIGN_PATH_MODEL_FAMILY = "tamarind-fixture/design-v1"


class BenchlingModelHubAdapter(Adapter):
    name = "benchling_model_hub"
    purpose = "Independent structure prediction from a different model family than the design path."
    requirement = "Set BENCHLING_MODEL_HUB_URL and BENCHLING_API_KEY."

    @property
    def configured(self) -> bool:
        return bool(self.settings.benchling_model_hub_url and self.settings.benchling_api_key)

    def independence_note(self) -> str:
        return (
            f"Independent model '{INDEPENDENT_MODEL_VERSION}' is a different family from the "
            f"design path '{DESIGN_PATH_MODEL_FAMILY}'. Agreement between two predictors is "
            "not evidence that either is right; it only removes single-model artifacts."
        )

    async def structure_agreement(
        self, record: dict[str, Any]
    ) -> tuple[dict[str, float] | None, Provenance]:
        metrics = record.get("model_hub_metrics")
        if metrics is None:
            # This candidate never reached the independent gate.
            return None, self.provenance(mode=AdapterMode.FIXTURE, note="Gate not run.")

        if self.configured:
            try:
                return await self._live(record)
            except Exception as exc:
                prov = self.degraded(
                    f"{type(exc).__name__}: {exc}", model_version=INDEPENDENT_MODEL_VERSION
                )
                return {k: float(v) for k, v in metrics.items()}, prov

        prov = self.provenance(
            mode=AdapterMode.FIXTURE,
            model_version=INDEPENDENT_MODEL_VERSION,
            parameters={"candidate": record["id"], "reference": "design_path_pose"},
            note="Authored fixture comparison. " + self.independence_note(),
        )
        return {k: float(v) for k, v in metrics.items()}, prov

    async def _live(self, record: dict[str, Any]) -> tuple[dict[str, float], Provenance]:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{self.settings.benchling_model_hub_url.rstrip('/')}/predict",
                json={"sequence": record["sequence"], "target": "VEGFA"},
                headers={"Authorization": f"Bearer {self.settings.benchling_api_key}"},
            )
            response.raise_for_status()
            payload = response.json()
        version = str(payload.get("model_version", "benchling-model-hub/unknown"))
        if version.split("/")[0] == DESIGN_PATH_MODEL_FAMILY.split("/")[0]:
            raise AdapterError(
                "Independent gate refused: Model Hub reported the same model family as the "
                f"design path ({version}). That comparison would not be independent."
            )
        return {
            "model_agreement": float(payload["model_agreement"]),
            "epitope_rmsd_angstrom": float(payload["epitope_rmsd_angstrom"]),
        }, self.provenance(
            mode=AdapterMode.LIVE,
            model_version=version,
            parameters={"candidate": record["id"]},
            note=self.independence_note(),
        )


class BenchlingAdapter(Adapter):
    name = "benchling"
    purpose = "Candidate sequences, prediction records, lineage, notebook entry and assay plan."
    requirement = (
        "Install benchling-sdk and set BENCHLING_TENANT, BENCHLING_API_KEY and "
        "BENCHLING_PROJECT_ID. A Benchling MCP URL can be supplied instead via "
        "BENCHLING_MCP_URL."
    )

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.benchling_tenant
            and self.settings.benchling_api_key
            and self.settings.benchling_project_id
        )

    def build_records(self, investigation: Any) -> list[dict[str, Any]]:
        """The exact payload that would be written. Shown to the human first."""
        records: list[dict[str, Any]] = []
        for candidate in investigation.finalists():
            records.append(
                {
                    "entity_type": "dna_sequence_or_aa_sequence",
                    "name": candidate.name,
                    "aliases": [f"{investigation.target.name}-{candidate.name}"],
                    "amino_acid_sequence": candidate.sequence,
                    "schema_fields": {
                        "target": investigation.target.name,
                        "format": candidate.format,
                        "parent_candidate": candidate.parent_id or "",
                        "run_id": investigation.id,
                        "recommendation_rank": candidate.rank,
                        "status": "computationally_prioritised_not_validated",
                    },
                    "prediction_results": [
                        {
                            "metric": t.metric,
                            "value": t.value,
                            "unit": t.unit,
                            "threshold": t.threshold,
                            "passed": t.passed,
                            "tool": t.tool,
                            "model_version": t.model_version,
                            "mode": t.provenance.mode.value,
                            "result_type": "in_silico_prediction",
                        }
                        for t in candidate.tests
                    ],
                }
            )
        return records

    async def write_records(
        self, investigation: Any, *, approved: bool
    ) -> tuple[list[dict[str, Any]], Provenance]:
        records = self.build_records(investigation)

        if self.configured and not approved:
            # Belt and braces: the API layer also gates this, but an adapter that
            # can write to a customer's system of record should refuse on its own.
            raise AdapterError("Refusing to write to Benchling without explicit human approval.")

        if not self.configured:
            prov = self.provenance(
                mode=AdapterMode.FIXTURE,
                parameters={"records": len(records)},
                note=(
                    "Benchling is not configured. Records were written to the local demo "
                    "store only — nothing was sent to a Benchling tenant."
                ),
            )
            return records, prov

        try:
            written = await self._live_write(records)
        except Exception as exc:
            prov = self.degraded(f"{type(exc).__name__}: {exc}")
            return records, prov
        return written, self.provenance(
            mode=AdapterMode.LIVE,
            parameters={"tenant": self.settings.benchling_tenant, "records": len(records)},
            note="Written to the live Benchling tenant after human approval.",
        )

    async def _live_write(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            from benchling_sdk.auth.api_key_auth import ApiKeyAuth
            from benchling_sdk.benchling import Benchling
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise AdapterError(
                "benchling-sdk is not installed. Install it with "
                "`pip install benchling-sdk` to enable live Benchling writes."
            ) from exc

        client = Benchling(
            url=f"https://{self.settings.benchling_tenant}.benchling.com",
            auth_method=ApiKeyAuth(self.settings.benchling_api_key),
        )
        # Deliberately not implemented against a guessed schema. Registering an
        # AA sequence requires the tenant's own schema and registry IDs, which
        # differ per customer and cannot be inferred here.
        raise AdapterError(
            "Live Benchling write is not wired to a specific tenant schema. "
            f"Connected to {client.__class__.__name__}; supply your registry and schema IDs "
            "in bioforge/adapters/benchling_adapter.py::_live_write to complete it. "
            f"{len(records)} record(s) were prepared and are available for export."
        )
