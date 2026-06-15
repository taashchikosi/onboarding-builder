"""FastAPI surface for the Onboarding Auto-Builder — SHARED_SITE_CONTRACT compliant.

Endpoints (approval-gated — /apply only runs after a human POSTs approve=true):
  GET  /health                 -> real self-check for the live-status dot (does NOT call the LLM)
  GET  /                       -> service banner + mode
  POST /compile {intake}       -> desired-state + screened unsafe lines
  POST /plan    {intake}       -> terraform-style diff (no mutation)
  POST /apply   {intake, approve} -> idempotent apply to the sandbox
  POST /reconcile {intake}     -> parity check
  POST /runbook {intake}       -> markdown runbook from reconciled state

Honesty (contract §4): every response carries an `engine` block stating whether the
REAL model/sandbox served it. In OAB_MODE=live, the service REFUSES to answer with a
stand-in — a mock must never be presented as live. Secrets stay server-side.

Env:
  OAB_MODE             demo (default) | live   (live requires real DeepSeek + HubSpot)
  OAB_PORT             default 8008 (claimed port in the registry)
  OAB_CORS_ORIGINS     comma list; default "*" (public read-only demo)
  OAB_DEEPSEEK_KEY     real compile model
  OAB_HUBSPOT_TOKEN    real sandbox provisioning target
  OAB_MAX_INTAKE_CHARS hard input cap (default 20000) — bounds per-request LLM cost
"""
import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from oab.compiler import compile_engineered
from oab.policy import screen_intake
from oab.planner import plan as make_plan, render_diff
from oab.applier import apply as apply_plan
from oab.reconcile import reconcile as do_reconcile
from oab.runbook import generate_runbook
from oab.adapters import MockSandboxAdapter, HubSpotAdapter
from oab.llm import get_provider

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
except Exception:                      # importable without fastapi (tests/CLI)
    FastAPI = None

MODE = os.environ.get("OAB_MODE", "demo").lower()
PORT = int(os.environ.get("OAB_PORT", "8008"))

# Hard input cap (contract §4 / elevation #5: token cap on a public, server-side-keyed
# endpoint). An intake is a SOW/discovery transcript; 20k chars (~5k tokens) is generous
# for that and bounds the per-request DeepSeek cost a caller can force. Tunable via env.
MAX_INTAKE_CHARS = int(os.environ.get("OAB_MAX_INTAKE_CHARS", "20000"))


def _adapter():
    """Demo mode always uses the in-memory mock (works with no/partial creds).
    Live mode uses the real HubSpot adapter — and /health then probes its real
    capability (scopes) so a token without scopes shows degraded, never fake-live."""
    tok = os.environ.get("OAB_HUBSPOT_TOKEN")
    if MODE == "live" and tok and getattr(HubSpotAdapter, "functional", False):
        return HubSpotAdapter(tok)
    return MockSandboxAdapter()

_SANDBOX = _adapter()


def _engine():
    """Truthful description of what is actually serving requests."""
    llm = get_provider().name                                  # 'deepseek' | 'mock'
    sandbox = "hubspot" if isinstance(_SANDBOX, HubSpotAdapter) else "mock"
    real = (llm == "deepseek") and (sandbox == "hubspot")
    return {"llm": llm, "sandbox": sandbox, "real": real, "mode": MODE}


def _require_real_if_live():
    """Contract §4: in live mode, never answer with a stand-in."""
    eng = _engine()
    if MODE == "live" and not eng["real"]:
        raise HTTPException(
            status_code=503,
            detail=f"live mode requires real providers, got {eng['llm']}/{eng['sandbox']}. "
                   f"Set OAB_DEEPSEEK_KEY + OAB_HUBSPOT_TOKEN.")


def _guard(req):
    """Per-request gate for every mutating/LLM endpoint: enforce the hard input cap
    BEFORE any LLM call (bounds cost/abuse), then the live-mode real-provider rule."""
    if len(req.intake) > MAX_INTAKE_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"intake too large: {len(req.intake)} chars > {MAX_INTAKE_CHARS} cap")
    _require_real_if_live()


# --- minimal in-memory rate limiter (contract §4: rate-limit public demo routes) ---
_HITS = {}
_LOCK = threading.Lock()
RL_MAX, RL_WINDOW = 30, 60          # 30 requests / 60s / IP

def _rate_ok(ip):
    now = time.time()
    with _LOCK:
        q = [t for t in _HITS.get(ip, []) if now - t < RL_WINDOW]
        if len(q) >= RL_MAX:
            _HITS[ip] = q
            return False
        q.append(now)
        _HITS[ip] = q
        return True


if FastAPI:
    app = FastAPI(title="Onboarding Auto-Builder", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in os.environ.get("OAB_CORS_ORIGINS", "*").split(",")],
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.middleware("http")
    async def _rl(request: Request, call_next):
        if request.url.path not in ("/health", "/"):
            ip = request.client.host if request.client else "anon"
            if not _rate_ok(ip):
                return JSONResponse(status_code=429, content={"detail": "rate limit: 30/min"})
        return await call_next(request)

    class IntakeReq(BaseModel):
        intake: str
        approve: bool = False

    @app.get("/")
    def root():
        return {"service": "onboarding-auto-builder", "mode": MODE, "engine": _engine()}

    @app.get("/health")
    def health():
        """Real self-check. In live mode it PROBES the sandbox's real capability
        (a cheap CRM read — scopes) so a token without scopes reports degraded, never
        fake-live. It never calls the LLM."""
        eng = _engine()
        detail = None
        if MODE == "live":
            ok = eng["real"]
            if ok and isinstance(_SANDBOX, HubSpotAdapter):
                cap_ok, reason = _SANDBOX.capable()
                ok = cap_ok
                if not cap_ok:
                    detail = reason
        else:
            ok = bool(os.environ.get("OAB_DEEPSEEK_KEY")) or eng["sandbox"] == "mock"
        status = "ok" if ok else "degraded"
        body = {"status": status, "engine": eng}
        if detail:
            body["detail"] = detail
        return JSONResponse(status_code=200 if ok else 503, content=body)

    @app.post("/compile")
    def compile_ep(req: IntakeReq):
        _guard(req)
        d = compile_engineered(req.intake)
        return {"customer": d.customer,
                "objects": [o.__dict__ for o in d.objects],
                "applyable": len(d.applyable()),
                "blocked": [{"line": l, "reason": r} for l, r in screen_intake(req.intake)],
                "engine": _engine()}

    @app.post("/plan")
    def plan_ep(req: IntakeReq):
        _guard(req)
        d = compile_engineered(req.intake)
        actions = make_plan(d, _SANDBOX.list_objects())
        diff, counts = render_diff(actions, d.customer)
        return {"diff": diff, "to_create": counts[0], "to_update": counts[1],
                "unchanged": counts[2], "engine": _engine()}

    @app.post("/apply")
    def apply_ep(req: IntakeReq):
        _guard(req)
        if not req.approve:
            raise HTTPException(status_code=412,
                                detail="approval required: nothing mutates until approve=true")
        d = compile_engineered(req.intake)
        res = apply_plan(make_plan(d, _SANDBOX.list_objects()), _SANDBOX)
        return {"ok": res.ok, "applied": len(res.applied), "skipped": len(res.skipped),
                "manual": len(res.manual), "rolled_back": len(res.rolled_back),
                "failed": res.failed, "engine": _engine()}

    @app.post("/reconcile")
    def reconcile_ep(req: IntakeReq):
        _guard(req)
        d = compile_engineered(req.intake)
        r = do_reconcile(d, _SANDBOX)
        return {"parity": r.parity, "missing": r.missing, "drifted": r.drifted,
                "manual": r.manual, "engine": _engine()}

    @app.post("/runbook")
    def runbook_ep(req: IntakeReq):
        _guard(req)
        d = compile_engineered(req.intake)
        return {"runbook_md": generate_runbook(d, _SANDBOX), "engine": _engine()}
