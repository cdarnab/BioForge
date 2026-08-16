"""Immutable audit recording plus the live event bus that feeds SSE.

Writing an audit event and publishing it to subscribers are the same call, so a
transition can never appear in the UI without also being durably recorded.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from typing import Any

from ..models import AdapterMode, AuditEvent, Provenance, WorkflowState
from ..store import Store


class EventBus:
    """Fan-out to every open SSE connection for a run."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._subscribers[run_id].add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        self._subscribers[run_id].discard(queue)
        if not self._subscribers[run_id]:
            self._subscribers.pop(run_id, None)

    def publish(self, run_id: str, payload: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(run_id, ())):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

    def subscriber_count(self, run_id: str) -> int:
        return len(self._subscribers.get(run_id, ()))


class Auditor:
    def __init__(self, store: Store, bus: EventBus, run_id: str) -> None:
        self.store = store
        self.bus = bus
        self.run_id = run_id

    def record(
        self,
        kind: str,
        summary: str,
        *,
        actor: str = "system",
        prev_state: WorkflowState | None = None,
        next_state: WorkflowState | None = None,
        tool: str | None = None,
        provenance: Provenance | None = None,
        input_artifact_ids: list[str] | None = None,
        output_artifact_ids: list[str] | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
        warning: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> AuditEvent:
        mode: AdapterMode | None = provenance.mode if provenance else None
        event = AuditEvent(
            run_id=self.run_id,
            kind=kind,  # type: ignore[arg-type]
            actor=actor,
            summary=summary,
            prev_state=prev_state,
            next_state=next_state,
            tool=tool or (provenance.tool if provenance else None),
            mode=mode,
            model_version=provenance.model_version if provenance else None,
            parameters=parameters or (provenance.parameters if provenance else {}),
            random_seed=provenance.random_seed if provenance else None,
            input_artifact_ids=input_artifact_ids or [],
            output_artifact_ids=output_artifact_ids or [],
            duration_ms=duration_ms,
            error=error,
            # A degraded adapter always carries a note; surface it as a warning
            # so the audit trail shows the fallback rather than burying it.
            warning=warning
            or (
                provenance.note
                if provenance and provenance.note and mode is not AdapterMode.LIVE
                else None
            ),
        )
        self.store.append_event(event)
        self.bus.publish(self.run_id, {"type": "audit", "event": event.model_dump(mode="json")})
        return event

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        """Publish a UI-only event. Not persisted — use `record` for anything auditable."""
        self.bus.publish(self.run_id, {"type": event_type, **payload})
