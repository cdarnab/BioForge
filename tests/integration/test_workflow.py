"""End-to-end workflow behaviour, determinism, provenance, and failure handling."""

from __future__ import annotations

import pytest

from bioforge.adapters.registry import AdapterRegistry
from bioforge.engine.audit import EventBus
from bioforge.engine.state_machine import MAIN_SEQUENCE
from bioforge.engine.workflow import WorkflowRunner
from bioforge.models import AdapterMode, WorkflowState
from bioforge.store import Store
from tests.conftest import DEMO_TARGET

# -- the seeded demo narrative ---------------------------------------------


async def test_seeded_demo_produces_the_documented_narrative(completed_run):
    inv = completed_run
    assert inv.status is WorkflowState.COMPLETED

    by_gate: dict[str, list[str]] = {}
    for candidate in inv.candidates:
        failed = next((g.gate for g in candidate.gates if not g.passed), None)
        if failed:
            by_gate.setdefault(failed, []).append(candidate.id)

    assert len(by_gate["binding"]) == 6
    assert len(by_gate["independent_structure"]) == 3
    assert len(by_gate["developability"]) == 2
    assert len(by_gate["robustness"]) == 2
    assert len(inv.finalists()) == 3
    # 16 generated plus exactly one redesign.
    assert len(inv.candidates) == 17
    assert sum(1 for c in inv.candidates if c.parent_id) == 1


async def test_at_least_one_rejection_of_each_kind_is_explained(completed_run):
    seen_codes = set()
    for candidate in completed_run.candidates:
        if candidate.status == "rejected":
            assert candidate.decision.summary, f"{candidate.id} was rejected without a reason"
            seen_codes.update(candidate.decision.reason_codes)
    assert {
        "BIND_LOW_CONFIDENCE",
        "STRUCT_DISAGREEMENT",
        "DEV_MULTIPLE_LIABILITIES",
    } <= seen_codes
    assert seen_codes & {"ROBUST_MUTATION_FRAGILE", "ROBUST_DECOY_BINDING"}


async def test_redesign_improves_its_target_without_improving_everything(completed_run):
    child = next(c for c in completed_run.candidates if c.parent_id)
    parent = completed_run.candidate(child.parent_id)
    assert parent is not None and parent.status == "rejected"

    def value(candidate, metric):
        test = candidate.metric(metric)
        return test.value if test else None

    # The liability it was built to fix actually improved.
    assert value(child, "aggregation_propensity") < value(parent, "aggregation_propensity")
    assert value(child, "surface_hydrophobicity") < value(parent, "surface_hydrophobicity")
    # And something got worse, because a redesign that improves everything is a
    # sign the scoring is not honest.
    degraded = [
        m
        for m in ("interface_confidence", "predicted_tm_celsius", "model_agreement")
        if value(child, m) < value(parent, m)
    ]
    assert degraded, "the redesign improved every metric, which is not credible"


async def test_redesign_reruns_every_gate_not_just_the_failed_one(completed_run):
    child = next(c for c in completed_run.candidates if c.parent_id)
    assert {g.gate for g in child.gates} == {
        "binding",
        "independent_structure",
        "developability",
        "robustness",
    }


async def test_only_one_redesign_iteration_is_permitted(runner, profile):
    inv = runner.create(DEMO_TARGET, profile)
    await runner.run_all(inv.id)
    before = len(runner.store.load(inv.id).candidates)
    await runner.redesign(inv.id)
    assert len(runner.store.load(inv.id).candidates) == before


# -- state machine and audit ------------------------------------------------


async def test_run_pauses_for_a_human_before_the_challenge(runner, profile):
    inv = runner.create(DEMO_TARGET, profile)
    inv = await runner.run_to_validation(inv.id)
    assert inv.status is WorkflowState.INDEPENDENT_VALIDATION
    assert not inv.challenge_run
    assert "press Challenge Survivors" in inv.status_detail


async def test_every_state_transition_is_audited(runner, profile, store):
    inv = runner.create(DEMO_TARGET, profile)
    await runner.run_all(inv.id)
    events = store.events(inv.id)
    transitions = [e.next_state for e in events if e.kind == "state_transition"]
    for state in MAIN_SEQUENCE:
        assert state in transitions, f"{state} was never recorded"


async def test_audit_log_is_append_only(runner, profile, store):
    inv = runner.create(DEMO_TARGET, profile)
    await runner.run_to_validation(inv.id)
    events = store.events(inv.id)
    assert events

    with pytest.raises(ValueError, match="append-only"):
        store.append_event(events[0])

    # Sequence numbers are dense and ordered.
    assert [e.seq for e in events] == list(range(1, len(events) + 1))


async def test_audit_events_record_tool_mode_and_seed(runner, profile, store):
    inv = runner.create(DEMO_TARGET, profile)
    await runner.run_all(inv.id)
    tool_calls = [e for e in store.events(inv.id) if e.kind == "tool_call"]
    assert tool_calls
    for event in tool_calls:
        assert event.tool
        assert event.mode is not None
        # A non-live tool call must carry the warning explaining the mode.
        if event.mode is not AdapterMode.LIVE:
            assert event.warning


async def test_challenge_is_attributed_to_the_human_who_pressed_it(runner, profile, store):
    inv = runner.create(DEMO_TARGET, profile)
    await runner.run_to_validation(inv.id)
    await runner.challenge(inv.id)
    challenge_events = [
        e for e in store.events(inv.id) if e.next_state is WorkflowState.ADVERSARIAL_CHALLENGE
    ]
    assert challenge_events and challenge_events[0].actor == "human"


# -- provenance -------------------------------------------------------------


async def test_every_score_carries_provenance(completed_run):
    for candidate in completed_run.candidates:
        assert candidate.tests, f"{candidate.id} has no measurements"
        for test in candidate.tests:
            assert test.provenance.tool
            assert test.provenance.mode in set(AdapterMode)
            assert test.model_version


async def test_no_score_claims_to_be_live_in_fixture_mode(completed_run):
    """The one exception is genuinely in-process computation, which IS live."""
    for candidate in completed_run.candidates:
        for test in candidate.tests:
            if test.provenance.mode is AdapterMode.LIVE:
                assert test.provenance.tool == "bioforge.biophysics", (
                    f"{test.metric} on {candidate.id} claims live mode from "
                    f"{test.provenance.tool} with no credentials configured"
                )


async def test_fixture_scores_explain_that_they_are_fixtures(completed_run):
    fixture_tests = [
        t
        for c in completed_run.candidates
        for t in c.tests
        if t.provenance.mode is AdapterMode.FIXTURE
    ]
    assert fixture_tests
    assert all(t.provenance.note for t in fixture_tests)


async def test_evidence_separates_observation_from_prediction(completed_run):
    levels = {e.evidence_level for e in completed_run.evidence}
    assert "observed" in levels
    assert "predicted" in levels
    for item in completed_run.evidence:
        assert item.provenance.tool
        if item.evidence_level != "predicted":
            assert item.source_title


async def test_contradicting_evidence_is_present_and_kept(completed_run):
    contradictions = [e for e in completed_run.evidence if e.support == "contradicts"]
    assert len(contradictions) >= 2
    assert completed_run.narrative["evidence_contradiction"]


# -- hypotheses -------------------------------------------------------------


async def test_hypotheses_are_resolved_against_their_falsification_criteria(completed_run):
    assert completed_run.hypotheses
    for hypothesis in completed_run.hypotheses:
        assert hypothesis.falsification_criteria
        assert hypothesis.status in ("survives", "rejected", "uncertain", "testing")
        assert hypothesis.result_summary


# -- artifacts --------------------------------------------------------------


async def test_package_contains_every_required_artifact(completed_run, store):
    kinds = {a.kind for a in completed_run.artifacts}
    assert {"report_md", "report_json", "csv_scores", "csv_plate"} <= kinds
    for artifact in completed_run.artifacts:
        found = store.get_artifact(artifact.id)
        assert found is not None
        _, content = found
        assert content.strip()


async def test_dossier_leads_with_the_prediction_caveat(completed_run, store):
    markdown = next(
        content
        for artifact in completed_run.artifacts
        if artifact.kind == "report_md"
        for _, content in [store.get_artifact(artifact.id)]
    )
    header = markdown[:2500]
    assert "computational predictions, not experimental results" in header
    assert "uncalibrated demonstration" in markdown
    assert "Limitations" in markdown


async def test_score_csv_row_count_matches_the_measurements(completed_run, store):
    csv_content = next(
        content
        for artifact in completed_run.artifacts
        if artifact.kind == "csv_scores"
        for _, content in [store.get_artifact(artifact.id)]
    )
    rows = [line for line in csv_content.strip().split("\n") if line]
    expected = sum(len(c.tests) for c in completed_run.candidates)
    assert len(rows) == expected + 1  # header


async def test_plate_map_carries_controls(completed_run, store):
    csv_content = next(
        content
        for artifact in completed_run.artifacts
        if artifact.kind == "csv_plate"
        for _, content in [store.get_artifact(artifact.id)]
    )
    assert "positive_control" in csv_content
    assert "negative_control" in csv_content
    assert "buffer_blank" in csv_content


# -- determinism ------------------------------------------------------------


async def _run_once(tmp_path, settings, name: str):
    store = Store(f"sqlite:///{tmp_path / name}.db")
    runner = WorkflowRunner(store, EventBus(), AdapterRegistry.build(settings), settings)
    from bioforge.models import TargetProductProfile

    inv = runner.create(
        DEMO_TARGET, TargetProductProfile(max_candidates=16, max_finalists=3), mode="fixture"
    )
    return await runner.run_all(inv.id)


def _signature(investigation):
    return [
        (
            c.id,
            c.status,
            c.rank,
            c.rank_score,
            tuple(sorted(c.decision.reason_codes)),
            tuple((t.metric, t.value, t.passed) for t in c.tests),
        )
        for c in sorted(investigation.candidates, key=lambda c: c.id)
    ]


async def test_two_identical_runs_produce_identical_results(tmp_path, settings):
    first = await _run_once(tmp_path, settings, "a")
    second = await _run_once(tmp_path, settings, "b")
    assert _signature(first) == _signature(second)


async def test_seed_is_recorded_even_though_fixtures_ignore_it(tmp_path, settings, store):
    runner = WorkflowRunner(store, EventBus(), AdapterRegistry.build(settings), settings)
    from bioforge.models import TargetProductProfile

    inv = runner.create(DEMO_TARGET, TargetProductProfile(), mode="fixture", seed=999)
    assert inv.seed == 999
    inv = await runner.run_all(inv.id)
    assert inv.seed == 999
    challenge_tests = [t for c in inv.candidates for t in c.tests if t.tool == "modal"]
    assert challenge_tests
    assert all(t.provenance.random_seed == 999 for t in challenge_tests)


# -- failure behaviour ------------------------------------------------------


async def test_tool_failure_moves_the_run_to_FAILED_and_records_it(
    runner, profile, store, monkeypatch
):
    inv = runner.create(DEMO_TARGET, profile)

    async def explode(*args, **kwargs):
        raise RuntimeError("structure service exploded")

    monkeypatch.setattr(runner.registry.tamarind, "generate_candidates", explode)

    with pytest.raises(RuntimeError, match="exploded"):
        await runner.run_to_validation(inv.id)

    reloaded = store.load(inv.id)
    assert reloaded.status is WorkflowState.FAILED
    assert "exploded" in (reloaded.error or "")
    errors = [e for e in store.events(inv.id) if e.kind == "error"]
    assert errors and "exploded" in (errors[0].error or "")


async def test_failure_does_not_fabricate_results(runner, profile, store, monkeypatch):
    inv = runner.create(DEMO_TARGET, profile)

    async def explode(*args, **kwargs):
        raise RuntimeError("model hub down")

    monkeypatch.setattr(runner.registry.model_hub, "structure_agreement", explode)
    with pytest.raises(RuntimeError):
        await runner.run_to_validation(inv.id)

    reloaded = store.load(inv.id)
    # No candidate may carry an independent-structure verdict that never ran.
    for candidate in reloaded.candidates:
        assert not any(t.metric == "model_agreement" for t in candidate.tests), (
            "a failed gate must leave no measurement behind"
        )


# -- durability -------------------------------------------------------------


async def test_a_run_survives_being_reloaded_from_a_new_store(tmp_path, settings):
    url = f"sqlite:///{tmp_path / 'durable.db'}"
    store = Store(url)
    runner = WorkflowRunner(store, EventBus(), AdapterRegistry.build(settings), settings)
    from bioforge.models import TargetProductProfile

    inv = runner.create(DEMO_TARGET, TargetProductProfile(max_candidates=16, max_finalists=3))
    await runner.run_to_validation(inv.id)

    # Simulate a process restart: brand new store and runner over the same file.
    reopened = Store(url)
    resumed = WorkflowRunner(reopened, EventBus(), AdapterRegistry.build(settings), settings)
    loaded = reopened.load(inv.id)
    assert loaded.status is WorkflowState.INDEPENDENT_VALIDATION
    assert len(loaded.candidates) == 16

    finished = await resumed.run_all(inv.id) if False else await resumed.challenge(inv.id)
    assert finished.challenge_run
    assert reopened.events(inv.id)[-1].seq == len(reopened.events(inv.id))


# -- benchling approval -----------------------------------------------------


async def test_benchling_write_requires_explicit_approval(completed_run, runner, store):
    assert not completed_run.benchling.approved
    inv = await runner.request_benchling_write(completed_run.id)
    assert inv.benchling.requested
    assert not inv.benchling.written
    assert inv.benchling.records

    inv = await runner.approve_benchling_write(completed_run.id, "Dr Approver")
    assert inv.benchling.approved
    assert inv.benchling.approved_by == "Dr Approver"
    # Unconfigured means the write went to the local store only.
    assert inv.benchling.write_mode is AdapterMode.FIXTURE
    assert not inv.benchling.written

    approvals = [e for e in store.events(completed_run.id) if e.kind == "human_action"]
    assert any("approved by Dr Approver" in e.summary for e in approvals)


async def test_benchling_records_are_labelled_as_predictions(completed_run, runner):
    inv = await runner.request_benchling_write(completed_run.id)
    assert inv.benchling.records
    for record in inv.benchling.records:
        assert record["schema_fields"]["status"] == "computationally_prioritised_not_validated"
        for result in record["prediction_results"]:
            assert result["result_type"] == "in_silico_prediction"
