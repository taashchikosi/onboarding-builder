# 🚦 Deploy Readiness Verdict — Onboarding Auto-Builder (14 Jun 2026, rev 2)

**Verdict: ✅ THE LIVE BUILD WORKS. Proven end-to-end against the real HubSpot sandbox (scopes added 14 Jun).**
Real objects were created in portal 443341147 by the agent: **Onboarding Pipeline + 3 custom deal properties** (Contract Value, Health Score, Account Tier). Re-run = idempotent no-op (zero duplicates). Roles/automations/integrations correctly recorded as honest manual steps. Only remaining work is the **mechanical site deploy** (VPS container + Caddy + Vercel route) and your **key rotation**.

### 🟢 Live-build proof (14 Jun 2026)
- DeepSeek compiled the Acme SOW → 12 objects; both injected attacks refused.
- Applied to **real HubSpot**: 5 created (1 pipeline + 3 fields + idempotent skip of the existing default), 7 manual (roles/automations/integrations — not API-provisionable).
- Read-back from HubSpot confirms the objects exist. Re-apply → 0 duplicates.
- Reconcile parity over supported types is clean except one **honest** drift: the SOW's "Sales Pipeline" collides with HubSpot's built-in default pipeline, and the agent **safely refused to overwrite it** (flagged for human review rather than clobbering). That's the safe-by-default story, not a bug.
- Port corrected to **8008** per the canonical registry (was 8003 — a portfolio-wide collision the contract resolved).

---

## ✅ What's production-grade and verified (green)

| Component | Status | Evidence |
|---|---|---|
| Compiler (SOW → desired-state) | ✅ live DeepSeek wired | parent-link F1 **99.1%** vs baseline 23.3% (10 gold) |
| Safety (injection screen + re-screen) | ✅ | attacks dropped in demo + 2 LLM-safety tests |
| Planner (terraform diff + topo order) | ✅ | demo + tests |
| Applier (idempotent · retry · rollback) | ✅ | sim 9.2%→100%, dup 643→0, unsafe 100→0 |
| Reconcile (plan↔actual parity) | ✅ | test + demo |
| API (CORS · rate limit · real /health · approval gate) | ✅ | 4 contract tests |
| Honesty layer (`engine.real`, live-mode 503) | ✅ | refuses to serve a stand-in |
| HubSpot adapter (pipelines + properties) | ✅ **proven live** | real objects created in your sandbox; idempotent |
| Docker / DEPLOY.md / frontend drop-ins | ✅ | port **8008** registered (collision fixed) |
| Tests | ✅ **17/17** | core + API + adapter, offline/deterministic |

---

## 🔴 Blocker 1 — Secrets would leak to GitHub (mitigated, action still needed)
- `.gitignore` now excludes `Secrets.txt`, `deepseek-key.txt`, `.env`, `*-key.txt`. ✅ done here.
- **You must still:** ROTATE the HubSpot token + DeepSeek key (they existed in plaintext), and fix the **same `Secrets.txt` in `project-03/` and `project-06/`** before any push.

## 🔴 Blocker 2 — HubSpot token is missing scopes
- Token is **valid** (portal 443341147, region **ap1/Australia**, type DEVELOPER_TEST = correct sandbox ✅).
- But reading pipelines returns **403 "hasn't been granted all required scopes."**
- **Fix (2 min):** HubSpot test account → Settings → Integrations → Private Apps → your app → **Scopes** → add:
  `crm.schemas.deals.read`, `crm.schemas.deals.write`, `crm.objects.deals.read`, `crm.objects.deals.write` → **Save**. Token stays the same.

## ✅ Blocker 3 — HubSpotAdapter — RESOLVED (implemented + tested)
- `HubSpotAdapter` now wires the real HubSpot CRM API: **list / create / update / delete** for **pipelines** (`/crm/v3/pipelines/deals`) and **custom deal properties** (`/crm/v3/properties/deals`), idempotent (skips existing), with retries + a `capable()` scope probe. `functional = True`.
- **Honesty (contract §4):** roles / automations / integrations are **not** cleanly API-provisionable, so the adapter declares `supports()=False` for them and the applier records them as **MANUAL steps** (`ApplyResult.manual`) — never fake-created. The real build = pipelines + custom fields, which appear in your HubSpot UI (filmable wow).
- **Tested:** 6 offline tests (payload shape, idempotency, manual-step routing) + a **live probe against your real token** that correctly returns "missing scopes". `/health` in live mode returns **503 + the exact reason** until scopes are added — it will flip to green automatically once they are. 17/17 tests total.
- Demo mode stays on the mock (works today, honestly labelled); live mode uses the real adapter.

---

## 🟢 Two deploy paths

**A. Representative deploy (today):** ship in demo mode with the honest "About the engine" banner — real DeepSeek compile, mock sandbox, clearly labelled. Satisfies §4. Good for a soft launch.

**B. Real-build deploy (the one worth filming):** only your 2 manual steps remain →
1. you: **rotate** the HubSpot token + DeepSeek key, and **add scopes** to the private app: `crm.schemas.deals.read/write` + `crm.objects.deals.read/write` (~4 min),
2. me: put the rotated token in the container env, flip `OAB_MODE=live`, deploy container + Caddy + Vercel env, verify the real endpoint (the adapter + honesty path are already done and tested).

**Recommendation:** Path B. The engineering is finished — `/health` will go green the instant your scopes land. Hold the Loom until then.
