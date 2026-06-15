"""Contract-compliance tests for the FastAPI surface (SHARED_SITE_CONTRACT §4).
Offline: no LLM/HubSpot calls. Skips cleanly if fastapi isn't installed."""
import os, sys, importlib
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


def _client(mode, hubspot=False):
    os.environ["OAB_MODE"] = mode
    os.environ.pop("OAB_DEEPSEEK_KEY", None)      # force mock LLM -> deterministic, offline
    if hubspot:
        os.environ["OAB_HUBSPOT_TOKEN"] = "pat-test"
    else:
        os.environ.pop("OAB_HUBSPOT_TOKEN", None)
    import oab.api as api
    importlib.reload(api)
    return TestClient(api.app), api


def test_every_response_is_honestly_tagged():
    c, _ = _client("demo")
    r = c.post("/plan", json={"intake": "Customer: X\nPipelines:\n- P: a, b"})
    assert r.status_code == 200
    eng = r.json()["engine"]
    assert set(eng) >= {"llm", "sandbox", "real", "mode"}
    assert eng["real"] is False          # mock sandbox -> not real, stated plainly


def test_live_mode_refuses_to_serve_a_stand_in():
    c, _ = _client("live", hubspot=False)     # live but no real providers
    assert c.get("/health").status_code == 503
    r = c.post("/plan", json={"intake": "Customer: X\nPipelines:\n- P: a, b"})
    assert r.status_code == 503               # never presents a mock as live


def test_apply_requires_explicit_approval():
    c, _ = _client("demo")
    r = c.post("/apply", json={"intake": "Customer: X\nPipelines:\n- P: a, b", "approve": False})
    assert r.status_code == 412               # nothing mutates without approve=true


def test_health_does_not_require_llm_in_demo():
    c, _ = _client("demo")
    assert c.get("/health").status_code == 200
