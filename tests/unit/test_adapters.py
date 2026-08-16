"""Adapter contract: never claim live when you were not live."""

from __future__ import annotations

import httpx
import pytest

from bioforge.adapters.base import AdapterError
from bioforge.adapters.benchling_adapter import BenchlingAdapter, BenchlingModelHubAdapter
from bioforge.adapters.biomni_adapter import BiomniAdapter
from bioforge.adapters.fixtures import by_id, candidate_records
from bioforge.adapters.paperclip_adapter import PaperclipAdapter
from bioforge.adapters.registry import AdapterRegistry
from bioforge.models import AdapterMode, Investigation, Target, TargetProductProfile


def test_every_adapter_reports_a_mode_and_a_requirement(settings):
    for status in AdapterRegistry.build(settings).statuses():
        assert status.mode in set(AdapterMode)
        assert status.detail
        if status.mode is not AdapterMode.LIVE:
            assert status.requirement, f"{status.name} must say how to go live"


def test_unconfigured_adapters_report_fixture_not_live(settings):
    registry = AdapterRegistry.build(settings)
    modes = {s.name: s.mode for s in registry.statuses()}
    assert modes["paperclip"] is AdapterMode.FIXTURE
    assert modes["tamarind"] is AdapterMode.FIXTURE
    assert modes["modal"] is AdapterMode.FIXTURE
    # Biomni has no automated interface in this build and says so rather than
    # pretending to be a fixture integration.
    assert modes["biomni"] is AdapterMode.IMPORT_HANDOFF


async def test_paperclip_serves_fixture_evidence_with_fixture_provenance(settings):
    adapter = PaperclipAdapter(settings)
    items, prov = await adapter.gather_evidence(Target(name="VEGF-A"))
    assert items
    assert prov.mode is AdapterMode.FIXTURE
    assert prov.note and "not retrieved by a live" in prov.note
    assert all(item.provenance.mode is AdapterMode.FIXTURE for item in items)


async def test_live_failure_degrades_visibly_rather_than_silently(settings, monkeypatch):
    """A configured adapter whose call fails must return FIXTURE plus the reason."""
    settings.paperclip_api_key = "test-key"
    settings.paperclip_api_url = "https://example.invalid/search"
    adapter = PaperclipAdapter(settings)
    assert adapter.configured

    async def boom(*args, **kwargs):
        raise httpx.ConnectError("name resolution failed")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)

    items, prov = await adapter.gather_evidence(Target(name="VEGF-A"))
    assert prov.mode is AdapterMode.FIXTURE, "must never report live after a failure"
    assert "Live call failed" in (prov.note or "")
    assert "ConnectError" in (prov.note or "")
    assert items, "degradation still returns usable data"
    assert adapter.status().last_error


async def test_model_hub_refuses_a_non_independent_comparison(settings, monkeypatch):
    """Gate 2 is worthless if both predictions come from the same model family."""
    settings.benchling_model_hub_url = "https://example.invalid/hub"
    settings.benchling_api_key = "test-key"
    adapter = BenchlingModelHubAdapter(settings)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model_version": "tamarind-fixture/design-v1",
                "model_agreement": 0.99,
                "epitope_rmsd_angstrom": 0.1,
            }

    async def post(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", post)

    record = by_id("BF-001")
    metrics, prov = await adapter.structure_agreement(record)
    # It degrades rather than accepting a same-family agreement of 0.99.
    assert prov.mode is AdapterMode.FIXTURE
    assert "would not be independent" in (prov.note or "")
    assert metrics["model_agreement"] != 0.99


def test_model_hub_states_its_independence_claim(settings):
    note = BenchlingModelHubAdapter(settings).independence_note()
    assert "different family" in note
    assert "not evidence that either is right" in note


async def test_benchling_refuses_to_write_without_approval(settings):
    settings.benchling_tenant = "acme"
    settings.benchling_api_key = "key"
    settings.benchling_project_id = "proj"
    adapter = BenchlingAdapter(settings)
    investigation = Investigation(
        id="run_test",
        target=Target(name="VEGF-A"),
        target_product_profile=TargetProductProfile(),
    )
    with pytest.raises(AdapterError, match="without explicit human approval"):
        await adapter.write_records(investigation, approved=False)


async def test_benchling_unconfigured_writes_only_to_the_local_store(settings):
    adapter = BenchlingAdapter(settings)
    investigation = Investigation(
        id="run_test",
        target=Target(name="VEGF-A"),
        target_product_profile=TargetProductProfile(),
    )
    records, prov = await adapter.write_records(investigation, approved=True)
    assert prov.mode is AdapterMode.FIXTURE
    assert "nothing was sent to a Benchling tenant" in (prov.note or "")
    assert records == []


def test_biomni_generates_an_actionable_task_prompt(settings):
    adapter = BiomniAdapter(settings)
    prompt, prov = adapter.task_prompt("run_0001", Target(name="VEGF-A", uniprot_id="P15692"))
    assert prov.mode is AdapterMode.IMPORT_HANDOFF
    assert "run_0001" in prompt
    assert "P15692" in prompt
    assert "findings" in prompt


def test_biomni_import_marks_uncited_findings_as_predicted(settings):
    adapter = BiomniAdapter(settings)
    items, prov = adapter.parse_import(
        "run_0001",
        {
            "analysis_version": "biomni/1.2.3",
            "findings": [
                {
                    "claim": "Cited finding",
                    "evidence_level": "reported",
                    "source_url": "https://example.org/x",
                },
                {"claim": "Uncited finding", "evidence_level": "reported"},
            ],
        },
    )
    assert prov.mode is AdapterMode.IMPORT_HANDOFF
    assert prov.model_version == "biomni/1.2.3"
    assert items[0].evidence_level == "reported"
    # No citation means it cannot be presented as a report of anything.
    assert items[1].evidence_level == "predicted"


def test_fixture_candidates_are_synthetic_and_labelled_as_such():
    from bioforge.adapters.fixtures import candidates_fixture

    assert "not real therapeutic sequences" in candidates_fixture()["sequence_disclaimer"]
    assert len(candidate_records()) == 16


def test_tamarind_separates_computed_metrics_from_predicted_ones(settings):
    from bioforge.adapters.tamarind_adapter import TamarindAdapter

    adapter = TamarindAdapter(settings)
    metrics, computed_prov, model_prov = adapter.developability_metrics(by_id("BF-001"))
    # The sequence-derived half is genuinely computed on every run.
    assert computed_prov.tool == "bioforge.biophysics"
    assert computed_prov.mode is AdapterMode.LIVE
    assert "heuristics" in (computed_prov.note or "")
    # The model-derived half is fixture data and admits it.
    assert model_prov.mode is AdapterMode.FIXTURE
    assert set(metrics) >= {"surface_hydrophobicity", "predicted_tm_celsius"}
