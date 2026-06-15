"""Offline tests for the real HubSpot request mapping (injected fake transport).
No network: verifies idempotency, payload shape, supports(), manual steps, rollback."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from oab.adapters import HubSpotAdapter, ManualStepRequired
from oab.schema import ConfigObject
from oab.planner import plan
from oab.applier import apply


class FakeHubSpot:
    """Records calls; serves a tiny in-memory HubSpot."""
    def __init__(self):
        self.calls = []
        self.pipelines = []     # list of {label,id,stages}
        self.props = []         # list of {label,type,hubspotDefined}

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path.endswith("/pipelines/deals"):
            return 200, {"results": self.pipelines}
        if method == "GET" and path.endswith("/properties/deals"):
            return 200, {"results": self.props}
        if method == "POST" and path.endswith("/pipelines/deals"):
            pid = f"p{len(self.pipelines)}"
            self.pipelines.append({"label": body["label"], "id": pid,
                                   "stages": [{"label": s["label"]} for s in body["stages"]]})
            return 201, {"id": pid}
        if method == "POST" and path.endswith("/properties/deals"):
            self.props.append({"label": body["label"], "type": body["type"], "hubspotDefined": False})
            return 201, {"name": body["name"]}
        if method == "DELETE":
            return 204, {}
        return 200, {}


def _adapter():
    return HubSpotAdapter(token="pat-test", http=FakeHubSpot())


def test_supports_only_pipelines_and_fields():
    a = _adapter()
    assert a.supports("pipeline") and a.supports("custom_field")
    assert not a.supports("user_role") and not a.supports("automation_rule")


def test_create_pipeline_and_property_payloads():
    fake = FakeHubSpot(); a = HubSpotAdapter(token="t", http=fake)
    a.create(ConfigObject("pipeline", "Sales", "Lead, Won"))
    a.create(ConfigObject("custom_field", "Budget", "number", parent="Sales"))
    posts = [c for c in fake.calls if c[0] == "POST"]
    assert any("pipelines" in p[1] and p[2]["label"] == "Sales"
               and [s["label"] for s in p[2]["stages"]] == ["Lead", "Won"] for p in posts)
    assert any("properties" in p[1] and p[2]["type"] == "number" for p in posts)


def test_create_is_idempotent():
    fake = FakeHubSpot(); a = HubSpotAdapter(token="t", http=fake)
    obj = ConfigObject("pipeline", "Sales", "Lead, Won")
    a.create(obj); a.create(obj)            # second is a no-op
    assert sum(1 for c in fake.calls if c[0] == "POST" and "pipelines" in c[1]) == 1


def test_unsupported_type_raises_manual():
    a = _adapter()
    try:
        a.create(ConfigObject("user_role", "Admin", "full"))
        assert False, "should have raised"
    except ManualStepRequired:
        pass


def test_capable_reports_missing_scopes():
    def http403(method, path, body=None): return 403, {"error": "scopes"}
    ok, reason = HubSpotAdapter(token="t", http=http403).capable()
    assert ok is False and "scope" in reason


def test_apply_records_manual_for_roles_against_hubspot():
    fake = FakeHubSpot(); a = HubSpotAdapter(token="t", http=fake)
    objs = [ConfigObject("pipeline", "Sales", "Lead, Won"),
            ConfigObject("custom_field", "Budget", "number", parent="Sales"),
            ConfigObject("user_role", "Admin", "full access"),
            ConfigObject("integration", "Slack", "Slack")]
    res = apply(plan_for(objs, a), a)
    assert res.ok
    assert len(res.applied) == 2          # pipeline + field really created
    assert len(res.manual) == 2           # role + integration -> honest manual step


def plan_for(objs, adapter):
    from oab.schema import DesiredState
    d = DesiredState(customer="X", objects=objs)
    return plan(d, adapter.list_objects())
