from __future__ import annotations

import pytest

from bioforge.adapters.registry import AdapterRegistry
from bioforge.config import Settings
from bioforge.engine.audit import EventBus
from bioforge.engine.decision_policy import load_policy
from bioforge.engine.workflow import WorkflowRunner
from bioforge.models import Target, TargetProductProfile
from bioforge.store import Store

DEMO_TARGET = Target(
    name="VEGF-A",
    uniprot_id="P15692",
    pdb_id="1BJ1",
    epitope_description="Receptor-binding region at the poles of the VEGF-A homodimer.",
)


@pytest.fixture
def settings(tmp_path) -> Settings:
    s = Settings()
    s.demo_pace_ms = 0
    s.artifact_dir = tmp_path / "artifacts"
    s.artifact_dir.mkdir(parents=True, exist_ok=True)
    # Guarantee fixture mode regardless of the developer's environment. Tests
    # must never reach a network or a locally installed CLI.
    for field in (
        "anthropic_api_key",
        "paperclip_api_key",
        "tamarind_api_key",
        "tamarind_api_url",
        "benchling_tenant",
        "benchling_api_key",
        "benchling_project_id",
        "benchling_model_hub_url",
        "modal_validator_url",
    ):
        setattr(s, field, "")
    # Paperclip is a real CLI that may well be installed on the developer's
    # machine; disable it explicitly rather than relying on it being absent.
    s.paperclip_enabled = False
    s.paperclip_bin = str(tmp_path / "no-such-paperclip")
    s.paperclip_cache_ttl_s = 0
    return s


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture
def registry(settings) -> AdapterRegistry:
    return AdapterRegistry.build(settings)


@pytest.fixture
def policy():
    return load_policy()


@pytest.fixture
def runner(store, registry, settings, policy) -> WorkflowRunner:
    return WorkflowRunner(store, EventBus(), registry, settings, policy)


@pytest.fixture
def profile() -> TargetProductProfile:
    return TargetProductProfile(format="nanobody", max_candidates=16, max_finalists=3)


@pytest.fixture
async def completed_run(runner, profile):
    investigation = runner.create(DEMO_TARGET, profile, mode="fixture")
    return await runner.run_all(investigation.id)
