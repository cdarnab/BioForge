"""Stable ID generation.

IDs are monotonic per-prefix within a process so that fixture runs are
byte-identical across replays. `reset_ids()` is called at the start of every
deterministic run and by the test suite.
"""

from __future__ import annotations

import itertools
import threading

_lock = threading.Lock()
_counters: dict[str, itertools.count] = {}


def reset_ids() -> None:
    with _lock:
        _counters.clear()


def new_id(prefix: str) -> str:
    with _lock:
        counter = _counters.get(prefix)
        if counter is None:
            counter = itertools.count(1)
            _counters[prefix] = counter
        n = next(counter)
    return f"{prefix}_{n:04d}"
