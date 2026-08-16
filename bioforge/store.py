"""Durable storage.

Two tables carry the durability guarantee:

`runs` holds the serialised `Investigation` and is overwritten on each save, so
a restarted process can pick an investigation back up at whatever state it had
reached.

`audit_events` is append-only. Nothing in this module offers an update or delete
for it. That is the property the dossier's audit trail rests on, so it is
enforced here rather than by convention.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import DateTime, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings
from .models import AuditEvent, Investigation


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    payload: Mapped[str] = mapped_column(Text)


class AuditRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    seq: Mapped[int] = mapped_column()
    payload: Mapped[str] = mapped_column(Text)


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    filename: Mapped[str] = mapped_column(String)
    media_type: Mapped[str] = mapped_column(String)
    payload: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)


class Store:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or settings.database_url
        connect_args = {"check_same_thread": False} if self.url.startswith("sqlite") else {}
        self.engine = create_engine(self.url, future=True, connect_args=connect_args)
        Base.metadata.create_all(self.engine)
        self._session = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)
        self._seq_lock = threading.Lock()

    # -- investigations ---------------------------------------------------

    def save(self, investigation: Investigation) -> None:
        payload = investigation.model_dump_json()
        with self._session() as session:
            row = session.get(RunRow, investigation.id)
            if row is None:
                row = RunRow(
                    id=investigation.id, status=investigation.status.value, payload=payload
                )
                session.add(row)
            else:
                row.status = investigation.status.value
                row.payload = payload
            session.commit()

    def load(self, run_id: str) -> Investigation | None:
        with self._session() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                return None
            return Investigation.model_validate_json(row.payload)

    def next_run_id(self) -> str:
        """Sequential and collision-free across process restarts."""
        with self._session() as session:
            existing = session.execute(select(RunRow.id)).scalars().all()
        highest = 0
        for run_id in existing:
            suffix = run_id.rsplit("_", 1)[-1]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        return f"run_{highest + 1:04d}"

    def list_runs(self) -> list[dict]:
        with self._session() as session:
            rows = session.execute(select(RunRow).order_by(RunRow.created_at.desc())).scalars()
            out = []
            for row in rows:
                data = json.loads(row.payload)
                out.append(
                    {
                        "id": row.id,
                        "status": row.status,
                        "target": data.get("target", {}).get("name"),
                        "mode": data.get("mode"),
                        "created_at": data.get("created_at"),
                        "candidates": len(data.get("candidates", [])),
                    }
                )
            return out

    # -- audit (append-only) ----------------------------------------------

    def next_seq(self, run_id: str) -> int:
        with self._seq_lock, self._session() as session:
            current = session.execute(
                select(func.max(AuditRow.seq)).where(AuditRow.run_id == run_id)
            ).scalar()
            return int(current or 0) + 1

    def append_event(self, event: AuditEvent) -> AuditEvent:
        """The only write path for audit events. There is deliberately no update."""
        if event.seq == 0:
            event.seq = self.next_seq(event.run_id)
        if not event.id:
            event.id = f"{event.run_id}-evt-{event.seq:04d}"
        with self._session() as session:
            existing = session.get(AuditRow, event.id)
            if existing is not None:
                raise ValueError(
                    f"audit event {event.id} already exists; the audit log is append-only"
                )
            session.add(
                AuditRow(
                    id=event.id,
                    run_id=event.run_id,
                    seq=event.seq,
                    payload=event.model_dump_json(),
                )
            )
            session.commit()
        return event

    def events(self, run_id: str) -> list[AuditEvent]:
        with self._session() as session:
            rows = session.execute(
                select(AuditRow).where(AuditRow.run_id == run_id).order_by(AuditRow.seq)
            ).scalars()
            return [AuditEvent.model_validate_json(r.payload) for r in rows]

    # -- artifacts --------------------------------------------------------

    def put_artifact(self, artifact, content: str) -> None:
        with self._session() as session:
            session.merge(
                ArtifactRow(
                    id=artifact.id,
                    run_id=artifact.run_id,
                    filename=artifact.filename,
                    media_type=artifact.media_type,
                    payload=artifact.model_dump_json(),
                    content=content,
                )
            )
            session.commit()

    def get_artifact(self, artifact_id: str) -> tuple[dict, str] | None:
        with self._session() as session:
            row = session.get(ArtifactRow, artifact_id)
            if row is None:
                return None
            return json.loads(row.payload), row.content

    def artifacts_for(self, run_id: str) -> Iterable[dict]:
        with self._session() as session:
            rows = session.execute(
                select(ArtifactRow).where(ArtifactRow.run_id == run_id)
            ).scalars()
            return [json.loads(r.payload) for r in rows]
