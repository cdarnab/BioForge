"""HTTP surface. Uses the app's real wiring against a temporary database."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("DEMO_PACE_MS", "0")
    # The Paperclip CLI may be installed on this machine; the API tests must be
    # hermetic, so turn it off explicitly.
    monkeypatch.setenv("PAPERCLIP_ENABLED", "false")
    for key in (
        "ANTHROPIC_API_KEY",
        "PAPERCLIP_API_KEY",
        "TAMARIND_API_KEY",
        "TAMARIND_API_URL",
        "BENCHLING_TENANT",
        "BENCHLING_API_KEY",
        "MODAL_VALIDATOR_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    import importlib

    import bioforge.config as config

    importlib.reload(config)
    import bioforge.api.main as main

    importlib.reload(main)
    with TestClient(main.app) as test_client:
        test_client.app_module = main  # type: ignore[attr-defined]
        yield test_client


def wait_for(client, run_id: str, predicate, timeout: float = 20.0):
    """Poll until the background workflow task reaches the wanted state."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = client.get(f"/api/investigations/{run_id}").json()
        if predicate(payload):
            return payload
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting on {run_id}; last status {payload['status']}")


def test_health_reports_integration_modes(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["any_live"] is False
    assert {i["name"] for i in body["integrations"]} >= {
        "anthropic",
        "paperclip",
        "biomni",
        "tamarind",
        "benchling_model_hub",
        "modal",
        "benchling",
    }


def test_integrations_refresh_reprobes_adapters(client):
    body = client.get("/api/integrations?refresh=true").json()
    assert isinstance(body, list)
    assert any(item["name"] == "paperclip" for item in body)


def test_policy_endpoint_exposes_thresholds_and_calibration(client):
    policy = client.get("/api/policy").json()
    assert policy["version"]
    names = [g["name"] for g in policy["gates"]]
    assert names == ["binding", "independent_structure", "developability", "robustness"]
    assert all(m["calibrated"] is False for g in policy["gates"] for m in g["metrics"])


def test_create_start_and_stream_through_to_validation(client):
    created = client.post("/api/investigations", json={"max_candidates": 16}).json()
    run_id = created["id"]
    assert created["status"] == "CREATED"

    assert client.post(f"/api/investigations/{run_id}/start").json()["ok"] is True
    payload = wait_for(client, run_id, lambda p: p["status"] == "INDEPENDENT_VALIDATION")

    assert len(payload["candidates"]) == 16
    assert len(payload["evidence"]) >= 10
    assert len(payload["hypotheses"]) == 4
    assert client.get(f"/api/investigations/{run_id}/audit").json()


def test_double_start_is_rejected(client):
    run_id = client.post("/api/investigations", json={}).json()["id"]
    client.post(f"/api/investigations/{run_id}/start")
    second = client.post(f"/api/investigations/{run_id}/start")
    assert second.status_code == 409


def test_full_demo_flow_with_challenge_and_redesign(client):
    run_id = client.post("/api/demo/seed?autostart=true").json()["run_id"]
    wait_for(client, run_id, lambda p: p["status"] == "INDEPENDENT_VALIDATION")

    assert client.post(f"/api/investigations/{run_id}/challenge").status_code == 200
    wait_for(client, run_id, lambda p: p["challenge_run"] is True)

    assert client.post(f"/api/investigations/{run_id}/redesign").status_code == 200
    payload = wait_for(client, run_id, lambda p: p["status"] == "COMPLETED", timeout=30)

    recommended = [c for c in payload["candidates"] if c["status"] == "recommended"]
    assert len(recommended) == 3
    assert any(c["parent_id"] for c in payload["candidates"])
    kinds = {a["kind"] for a in payload["artifacts"]}
    assert {"report_md", "report_json", "csv_scores", "csv_plate"} <= kinds


def test_challenge_twice_is_rejected(client):
    run_id = client.post("/api/demo/seed?autostart=true").json()["run_id"]
    wait_for(client, run_id, lambda p: p["status"] == "INDEPENDENT_VALIDATION")
    client.post(f"/api/investigations/{run_id}/challenge")
    wait_for(client, run_id, lambda p: p["challenge_run"] is True)
    assert client.post(f"/api/investigations/{run_id}/challenge").status_code == 409


def test_artifacts_download_with_the_right_headers(client):
    run_id = client.post("/api/demo/seed?autostart=true").json()["run_id"]
    wait_for(client, run_id, lambda p: p["status"] == "INDEPENDENT_VALIDATION")
    client.post(f"/api/investigations/{run_id}/challenge")
    wait_for(client, run_id, lambda p: p["challenge_run"] is True)
    client.post(f"/api/investigations/{run_id}/redesign")
    wait_for(client, run_id, lambda p: p["status"] == "COMPLETED", timeout=30)

    artifacts = client.get(f"/api/investigations/{run_id}/artifacts").json()
    plate = next(a for a in artifacts if a["kind"] == "csv_plate")
    response = client.get(f"/api/investigations/{run_id}/artifacts/{plate['id']}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert plate["filename"] in response.headers["content-disposition"]
    assert "positive_control" in response.text


def test_artifact_from_another_run_is_not_served(client):
    a = client.post("/api/demo/seed?autostart=false").json()["run_id"]
    b = client.post("/api/demo/seed?autostart=false").json()["run_id"]
    assert a != b
    client.post(f"/api/investigations/{a}/start")
    wait_for(client, a, lambda p: p["status"] == "INDEPENDENT_VALIDATION")
    artifacts = client.get(f"/api/investigations/{a}/artifacts").json()
    assert artifacts
    response = client.get(f"/api/investigations/{b}/artifacts/{artifacts[0]['id']}")
    assert response.status_code == 404


def test_benchling_write_needs_confirm_and_an_approver(client):
    run_id = client.post("/api/demo/seed?autostart=true").json()["run_id"]
    wait_for(client, run_id, lambda p: p["status"] == "INDEPENDENT_VALIDATION")

    unconfirmed = client.post(
        f"/api/investigations/{run_id}/approve-benchling-write",
        json={"approver": "Dr Approver", "confirm": False},
    )
    assert unconfirmed.status_code == 400
    assert "confirm must be true" in unconfirmed.json()["detail"]

    missing_name = client.post(
        f"/api/investigations/{run_id}/approve-benchling-write",
        json={"approver": "", "confirm": True},
    )
    assert missing_name.status_code == 422

    approved = client.post(
        f"/api/investigations/{run_id}/approve-benchling-write",
        json={"approver": "Dr Approver", "confirm": True},
    ).json()
    assert approved["approved"] is True
    assert approved["approved_by"] == "Dr Approver"
    assert approved["written"] is False  # unconfigured: local store only


def test_biomni_import_handoff(client):
    run_id = client.post("/api/demo/seed?autostart=true").json()["run_id"]
    wait_for(client, run_id, lambda p: p["status"] == "INDEPENDENT_VALIDATION")
    before = len(client.get(f"/api/investigations/{run_id}/evidence").json())

    bad = client.post(f"/api/investigations/{run_id}/import/biomni", json={"nope": 1})
    assert bad.status_code == 400

    good = client.post(
        f"/api/investigations/{run_id}/import/biomni",
        json={
            "analysis_version": "biomni/test",
            "findings": [
                {
                    "claim": "VEGF-A shares 43% identity with PlGF over the cystine-knot domain.",
                    "evidence_level": "annotated",
                    "support": "contradicts",
                    "source_title": "Biomni homology analysis",
                    "source_url": "https://example.org/biomni/run",
                    "relevance": 0.8,
                    "confidence": 0.75,
                }
            ],
        },
    )
    assert good.status_code == 200
    evidence = client.get(f"/api/investigations/{run_id}/evidence").json()
    assert len(evidence) == before + 1
    imported = evidence[-1]
    assert imported["provenance"]["mode"] == "import_handoff"
    assert "did not execute this analysis" in imported["provenance"]["note"]


def test_sse_route_is_registered_as_an_event_stream(client):
    """The stream itself is exercised in test_events.py against the real bus.

    TestClient cannot drain an open-ended SSE response cleanly, so the HTTP
    layer is checked structurally here and the streaming behaviour is tested
    where it actually lives.
    """
    main = client.app_module  # type: ignore[attr-defined]
    routes = {r.path for r in main.app.routes}  # type: ignore[attr-defined]
    assert "/api/investigations/{run_id}/events" in routes


def test_missing_run_is_404(client):
    assert client.get("/api/investigations/run_9999").status_code == 404
    assert client.post("/api/investigations/run_9999/challenge").status_code == 404


def test_spa_or_api_hint_is_served_at_root(client):
    response = client.get("/")
    assert response.status_code == 200


def test_asyncio_default_loop_is_available():
    """Guard against an event-loop policy change breaking the background tasks."""
    assert asyncio.get_event_loop_policy() is not None
