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


async def test_paperclip_serves_fixture_evidence_when_the_cli_is_absent(settings):
    adapter = PaperclipAdapter(settings)
    assert adapter.configured is False
    items, prov = await adapter.gather_evidence(Target(name="VEGF-A"))
    assert items
    assert prov.mode is AdapterMode.FIXTURE
    assert prov.note and "not retrieved by a live" in prov.note
    assert all(item.provenance.mode is AdapterMode.FIXTURE for item in items)


async def test_paperclip_disabled_flag_beats_an_installed_cli(settings, tmp_path):
    """PAPERCLIP_ENABLED=false must win even where the binary exists."""
    binary = tmp_path / "paperclip"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    settings.paperclip_bin = str(binary)

    settings.paperclip_enabled = True
    assert PaperclipAdapter(settings).configured is True

    settings.paperclip_enabled = False
    disabled = PaperclipAdapter(settings)
    assert disabled.configured is False
    assert "Disabled by PAPERCLIP_ENABLED" in disabled.status().detail


async def test_paperclip_unauthenticated_cli_falls_back_with_the_reason(settings, tmp_path):
    """Installed but signed out: fixture mode, and the reason is carried through."""
    binary = tmp_path / "paperclip"
    binary.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        '  --version) echo "paperclip, version 1.2.3";;\n'
        '  config) echo "  Server:  https://paperclip.example";;\n'
        "  *) exit 1;;\n"
        "esac\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    settings.paperclip_enabled = True
    settings.paperclip_bin = str(binary)

    adapter = PaperclipAdapter(settings)
    assert adapter.configured is True, "the binary is present"
    items, prov = await adapter.gather_evidence(Target(name="VEGF-A"))
    assert prov.mode is AdapterMode.FIXTURE, "must never claim live while signed out"
    assert "not authenticated" in (prov.note or "")
    assert items, "the run still gets usable evidence"


async def test_paperclip_live_cli_returns_cited_evidence(settings, tmp_path):
    """Authenticated CLI: live provenance, on-topic hits, and a scope caveat."""
    import stat
    import textwrap

    csv_body = (
        "title,authors,id,source,date,url,abstract\n"
        'A nanobody against VEGF,"Karami E",PMC7717616,PMC,2020-05-22,'
        "https://example.org/PMC7717616,A potent neutralizing nanobody against VEGF-A.\n"
        'VEGF trial terminated,"Smith J",NCT00000001,trials,2019-01-01,'
        "https://example.org/NCT00000001,Study terminated early due to lack of efficacy.\n"
    )
    script = textwrap.dedent(
        f"""
        import sys, pathlib
        args = sys.argv[1:]
        csv = {csv_body!r}
        if args[:1] == ["--version"]:
            print("paperclip, version 9.9.9"); sys.exit(0)
        if args[:1] == ["config"]:
            print("  Server:  https://paperclip.example")
            print("  Auth:    \\u2713 tester@example.com")
            print("  Health:  \\u2713 server reachable")
            sys.exit(0)
        if args[:1] == ["search"]:
            print("Found 2 papers  [s_live123]"); sys.exit(0)
        if args[:1] == ["results"]:
            out = args[args.index("--save") + 1]
            pathlib.Path(out).write_text(csv); sys.exit(0)
        if args[:1] == ["cat"] and "/proteins/" in args[1]:
            print('{{"accession": "P15692", "protein_name": "VEGF-A", "gene_name": "VEGFA",'
                  ' "organism": "Homo sapiens", "sequence_length": 395, "annotation_score": 5.0}}')
            sys.exit(0)
        sys.stderr.write("unknown command\\n"); sys.exit(2)
        """
    )
    binary = tmp_path / "paperclip"
    binary.write_text("#!/usr/bin/env python3\n" + script, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    settings.paperclip_enabled = True
    settings.paperclip_bin = str(binary)
    settings.paperclip_cache_ttl_s = 0
    settings.paperclip_max_results = 4

    adapter = PaperclipAdapter(settings)
    items, prov = await adapter.gather_evidence(
        Target(name="VEGF-A", uniprot_id="P15692", epitope_description="receptor pole")
    )

    assert prov.mode is AdapterMode.LIVE
    assert "contradiction probe" in (prov.note or "").lower()
    assert any(item.source_type == "database" for item in items)
    assert any(item.support == "supports" for item in items)
    assert any(item.support == "contradicts" for item in items)
    assert any(item.tool == "bioforge" for item in items), "scope caveat travels as evidence"
    assert all(
        item.provenance.mode is AdapterMode.LIVE for item in items if item.tool == "paperclip"
    )


def test_paperclip_filters_off_topic_hits():
    from bioforge.adapters.paperclip_adapter import mentions_target, target_aliases
    from bioforge.adapters.paperclip_cli import SearchHit

    aliases = target_aliases(Target(name="VEGF-A", uniprot_id="P15692"))
    assert "vegf" in aliases

    on_topic = SearchHit(
        title="Smartphone CBT for depression",
        authors="",
        doc_id="NCT1",
        source="trials",
        date="",
        url="",
        abstract="Trial terminated early.",
        rank=1,
        query="q",
        paperclip_source="trials/us",
    )
    assert mentions_target(on_topic, aliases) is False

    relevant = SearchHit(
        title="Anti-VEGF resistance mechanisms",
        authors="",
        doc_id="PMC2",
        source="PMC",
        date="",
        url="",
        abstract="",
        rank=1,
        query="q",
        paperclip_source="pmc",
    )
    assert mentions_target(relevant, aliases) is True


async def test_live_failure_degrades_visibly_rather_than_silently(settings, tmp_path, monkeypatch):
    """A working, authenticated CLI whose retrieval blows up must report FIXTURE."""
    binary = tmp_path / "paperclip"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    settings.paperclip_enabled = True
    settings.paperclip_bin = str(binary)
    adapter = PaperclipAdapter(settings)

    from bioforge.adapters.paperclip_cli import Probe

    async def healthy_probe(*args, **kwargs):
        return Probe(
            available=True,
            version="1.2.3",
            account="tester@example.com",
            server="https://paperclip.example",
            reachable=True,
            detail="Signed in as tester@example.com; server reachable.",
            checked_at=0.0,
        )

    async def boom(*args, **kwargs):
        raise RuntimeError("search subsystem exploded")

    monkeypatch.setattr(adapter.cli, "probe", healthy_probe)
    monkeypatch.setattr(adapter.cli, "search_many", boom)

    items, prov = await adapter.gather_evidence(Target(name="VEGF-A"))
    assert prov.mode is AdapterMode.FIXTURE, "must never report live after a failure"
    assert "Live call failed" in (prov.note or "")
    assert "RuntimeError" in (prov.note or "")
    assert items, "degradation still returns usable data"
    assert adapter.status().last_error


def test_paperclip_classifies_contradictions_conservatively():
    """Contradiction wins ties — a missed problem is worse than a flagged one."""
    from bioforge.adapters.paperclip_adapter import classify_support
    from bioforge.adapters.paperclip_cli import SearchHit

    def hit(title: str, abstract: str = "") -> SearchHit:
        return SearchHit(
            title=title,
            authors="",
            doc_id="PMC1",
            source="PMC",
            date="",
            url="",
            abstract=abstract,
            rank=1,
            query="q",
            paperclip_source="pmc",
        )

    assert classify_support(hit("Resistance to anti-VEGF therapy"))[0] == "contradicts"
    assert classify_support(hit("Trial terminated early"))[0] == "contradicts"
    assert classify_support(hit("A potent neutralizing nanobody"))[0] == "supports"
    assert classify_support(hit("Expression of a protein"))[0] == "context_only"
    # Both signals present → contradiction.
    assert classify_support(hit("Potent inhibitor with acquired resistance"))[0] == "contradicts"
    # The basis string travels with the label so provenance can record it.
    assert classify_support(hit("Resistance"))[1].startswith("keyword_heuristic")


def test_paperclip_query_plan_covers_the_required_sources():
    from bioforge.adapters.paperclip_adapter import build_contradiction_plan, build_query_plan

    target = Target(name="VEGF-A", uniprot_id="P15692", epitope_description="receptor pole")
    sources = {source for source, _, _ in build_query_plan(target, 6)}
    assert {"pmc", "fda", "trials/us"} <= sources

    probes = build_contradiction_plan(target, 3)
    assert probes, "the adapter must actively search for disconfirming evidence"
    joined = " ".join(query for _, query, _ in probes).lower()
    assert any(word in joined for word in ("resistance", "withdrawn", "terminated", "failed"))


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
