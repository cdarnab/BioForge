#!/usr/bin/env python3
"""Run the full seeded VEGF-A investigation with no server and no UI.

Useful for CI, for checking determinism, and for reading the dossier without a
browser. Writes every artifact to the artifact directory.

    python scripts/run_headless.py [--out artifacts/demo]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bioforge.adapters.registry import AdapterRegistry  # noqa: E402
from bioforge.api.main import DEMO_TARGET  # noqa: E402
from bioforge.config import settings  # noqa: E402
from bioforge.engine.audit import EventBus  # noqa: E402
from bioforge.engine.decision_policy import load_policy  # noqa: E402
from bioforge.engine.workflow import WorkflowRunner  # noqa: E402
from bioforge.models import TargetProductProfile  # noqa: E402
from bioforge.store import Store  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "demo"))
    parser.add_argument("--db", default="sqlite:///./bioforge.db")
    parser.add_argument("--pace", type=int, default=0, help="ms between steps")
    args = parser.parse_args()

    settings.demo_pace_ms = args.pace
    store = Store(args.db)
    bus = EventBus()
    registry = AdapterRegistry.build(settings)
    runner = WorkflowRunner(store, bus, registry, settings, load_policy())

    print("integration modes:")
    for status in registry.statuses():
        print(f"  {status.name:<22} {status.mode.value}")
    print()

    inv = runner.create(
        DEMO_TARGET,
        TargetProductProfile(format="nanobody", max_candidates=16, max_finalists=3),
        mode="fixture",
    )
    inv = await runner.run_all(inv.id)

    print(f"run          : {inv.id}")
    print(f"final state  : {inv.status.value}")
    print(f"candidates   : {len(inv.candidates)}")
    print(f"rejected     : {sum(1 for c in inv.candidates if c.status == 'rejected')}")
    print(f"advanced     : {sum(1 for c in inv.candidates if c.status == 'survives')}")
    print(f"recommended  : {len(inv.finalists())}")
    print()

    by_gate: dict[str, list[str]] = {}
    for candidate in inv.candidates:
        if candidate.status != "rejected":
            continue
        failed = next((g.gate for g in candidate.gates if not g.passed), "unknown")
        by_gate.setdefault(failed, []).append(candidate.id)
    print("rejections by gate:")
    for gate, ids in sorted(by_gate.items()):
        print(f"  {gate:<24} {len(ids):>2}  {', '.join(sorted(ids))}")
    print()

    print("shortlist:")
    for candidate in inv.finalists():
        origin = f" (redesign of {candidate.parent_id})" if candidate.parent_id else ""
        print(f"  #{candidate.rank}  {candidate.id}  score={candidate.rank_score}{origin}")
    print()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for artifact in inv.artifacts:
        found = store.get_artifact(artifact.id)
        if found is None:
            continue
        _, content = found
        (out / artifact.filename).write_text(content, encoding="utf-8")
    print(f"wrote {len(inv.artifacts)} artifacts to {out}")

    print(f"audit events : {len(store.events(inv.id))}")
    return 0 if inv.status.value == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
