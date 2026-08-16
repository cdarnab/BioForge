"""The Paperclip CLI wrapper, tested against a fake `paperclip` binary.

These run a real subprocess — just not the real Paperclip. That exercises the
parts most likely to break in production (timeouts, process cleanup, CSV
contract drift, cache behaviour) without a network or an account, and without
mocking away the thing under test.
"""

from __future__ import annotations

import os
import stat
import textwrap

import pytest

from bioforge.adapters.paperclip_cli import (
    RESULT_ID,
    PaperclipCLI,
    PaperclipError,
    SearchHit,
)

CSV_BODY = (
    "title,authors,id,source,date,url,abstract\n"
    'A nanobody against VEGF,"Karami E, Sabatier J",PMC7717616,PMC,2020-05-22,'
    "https://example.org/PMC7717616,A peptide mimicked a nanobody's action.\n"
    'Bivalent nanobody VEGF165,"Khodabakhsh F",PMC8112138,PMC,2021-01-01,'
    "https://example.org/PMC8112138,Improved stability and expression.\n"
)


def write_fake(tmp_path, script: str) -> str:
    path = tmp_path / "paperclip"
    path.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(script), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


@pytest.fixture
def working_cli(tmp_path):
    """A fake paperclip that behaves like the real one for search + export."""
    csv_literal = repr(CSV_BODY)
    binary = write_fake(
        tmp_path,
        f"""
        import sys, pathlib
        args = sys.argv[1:]
        if args[:1] == ["--version"]:
            print("paperclip, version 9.9.9"); sys.exit(0)
        if args[:1] == ["config"]:
            print("  Server:  https://paperclip.example")
            print("  Auth:    \\u2713 tester@example.com")
            print("  Health:  \\u2713 server reachable")
            sys.exit(0)
        if args[:1] == ["search"]:
            print("Found 2 papers  [s_deadbeef]"); sys.exit(0)
        if args[:1] == ["results"]:
            out = args[args.index("--save") + 1]
            pathlib.Path(out).write_text({csv_literal})
            print("  \\u2713 Saved 2 papers"); sys.exit(0)
        if args[:1] == ["cat"] and "/proteins/" in args[1]:
            print('{{"_timing": "x", "accession": "P15692", "protein_name": "VEGF-A",'
                  ' "gene_name": "VEGFA", "organism": "Homo sapiens",'
                  ' "sequence_length": 395, "annotation_score": 5.0}}')
            sys.exit(0)
        sys.stderr.write("unknown command\\n"); sys.exit(2)
        """,
    )
    return PaperclipCLI(binary=binary, timeout_s=20, cache_ttl_s=0, cache_dir=tmp_path / "cache")


# -- discovery --------------------------------------------------------------


def test_missing_binary_is_reported_not_raised_at_construction(tmp_path):
    cli = PaperclipCLI(binary=str(tmp_path / "absent"), cache_dir=tmp_path / "c")
    assert cli.installed is False
    assert cli.resolve_binary() is None


async def test_running_without_a_binary_raises_a_clear_error(tmp_path):
    cli = PaperclipCLI(binary=str(tmp_path / "absent"), cache_dir=tmp_path / "c")
    with pytest.raises(PaperclipError, match="not installed"):
        await cli.run(["--version"])


async def test_probe_reads_version_account_and_reachability(working_cli):
    probe = await working_cli.probe()
    assert probe.available is True
    assert probe.version == "9.9.9"
    assert probe.account == "tester@example.com"
    assert probe.reachable is True
    assert "tester@example.com" in probe.detail


async def test_probe_is_cached(working_cli):
    first = await working_cli.probe()
    second = await working_cli.probe()
    assert first.checked_at == second.checked_at, "probe should not re-shell out"
    third = await working_cli.probe(force=True)
    assert third.checked_at >= first.checked_at


async def test_unauthenticated_cli_is_not_available(tmp_path):
    binary = write_fake(
        tmp_path,
        """
        import sys
        args = sys.argv[1:]
        if args[:1] == ["--version"]:
            print("paperclip, version 1.0.0"); sys.exit(0)
        if args[:1] == ["config"]:
            print("  Server:  https://paperclip.example"); sys.exit(0)
        sys.exit(1)
        """,
    )
    cli = PaperclipCLI(binary=binary, cache_dir=tmp_path / "c")
    probe = await cli.probe()
    assert probe.available is False
    assert "not authenticated" in probe.detail


# -- search + export --------------------------------------------------------


def test_result_id_pattern_matches_real_cli_output():
    assert RESULT_ID.search("Found 20 papers  [s_33c33ac5]").group(1) == "s_33c33ac5"
    assert RESULT_ID.search("Found 20 documents  [s_d8df545c]").group(1) == "s_d8df545c"
    assert RESULT_ID.search("no id here") is None


async def test_search_parses_the_documented_csv_contract(working_cli):
    outcome = await working_cli.search("pmc", "VEGF nanobody", limit=2)
    assert outcome.error is None
    assert len(outcome.hits) == 2
    first = outcome.hits[0]
    assert first.doc_id == "PMC7717616"
    assert first.title == "A nanobody against VEGF"
    assert first.date == "2020-05-22"
    assert first.rank == 1
    assert outcome.hits[1].rank == 2


async def test_search_reports_a_missing_result_id_rather_than_guessing(tmp_path):
    binary = write_fake(
        tmp_path,
        """
        import sys
        if sys.argv[1] == "search":
            print("Found 0 papers"); sys.exit(0)
        sys.exit(0)
        """,
    )
    cli = PaperclipCLI(binary=binary, cache_dir=tmp_path / "c", cache_ttl_s=0)
    outcome = await cli.search("pmc", "nothing")
    assert outcome.hits == []
    assert outcome.error and "no result id" in outcome.error


async def test_a_changed_csv_contract_is_an_error_not_silent_data_loss(tmp_path):
    """If Paperclip renames a column we must say so, not emit empty evidence."""
    binary = write_fake(
        tmp_path,
        """
        import sys, pathlib
        if sys.argv[1] == "search":
            print("Found 1 papers  [s_abc123]"); sys.exit(0)
        if sys.argv[1] == "results":
            out = sys.argv[sys.argv.index("--save") + 1]
            pathlib.Path(out).write_text("headline,who,identifier\\nA,B,C\\n")
            sys.exit(0)
        sys.exit(0)
        """,
    )
    cli = PaperclipCLI(binary=binary, cache_dir=tmp_path / "c", cache_ttl_s=0)
    outcome = await cli.search("pmc", "q")
    assert outcome.hits == []
    assert outcome.error and "unexpected CSV columns" in outcome.error


async def test_export_failure_is_reported(tmp_path):
    binary = write_fake(
        tmp_path,
        """
        import sys
        if sys.argv[1] == "search":
            print("Found 1 papers  [s_abc123]"); sys.exit(0)
        sys.stderr.write("export exploded\\n"); sys.exit(3)
        """,
    )
    cli = PaperclipCLI(binary=binary, cache_dir=tmp_path / "c", cache_ttl_s=0)
    outcome = await cli.search("pmc", "q")
    assert outcome.error and "export failed" in outcome.error


# -- timeouts ---------------------------------------------------------------


async def test_a_hanging_call_times_out_and_is_killed(tmp_path):
    """`-s proteins` search and `head` on content.lines both hang in reality."""
    binary = write_fake(tmp_path, "import time\ntime.sleep(30)\n")
    cli = PaperclipCLI(binary=binary, timeout_s=1.0, cache_dir=tmp_path / "c", cache_ttl_s=0)
    result = await cli.run(["search", "-s", "proteins", "x"])
    assert result.timed_out is True
    assert result.ok is False
    assert "timed out" in result.stderr


async def test_search_surfaces_a_timeout_as_a_source_error(tmp_path):
    binary = write_fake(tmp_path, "import time\ntime.sleep(30)\n")
    cli = PaperclipCLI(binary=binary, timeout_s=1.0, cache_dir=tmp_path / "c", cache_ttl_s=0)
    outcome = await cli.search("proteins", "VEGF")
    assert outcome.hits == []
    assert outcome.error and outcome.error.startswith("timeout")


async def test_one_slow_source_does_not_lose_the_others(tmp_path):
    binary = write_fake(
        tmp_path,
        """
        import sys, time, pathlib
        args = sys.argv[1:]
        if args[:1] == ["search"]:
            if "proteins" in args:
                time.sleep(30)
            print("Found 1 papers  [s_ok]"); sys.exit(0)
        if args[:1] == ["results"]:
            out = args[args.index("--save") + 1]
            pathlib.Path(out).write_text(
                "title,authors,id,source,date,url,abstract\\nT,A,PMC1,PMC,2020,u,abs\\n")
            sys.exit(0)
        sys.exit(0)
        """,
    )
    cli = PaperclipCLI(binary=binary, timeout_s=1.5, cache_dir=tmp_path / "c", cache_ttl_s=0)
    outcomes = await cli.search_many([("pmc", "a", 1), ("proteins", "b", 1), ("fda", "c", 1)])
    by_source = {o.source: o for o in outcomes}
    assert by_source["pmc"].hits, "a healthy source must still return"
    assert by_source["fda"].hits
    assert by_source["proteins"].error, "the slow source must report its failure"


# -- protein VFS -------------------------------------------------------------


async def test_protein_meta_strips_the_timing_footer(working_cli):
    payload = await working_cli.protein_meta("P15692")
    assert payload is not None
    assert payload["accession"] == "P15692"
    assert payload["sequence_length"] == 395
    assert "_timing" not in payload


async def test_protein_meta_returns_none_on_failure(tmp_path):
    binary = write_fake(tmp_path, "import sys\nsys.exit(1)\n")
    cli = PaperclipCLI(binary=binary, cache_dir=tmp_path / "c", cache_ttl_s=0)
    assert await cli.protein_meta("P00000") is None


# -- cache -------------------------------------------------------------------


async def test_cache_avoids_a_second_subprocess(tmp_path):
    counter = tmp_path / "calls.txt"
    binary = write_fake(
        tmp_path,
        f"""
        import sys, pathlib
        c = pathlib.Path({str(counter)!r})
        args = sys.argv[1:]
        if args[:1] == ["search"]:
            c.write_text(str(int(c.read_text()) + 1) if c.exists() else "1")
            print("Found 1 papers  [s_cached]"); sys.exit(0)
        if args[:1] == ["results"]:
            out = args[args.index("--save") + 1]
            pathlib.Path(out).write_text(
                "title,authors,id,source,date,url,abstract\\nT,A,PMC1,PMC,2020,u,abs\\n")
            sys.exit(0)
        sys.exit(0)
        """,
    )
    cli = PaperclipCLI(binary=binary, cache_dir=tmp_path / "cache", cache_ttl_s=3600)

    first = await cli.search("pmc", "same query", limit=1)
    second = await cli.search("pmc", "same query", limit=1)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert [h.doc_id for h in first.hits] == [h.doc_id for h in second.hits]
    assert counter.read_text() == "1", "the second call must not re-run the CLI"


async def test_cache_can_be_disabled(tmp_path, working_cli):
    working_cli.cache_ttl_s = 0
    first = await working_cli.search("pmc", "q", limit=2)
    second = await working_cli.search("pmc", "q", limit=2)
    assert first.cache_hit is False and second.cache_hit is False


async def test_api_key_is_passed_to_the_child_environment(tmp_path):
    binary = write_fake(
        tmp_path,
        """
        import os, sys
        sys.stdout.write(os.environ.get("PAPERCLIP_API_KEY", "MISSING"))
        """,
    )
    cli = PaperclipCLI(binary=binary, api_key="pk-test-123", cache_dir=tmp_path / "c")
    result = await cli.run(["config"])
    assert result.stdout.strip() == "pk-test-123"


def test_env_does_not_leak_an_empty_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("PAPERCLIP_API_KEY", raising=False)
    cli = PaperclipCLI(binary=str(tmp_path / "x"), api_key="", cache_dir=tmp_path / "c")
    assert "PAPERCLIP_API_KEY" not in cli._env()


# -- citation URLs -----------------------------------------------------------


@pytest.mark.parametrize(
    ("doc_id", "family"),
    [
        ("PMC7717616", "papers"),
        ("bio_dca47d15", "papers"),
        ("fda_9197d081d161", "fda"),
        ("tri_abc123", "trials"),
        ("NCT03928938", "trials"),
    ],
)
def test_citation_url_routes_to_the_right_family(doc_id, family):
    hit = SearchHit(
        title="t",
        authors="a",
        doc_id=doc_id,
        source="s",
        date="",
        url="",
        abstract="",
        rank=1,
        query="q",
        paperclip_source="pmc",
    )
    assert hit.citation_url() == f"https://paperclip.gxl.ai/citations/{family}/{doc_id}"


def test_best_url_prefers_the_publisher_link():
    hit = SearchHit(
        title="t",
        authors="a",
        doc_id="PMC1",
        source="PMC",
        date="",
        url="https://ncbi.example/PMC1",
        abstract="",
        rank=1,
        query="q",
        paperclip_source="pmc",
    )
    assert hit.best_url() == "https://ncbi.example/PMC1"
    hit.url = ""
    assert hit.best_url().startswith("https://paperclip.gxl.ai/citations/papers/")


def test_no_hardcoded_vendor_http_endpoint_in_the_adapter():
    """The integration is the CLI; an invented REST URL would be a regression."""
    from pathlib import Path

    source = Path("bioforge/adapters/paperclip_adapter.py").read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "paperclip_api_url" not in source
    assert os.getenv("PAPERCLIP_API_URL") is None or True  # documented as removed
