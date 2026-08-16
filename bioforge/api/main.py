"""FastAPI application: REST surface plus the SSE progress stream."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..adapters.registry import AdapterRegistry
from ..config import ROOT, settings
from ..engine.audit import EventBus
from ..engine.decision_policy import load_policy
from ..engine.state_machine import MAIN_SEQUENCE, progress_fraction
from ..engine.workflow import WorkflowRunner
from ..models import Target, TargetProductProfile
from ..store import Store

log = logging.getLogger("bioforge")

DEMO_TARGET = Target(
    name="VEGF-A",
    uniprot_id="P15692",
    pdb_id="1BJ1",
    epitope_description=(
        "Receptor-binding region at the poles of the VEGF-A homodimer, overlapping the "
        "VEGFR-2 (KDR) interface. Composite surface contributed by both protomers."
    ),
)

app = FastAPI(
    title="BioForge Judge",
    version="0.1.0",
    description=(
        "Adversarial candidate triage for antibody and nanobody design. Every score this "
        "API returns is a computational prediction, never an experimental result."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = Store()
bus = EventBus()
registry = AdapterRegistry.build(settings)
runner = WorkflowRunner(store, bus, registry, settings, load_policy())

#: Background tasks per run, so a second start cannot race the first.
_tasks: dict[str, asyncio.Task] = {}


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class CreateInvestigation(BaseModel):
    target_name: str = Field(default="VEGF-A")
    uniprot_id: str | None = "P15692"
    pdb_id: str | None = "1BJ1"
    epitope_description: str = DEMO_TARGET.epitope_description
    format: str = "nanobody"
    max_candidates: int = 16
    max_finalists: int = 3
    mode: str = "fixture"
    seed: int | None = None


class ApproveBenchling(BaseModel):
    approver: str = Field(min_length=1, description="Name of the human approving the write.")
    confirm: bool = Field(
        default=False,
        description="Must be true. Present so an accidental POST cannot write to a tenant.",
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _load(run_id: str):
    inv = store.load(run_id)
    if inv is None:
        raise HTTPException(status_code=404, detail=f"investigation {run_id} not found")
    return inv


def _spawn(run_id: str, coro_factory) -> None:
    existing = _tasks.get(run_id)
    if existing and not existing.done():
        raise HTTPException(status_code=409, detail="a phase is already running for this run")

    async def guarded():
        try:
            await coro_factory()
        except Exception:  # already recorded as a FAILED transition by the runner
            log.exception("workflow task failed for %s", run_id)

    _tasks[run_id] = asyncio.create_task(guarded())


# --------------------------------------------------------------------------
# Meta
# --------------------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "app_mode": settings.app_mode,
        "policy_version": runner.policy.version,
        "seed": settings.random_seed,
        "integrations": [s.model_dump(mode="json") for s in registry.statuses()],
        "any_live": any(s.mode.value == "live" for s in registry.statuses()),
    }


@app.get("/api/integrations")
async def integrations() -> list[dict[str, Any]]:
    return [s.model_dump(mode="json") for s in registry.statuses()]


@app.get("/api/policy")
async def policy() -> dict[str, Any]:
    return runner.policy.as_dict()


@app.get("/api/workflow")
async def workflow_states() -> dict[str, Any]:
    return {
        "sequence": [s.value for s in MAIN_SEQUENCE],
        "escalations": ["NEEDS_REVIEW", "FAILED"],
    }


# --------------------------------------------------------------------------
# Investigations
# --------------------------------------------------------------------------


@app.post("/api/investigations", status_code=201)
async def create_investigation(body: CreateInvestigation) -> dict[str, Any]:
    target = Target(
        name=body.target_name,
        uniprot_id=body.uniprot_id,
        pdb_id=body.pdb_id,
        epitope_description=body.epitope_description,
    )
    profile = TargetProductProfile(
        format=body.format,  # type: ignore[arg-type]
        max_candidates=body.max_candidates,
        max_finalists=body.max_finalists,
    )
    inv = runner.create(target, profile, mode=body.mode, seed=body.seed)
    return inv.model_dump(mode="json")


@app.get("/api/investigations")
async def list_investigations() -> list[dict[str, Any]]:
    return store.list_runs()


@app.get("/api/investigations/{run_id}")
async def get_investigation(run_id: str) -> dict[str, Any]:
    inv = _load(run_id)
    payload = inv.model_dump(mode="json")
    payload["progress"] = progress_fraction(inv.status)
    payload["running"] = bool(_tasks.get(run_id) and not _tasks[run_id].done())
    return payload


@app.post("/api/investigations/{run_id}/start")
async def start(run_id: str) -> dict[str, Any]:
    inv = _load(run_id)
    if inv.status.value != "CREATED":
        raise HTTPException(status_code=409, detail=f"run already started ({inv.status.value})")
    _spawn(run_id, lambda: runner.run_to_validation(run_id))
    return {"ok": True, "run_id": run_id, "streaming": True}


@app.post("/api/investigations/{run_id}/challenge")
async def challenge(run_id: str) -> dict[str, Any]:
    inv = _load(run_id)
    if inv.challenge_run:
        raise HTTPException(status_code=409, detail="challenge already run")
    _spawn(run_id, lambda: runner.challenge(run_id))
    return {"ok": True, "run_id": run_id}


@app.post("/api/investigations/{run_id}/redesign")
@app.post("/api/investigations/{run_id}/redesign/{candidate_id}")
async def redesign(run_id: str, candidate_id: str | None = None) -> dict[str, Any]:
    inv = _load(run_id)
    if inv.redesign_run:
        raise HTTPException(
            status_code=409, detail="this MVP permits exactly one redesign iteration"
        )
    _spawn(run_id, lambda: runner.redesign(run_id, candidate_id))
    return {"ok": True, "run_id": run_id, "candidate_id": candidate_id}


@app.post("/api/investigations/{run_id}/finalize")
async def finalize(run_id: str) -> dict[str, Any]:
    _load(run_id)
    _spawn(run_id, lambda: runner.finalise(run_id))
    return {"ok": True, "run_id": run_id}


# --------------------------------------------------------------------------
# Sub-resources
# --------------------------------------------------------------------------


@app.get("/api/investigations/{run_id}/evidence")
async def evidence(run_id: str) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json") for e in _load(run_id).evidence]


@app.get("/api/investigations/{run_id}/hypotheses")
async def hypotheses(run_id: str) -> list[dict[str, Any]]:
    return [h.model_dump(mode="json") for h in _load(run_id).hypotheses]


@app.get("/api/investigations/{run_id}/candidates")
async def candidates(run_id: str) -> list[dict[str, Any]]:
    return [c.model_dump(mode="json") for c in _load(run_id).candidates]


@app.get("/api/investigations/{run_id}/audit")
async def audit(run_id: str) -> list[dict[str, Any]]:
    _load(run_id)
    return [e.model_dump(mode="json") for e in store.events(run_id)]


@app.get("/api/investigations/{run_id}/dossier")
async def dossier(run_id: str) -> dict[str, Any]:
    inv = _load(run_id)
    from ..engine import packaging

    return {
        "markdown": packaging.dossier_markdown(inv, runner.policy, store.events(run_id)),
        "finalists": [c.model_dump(mode="json") for c in inv.finalists()],
        "artifacts": [a.model_dump(mode="json") for a in inv.artifacts],
        "benchling": inv.benchling.model_dump(mode="json"),
        "redesign_delta": inv.narrative.get("redesign_delta", ""),
    }


@app.get("/api/investigations/{run_id}/artifacts")
async def artifacts(run_id: str) -> list[dict[str, Any]]:
    return [a.model_dump(mode="json") for a in _load(run_id).artifacts]


@app.get("/api/investigations/{run_id}/artifacts/{artifact_id}")
async def artifact(run_id: str, artifact_id: str, download: bool = True) -> Response:
    _load(run_id)
    found = store.get_artifact(artifact_id)
    if found is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    meta, content = found
    if meta["run_id"] != run_id:
        raise HTTPException(status_code=404, detail="artifact does not belong to this run")
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{meta["filename"]}"'
    return Response(content=content, media_type=meta["media_type"], headers=headers)


# --------------------------------------------------------------------------
# Benchling human approval
# --------------------------------------------------------------------------


@app.post("/api/investigations/{run_id}/request-benchling-write")
async def request_benchling(run_id: str) -> dict[str, Any]:
    inv = await runner.request_benchling_write(run_id)
    return inv.benchling.model_dump(mode="json")


@app.post("/api/investigations/{run_id}/approve-benchling-write")
async def approve_benchling(run_id: str, body: ApproveBenchling) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="confirm must be true — this endpoint can write to a live Benchling tenant",
        )
    inv = await runner.approve_benchling_write(run_id, body.approver)
    return inv.benchling.model_dump(mode="json")


# --------------------------------------------------------------------------
# Import handoff
# --------------------------------------------------------------------------


@app.post("/api/investigations/{run_id}/import/biomni")
async def import_biomni(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _load(run_id)
    if "findings" not in payload:
        raise HTTPException(
            status_code=400,
            detail="expected a Biomni export with a top-level 'findings' array",
        )
    inv = runner.import_biomni(run_id, payload)
    return {"imported": len(payload["findings"]), "evidence_total": len(inv.evidence)}


# --------------------------------------------------------------------------
# SSE
# --------------------------------------------------------------------------


@app.get("/api/investigations/{run_id}/events")
async def stream(run_id: str, request: Request) -> EventSourceResponse:
    inv = _load(run_id)
    queue = bus.subscribe(run_id)

    async def generator():
        try:
            # Replay current state first so a late subscriber is never blank.
            yield {
                "event": "message",
                "data": json.dumps(
                    {
                        "type": "snapshot",
                        "investigation": inv.model_dump(mode="json"),
                        "progress": progress_fraction(inv.status),
                    }
                ),
            }
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {"event": "message", "data": json.dumps(payload, default=str)}
        finally:
            bus.unsubscribe(run_id, queue)

    return EventSourceResponse(generator())


# --------------------------------------------------------------------------
# Seeded demo
# --------------------------------------------------------------------------


@app.post("/api/demo/seed", status_code=201)
async def seed_demo(autostart: bool = True) -> dict[str, Any]:
    """One call that sets up the VEGF-A demo exactly as the demo script expects."""
    inv = runner.create(
        DEMO_TARGET,
        TargetProductProfile(format="nanobody", max_candidates=16, max_finalists=3),
        mode="fixture",
    )
    if autostart:
        _spawn(inv.id, lambda: runner.run_to_validation(inv.id))
    return {"run_id": inv.id, "autostart": autostart}


# --------------------------------------------------------------------------
# Static UI
# --------------------------------------------------------------------------

_DIST = ROOT / "web" / "dist"
if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = _DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")

else:  # pragma: no cover - dev convenience only

    @app.get("/")
    async def no_ui() -> JSONResponse:
        return JSONResponse(
            {
                "message": (
                    "API is running but the UI has not been built. Run `make build-web`, "
                    "or start the Vite dev server with `make dev-web`."
                ),
                "api_docs": "/docs",
                "health": "/api/health",
            }
        )
