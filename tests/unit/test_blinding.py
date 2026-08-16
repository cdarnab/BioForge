"""The benchmark must not be able to leak its answer key into the scoring path.

Blinding here is a structural property of the import graph, so it is tested that
way rather than by inspecting behaviour: if a scoring module ever imports the
labels, this fails.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "bioforge"

#: Modules allowed to touch ground-truth control labels.
ALLOWED = {
    Path("bioforge/adapters/fixtures.py"),  # defines the loader
    Path("bioforge/benchmark/harness.py"),  # joins labels AFTER scoring
}

FORBIDDEN_TOKENS = ("benchmark_labels", "benchmark_labels.json", "control_role")


def python_files() -> list[Path]:
    return sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)


def test_scoring_path_never_references_the_labels():
    offenders = []
    for path in python_files():
        relative = path.relative_to(ROOT)
        if relative in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{relative} references {token!r}")
    assert not offenders, "labels leaked into the scoring path:\n" + "\n".join(offenders)


def test_decision_policy_imports_nothing_from_the_benchmark():
    tree = ast.parse((PACKAGE / "engine" / "decision_policy.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "benchmark" not in node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "benchmark" not in alias.name


def test_workflow_imports_nothing_from_the_benchmark():
    tree = ast.parse((PACKAGE / "engine" / "workflow.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "benchmark" not in node.module


def test_candidate_fixture_carries_no_control_labels():
    """A label smuggled into the candidate file would defeat the separation."""
    payload = json.loads(
        (ROOT / "data" / "fixtures" / "vegfa_candidates.json").read_text(encoding="utf-8")
    )
    blob = json.dumps(payload).lower()
    for word in ("positive_control", "negative_control", "shuffled_cdr_negative", "ground_truth"):
        assert word not in blob, f"{word!r} leaked into the candidate fixture"


def test_labels_file_exists_and_names_its_controls():
    labels = json.loads(
        (ROOT / "data" / "fixtures" / "benchmark_labels.json").read_text(encoding="utf-8")
    )
    assert labels["expected_positive"]
    assert len(labels["expected_negative"]) >= 3
    assert set(labels["expected_positive"]).isdisjoint(labels["expected_negative"])


@pytest.mark.parametrize("module", ["decision_policy", "workflow", "packaging"])
def test_engine_modules_import_without_the_labels_loaded(module):
    """Importing the engine must not pull the answer key into memory."""
    import importlib

    imported = importlib.import_module(f"bioforge.engine.{module}")
    assert not hasattr(imported, "benchmark_labels")
