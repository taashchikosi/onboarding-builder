"""Workspace adapters.

MockSandboxAdapter — credential-free, in-memory stand-in for a CRM sandbox API.
HubSpotAdapter     — REAL HubSpot CRM provisioning for the cleanly API-creatable
                     object types: pipelines (POST /crm/v3/pipelines/deals) and
                     custom deal properties (POST /crm/v3/properties/deals).
                     Roles / automations / integrations are NOT cleanly private-app
                     provisionable, so the adapter declares it does not `support`
                     them and the applier records them as MANUAL steps (honest, §4).

The HTTP layer is injectable (`http=`) so the request mapping is unit-tested
offline; the default transport is urllib (no third-party deps).
"""
import json
import urllib.request
import urllib.error


class WorkspaceAdapter:
    def list_objects(self): raise NotImplementedError
    def create(self, obj):  raise NotImplementedError
    def update(self, obj):  raise NotImplementedError
    def delete(self, key):  raise NotImplementedError
    def supports(self, otype): return True            # mock supports everything
    def normalize(self, otype, value): return value   # vocab canonicalisation (per-target)


class TransientError(Exception):
    pass


class ManualStepRequired(Exception):
    """Raised for object types a target can't auto-provision (-> manual step)."""


# ----------------------------- MOCK -----------------------------
import random

class MockSandboxAdapter(WorkspaceAdapter):
    def __init__(self, fail_rate=0.0, seed=0):
        self.store = {}
        self.create_calls = {}
        self.fail_rate = fail_rate
        self.rng = random.Random(seed)

    def _maybe_fail(self):
        if self.rng.random() < self.fail_rate:
            raise TransientError("sandbox API 5xx / timeout")

    def list_objects(self):
        return dict(self.store)

    def create(self, obj):
        self.create_calls[obj.key] = self.create_calls.get(obj.key, 0) + 1
        self._maybe_fail()
        self.store[obj.key] = obj.value
        return True

    def update(self, obj):
        self._maybe_fail()
        self.store[obj.key] = obj.value
        return True

    def delete(self, key):
        self.store.pop(key, None)
        return True

    def duplicate_count(self):
        return sum(max(0, c - 1) for c in self.create_calls.values())


# --------------------------- HUBSPOT ----------------------------
class HubSpotAdapter(WorkspaceAdapter):
    BASE = "https://api.hubapi.com"
    SUPPORTED = {"pipeline", "custom_field"}     # the rest are honest manual steps
    functional = True                            # request mapping implemented + unit-tested

    # desired 'value' for a field -> (HubSpot type, fieldType)
    FIELD_TYPES = {
        "number": ("number", "number"), "date": ("date", "date"),
        "string": ("string", "text"), "text": ("string", "text"),
        "boolean": ("bool", "booleancheckbox"),
        "dropdown": ("enumeration", "select"), "enumeration": ("enumeration", "select"),
    }

    def __init__(self, token=None, http=None, timeout=20, max_retries=3):
        self.token = token
        self._http = http or self._urllib_http
        self.timeout = timeout
        self.max_retries = max_retries
        self._pipeline_ids = {}                   # label -> id (for delete/rollback)

    def supports(self, otype):
        return otype in self.SUPPORTED

    def normalize(self, otype, value):
        """Canonicalise desired vocab to HubSpot's so reconcile flags only REAL drift
        (e.g. desired 'dropdown' == HubSpot 'enumeration'; '(number)' == 'number')."""
        if value is None:
            return None
        if otype == "custom_field":
            key = str(value).strip().strip("()").lower()
            return self.FIELD_TYPES.get(key, ("string", "text"))[0]
        if otype == "pipeline":
            return ", ".join(s.strip() for s in str(value).split(",") if s.strip())
        return value

    # --- HTTP ---
    def _urllib_http(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.BASE + path, data=data, method=method,
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                txt = r.read().decode()
                return r.status, (json.loads(txt) if txt else {})
        except urllib.error.HTTPError as e:
            return e.code, {"error": e.read().decode()[:300]}

    def _req(self, method, path, body=None):
        last = None
        for attempt in range(self.max_retries):
            status, payload = self._http(method, path, body)
            if status in (429, 500, 502, 503):     # transient
                last = (status, payload); continue
            return status, payload
        return last

    # --- capability probe (used by /health in live mode; a real check, not the LLM) ---
    def capable(self):
        status, payload = self._req("GET", "/crm/v3/pipelines/deals")
        if status == 200:
            return True, "ok"
        if status == 403:
            return False, "missing scopes (add crm.schemas.deals.* + crm.objects.deals.*)"
        if status in (401, 0):
            return False, "invalid/expired token"
        return False, f"unexpected {status}"

    # --- reads ---
    def _fetch_pipelines(self):
        out = {}
        status, payload = self._req("GET", "/crm/v3/pipelines/deals")
        if status != 200:
            raise TransientError(f"pipelines read {status}")
        for p in payload.get("results", []):
            self._pipeline_ids[p["label"]] = p.get("id")
            out[("pipeline", p["label"])] = ", ".join(s["label"] for s in p.get("stages", []))
        return out

    def _fetch_properties(self):
        out = {}
        status, payload = self._req("GET", "/crm/v3/properties/deals")
        if status != 200:
            raise TransientError(f"properties read {status}")
        for pr in payload.get("results", []):
            if not pr.get("hubspotDefined", False):       # custom only
                out[("custom_field", pr["label"])] = pr.get("type", "")
        return out

    def list_objects(self):
        out = {}
        out.update(self._fetch_pipelines())
        out.update(self._fetch_properties())
        return out

    # --- writes (idempotent: skip if already present) ---
    def create(self, obj):
        if not self.supports(obj.otype):
            raise ManualStepRequired(obj.otype)
        existing = self.list_objects()
        if obj.key in existing:                    # idempotency: never duplicate
            return True
        if obj.otype == "pipeline":
            stages = [s.strip() for s in obj.value.split(",") if s.strip()]
            body = {"label": obj.name, "displayOrder": 0,
                    "stages": [{"label": s, "displayOrder": i,
                                "metadata": {"probability": "0.5"}} for i, s in enumerate(stages)]}
            status, payload = self._req("POST", "/crm/v3/pipelines/deals", body)
            if status in (200, 201):
                self._pipeline_ids[obj.name] = payload.get("id")
                return True
        elif obj.otype == "custom_field":
            key = obj.value.strip("()").lower()
            htype, ftype = self.FIELD_TYPES.get(key, ("string", "text"))
            body = {"name": _slug(obj.name), "label": obj.name,
                    "type": htype, "fieldType": ftype, "groupName": "dealinformation"}
            if htype == "enumeration":
                body["options"] = [{"label": "Option A", "value": "a", "displayOrder": 0},
                                   {"label": "Option B", "value": "b", "displayOrder": 1}]
            status, payload = self._req("POST", "/crm/v3/properties/deals", body)
            if status in (200, 201):
                return True
        raise TransientError(f"create {obj.otype} failed: {status}")

    def update(self, obj):
        if not self.supports(obj.otype):
            raise ManualStepRequired(obj.otype)
        if obj.otype == "custom_field":
            status, _ = self._req("PATCH", f"/crm/v3/properties/deals/{_slug(obj.name)}",
                                   {"label": obj.name})
            return status == 200
        return True                                 # pipeline stage edits = fast-follow

    def delete(self, key):
        otype, name = key
        if otype == "pipeline":
            pid = self._pipeline_ids.get(name)
            if pid:
                self._req("DELETE", f"/crm/v3/pipelines/deals/{pid}")
        elif otype == "custom_field":
            self._req("DELETE", f"/crm/v3/properties/deals/{_slug(name)}")
        return True


def _slug(label):
    return "oab_" + "".join(c if c.isalnum() else "_" for c in label.strip().lower())
