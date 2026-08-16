"""Live progress plumbing: the event bus that SSE connections read from."""

from __future__ import annotations

import asyncio

import pytest

from bioforge.engine.audit import Auditor, EventBus
from bioforge.models import AdapterMode, Provenance, WorkflowState
from tests.conftest import DEMO_TARGET


async def test_publish_reaches_every_subscriber():
    bus = EventBus()
    a = bus.subscribe("run_1")
    b = bus.subscribe("run_1")
    other = bus.subscribe("run_2")

    bus.publish("run_1", {"type": "test", "value": 1})

    assert (await a.get())["value"] == 1
    assert (await b.get())["value"] == 1
    assert other.empty(), "events must not cross runs"


async def test_unsubscribe_stops_delivery():
    bus = EventBus()
    queue = bus.subscribe("run_1")
    bus.unsubscribe("run_1", queue)
    bus.publish("run_1", {"type": "test"})
    assert queue.empty()
    assert bus.subscriber_count("run_1") == 0


async def test_a_full_queue_never_blocks_the_workflow():
    """A stalled browser tab must not be able to wedge a run."""
    bus = EventBus()
    queue = bus.subscribe("run_1")
    for i in range(queue.maxsize + 50):
        bus.publish("run_1", {"type": "flood", "i": i})
    assert queue.full()
    # The point is that the loop above returned rather than hanging.


async def test_audit_record_writes_and_publishes_together(store):
    bus = EventBus()
    queue = bus.subscribe("run_x")
    auditor = Auditor(store, bus, "run_x")

    auditor.record(
        "state_transition",
        "moved on",
        prev_state=WorkflowState.CREATED,
        next_state=WorkflowState.EVIDENCE_GATHERING,
    )

    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert payload["type"] == "audit"
    assert payload["event"]["summary"] == "moved on"
    stored = store.events("run_x")
    assert len(stored) == 1 and stored[0].seq == 1


async def test_degraded_provenance_surfaces_as_a_warning(store):
    bus = EventBus()
    auditor = Auditor(store, bus, "run_y")
    auditor.record(
        "tool_call",
        "called a tool",
        provenance=Provenance(
            tool="paperclip",
            mode=AdapterMode.FIXTURE,
            note="Live call failed, served deterministic fixture instead: boom",
        ),
    )
    event = store.events("run_y")[0]
    assert event.warning and "Live call failed" in event.warning


async def test_a_live_call_carries_no_spurious_warning(store):
    bus = EventBus()
    auditor = Auditor(store, bus, "run_z")
    auditor.record(
        "tool_call",
        "called a tool",
        provenance=Provenance(tool="anthropic", mode=AdapterMode.LIVE, note="all good"),
    )
    assert store.events("run_z")[0].warning is None


async def test_workflow_emits_progress_events_for_the_ui(runner, profile):
    bus = runner.bus
    investigation = runner.create(DEMO_TARGET, profile)
    queue = bus.subscribe(investigation.id)

    await runner.run_to_validation(investigation.id)

    seen: set[str] = set()
    while not queue.empty():
        seen.add(queue.get_nowait()["type"])
    # Everything the five views bind to must actually arrive on the stream.
    assert {"investigation", "evidence", "hypothesis", "candidate", "audit"} <= seen


@pytest.mark.parametrize("count", [0, 1, 3])
async def test_subscriber_count_tracks_connections(count):
    bus = EventBus()
    queues = [bus.subscribe("run_n") for _ in range(count)]
    assert bus.subscriber_count("run_n") == count
    for queue in queues:
        bus.unsubscribe("run_n", queue)
    assert bus.subscriber_count("run_n") == 0
