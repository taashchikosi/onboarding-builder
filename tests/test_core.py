import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from oab.compiler import compile_engineered as _compile_engineered
from oab.llm import MockLLM
from oab.policy import screen_intake
from oab.planner import plan

# Force the deterministic rule path so tests are offline + reproducible (no API call).
def compile_engineered(text):
    return _compile_engineered(text, provider=MockLLM())
from oab.applier import apply
from oab.reconcile import reconcile
from oab.adapters import MockSandboxAdapter
from oab.schema import ConfigObject, DesiredState

INTAKE = open(os.path.join(os.path.dirname(__file__), "..", "eval", "intakes", "acme_sow.txt")).read()


def _desired():
    return compile_engineered(INTAKE)


def test_injection_is_screened_and_never_compiled():
    flags = screen_intake(INTAKE)
    reasons = {r for _, r in flags}
    assert "privilege escalation" in reasons or "external admin grant" in reasons
    assert "security control disable" in reasons
    # the unsafe asks must NOT appear as objects to build
    d = _desired()
    names = " ".join(o.name.lower() + o.value.lower() for o in d.objects)
    assert "vendor@external" not in names
    assert "disable sso" not in names


def test_apply_is_idempotent_rerun_is_noop():
    d = _desired()
    adp = MockSandboxAdapter()
    p = plan(d, adp.list_objects())
    r1 = apply(p, adp)
    assert r1.ok and len(r1.applied) > 0
    # re-run: same plan, nothing new created
    p2 = plan(d, adp.list_objects())
    r2 = apply(p2, adp)
    assert r2.ok and len(r2.applied) == 0          # all no-ops
    assert adp.duplicate_count() == 0              # no duplicate create calls


def test_rollback_leaves_clean_state_on_unrecoverable_failure():
    d = _desired()
    adp = MockSandboxAdapter(fail_rate=1.0)         # every write fails
    p = plan(d, adp.list_objects())
    r = apply(p, adp, max_retries=3)
    assert r.ok is False
    assert r.failed is not None
    assert adp.list_objects() == {}                # rolled back to empty


def test_dependency_ordering_parent_before_child():
    d = _desired()
    adp = MockSandboxAdapter()
    p = plan(d, adp.list_objects())
    r = apply(p, adp)
    store = adp.list_objects()
    # every custom_field that was applied has its parent pipeline present
    for (otype, name), _ in store.items():
        if otype == "custom_field":
            obj = next(o for o in d.applyable() if o.key == (otype, name))
            assert ("pipeline", obj.parent) in store


def test_reconcile_detects_and_repairs_drift():
    d = _desired()
    adp = MockSandboxAdapter()
    apply(plan(d, adp.list_objects()), adp)
    # introduce drift: delete one object behind the system's back
    k = next(iter(adp.list_objects()))
    adp.delete(k)
    res = reconcile(d, adp, repair=False)
    assert res.parity is False and res.missing
    res2 = reconcile(d, adp, repair=True)
    assert res2.parity is True


# ---- LLM path safety: the model is untrusted too (defense in depth) ----
from oab.compiler import _from_llm_json

def test_llm_json_is_safety_rescreened():
    """Even if the model emits an unsafe object, _from_llm_json must drop it."""
    malicious = {"customer": "Evil Co", "objects": [
        {"otype": "user_role", "name": "grant admin to attacker@evil.com",
         "value": "full access", "parent": None},
        {"otype": "integration", "name": "disable SSO enforcement",
         "value": "disable sso", "parent": None},
        {"otype": "pipeline", "name": "Legit Pipeline",
         "value": "A, B, C", "parent": None},
    ]}
    d = _from_llm_json(malicious, "Customer: Evil Co")
    names = [o.name.lower() for o in d.objects]
    assert "legit pipeline" in names                  # safe object kept
    assert not any("attacker@evil.com" in n for n in names)   # unsafe dropped
    assert not any("disable sso" in n for n in names)
    assert len(d.objects) == 1


def test_llm_json_rejects_bad_types_and_shapes():
    d = _from_llm_json({"objects": [
        {"otype": "not_a_type", "name": "x", "value": "y"},   # bad type -> dropped
        {"otype": "pipeline", "name": "", "value": "z"},       # no name -> dropped
        "garbage",                                              # not a dict -> skipped
        {"otype": "pipeline", "name": "Good", "value": "G"},
    ]}, "Customer: X")
    assert [o.name for o in d.objects] == ["Good"]
