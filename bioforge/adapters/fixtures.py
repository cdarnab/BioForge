"""Deterministic fixture store shared by every adapter's fixture path.

Loaded once and cached. Nothing here consults the network, the clock, or a
random number generator, so two runs of the seeded demo produce byte-identical
scores.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from ..config import FIXTURE_DIR


@lru_cache(maxsize=1)
def candidates_fixture() -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / "vegfa_candidates.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def evidence_fixture() -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / "vegfa_evidence.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def hypotheses_fixture() -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / "vegfa_hypotheses.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def benchmark_labels() -> dict[str, Any]:
    """Ground-truth control labels.

    Deliberately NOT imported by any scoring path. `tests/unit/test_blinding.py`
    asserts that the only modules referencing this function are the benchmark
    harness and the tests themselves.
    """
    return json.loads((FIXTURE_DIR / "benchmark_labels.json").read_text(encoding="utf-8"))


def candidate_records() -> list[dict[str, Any]]:
    return list(candidates_fixture()["candidates"])


def redesign_record() -> dict[str, Any]:
    return dict(candidates_fixture()["redesign"])


def by_id(cid: str) -> dict[str, Any] | None:
    for record in candidate_records():
        if record["id"] == cid:
            return record
    redesign = redesign_record()
    return redesign if redesign["id"] == cid else None
