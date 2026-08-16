#!/usr/bin/env python3
"""Run the retrospective benchmark across several seeds and write a report.

python scripts/run_benchmark.py --seeds 1 2 3 --out artifacts/benchmark.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bioforge.benchmark.harness import run_benchmark  # noqa: E402
from bioforge.config import settings  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "benchmark.json"))
    args = parser.parse_args()

    settings.demo_pace_ms = 0
    results = []
    for seed in args.seeds:
        result = await run_benchmark(
            seed, settings=settings, include_ablations=seed == args.seeds[0]
        )
        results.append(result.as_dict())
        print(
            f"seed {seed:>4}  positive-control rank {result.positive_control_rank}  "
            f"AUROC {result.auroc}  top-1 enrichment {result.top_k_enrichment[1]}  "
            f"{result.runtime_seconds:.2f}s"
        )

    first = results[0]
    identical = all(
        r["ranking"] == first["ranking"] and r["shortlist"] == first["shortlist"] for r in results
    )

    print()
    print("=== summary ===")
    print(f"seeds run                : {args.seeds}")
    print(f"identical across seeds   : {identical}")
    if identical:
        print(
            "  (expected — fixture data is seed-invariant by construction. The seed is "
            "recorded in provenance and only changes results once a stochastic live "
            "adapter is configured.)"
        )
    print(f"positive-control rank    : {first['positive_control_rank']} of {len(first['ranking'])}")
    print(f"negative-control ranks   : {first['negative_control_ranks']}")
    print(f"AUROC (pos vs neg)       : {first['auroc']}")
    print(f"top-k enrichment         : {first['top_k_enrichment']}")
    print(f"shortlist                : {first['shortlist']}")
    print(f"approx cost              : ${first['approximate_cost_usd']}  — {first['cost_note']}")
    print()
    print("rejections by gate:")
    for gate, ids in sorted(first["gate_rejections"].items()):
        print(f"  {gate:<24} {len(ids):>2}  {', '.join(ids)}")
    print()
    print("ablations (each policy replayed over the same stored raw metrics):")
    baseline = first["ablations"]["_baseline"]
    print(
        f"  full policy                  {baseline['shortlist']}  "
        f"({baseline['total_rejected']} rejected)"
    )
    for name, data in first["ablations"].items():
        if name.startswith("_"):
            continue
        flag = "top-3 CHANGED" if data["shortlist_changed"] else "top-3 same"
        print(f"  {name:<28} {data['shortlist']}  ({data['total_rejected']} rejected)  [{flag}]")
        if data["escaped_rejection"]:
            print(
                f"      → {len(data['escaped_rejection'])} candidate(s) the full policy "
                f"rejected now survive: {', '.join(data['escaped_rejection'])}"
            )
        if data["negative_controls_promoted"]:
            print(
                f"      ⚠ known negative controls among them: {data['negative_controls_promoted']}"
            )

    single = first["ablations"]["_single_model_score"]
    print()
    print("single-model-score baseline (no gates at all — the thing this product beats):")
    print(f"  top-{len(single['shortlist'])} by interface_confidence: {single['shortlist']}")
    for cid, info in single["picks_the_full_pipeline_rejected"].items():
        print(
            f"      ⚠ {cid} would have gone to the bench, but the full pipeline rejected it "
            f"at the {info['gate']} gate ({', '.join(info['metrics_failed'])})"
        )
    if not single["picks_the_full_pipeline_rejected"]:
        print("      (no difference on this fixture set)")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "seeds": args.seeds,
                "identical_across_seeds": identical,
                "results": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
