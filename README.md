# 🏗️ Onboarding / Implementation Auto-Builder — "onboarding-as-code"

Project 05 of the automation portfolio. Compile a signed SOW / discovery transcript into a **desired-state workspace config**, show a `terraform plan`-style diff, **approve**, then **apply** it idempotently to a real sandbox, **reconcile** plan-vs-actual, and emit a tailored runbook. Plan: `../Project-05-Onboarding-Auto-Builder-Plan.md`.

> **Status: runnable skeleton, built autonomously 14 Jun 2026.** Runs end-to-end **with zero credentials** (mock LLM + in-memory sandbox). Real DeepSeek + HubSpot sandbox swap in at two clearly-marked seams. See `WHAT_I_NEED_FROM_YOU.md`.

## What already works today (no setup)

```bash
cd onboarding-builder
python3 demo/run_demo.py        # full flow: screen → compile → plan → approve → apply → reconcile → re-run no-op → rollback → runbook
python3 eval/run_eval.py        # compile-accuracy: engineered vs naive baseline vs gold
python3 -m pytest -q tests/     # 5 tests: idempotency, rollback, injection-block, dependency order, drift repair
python3 ../onboarding_provision_sim.py   # apply-layer proof: naive vs engineered under fault injection
```

Open `ui/plan_diff_mockup.html` in a browser for the visual plan/approve/rollback UX.

## Real numbers produced this session

| Proof | Result |
|---|---|
| **Compile-accuracy** — parent-link F1 vs gold, 10 scenarios: **live DeepSeek / pure rules / naive baseline** | **~99% / 80% / 23.3%** |
| — full-config F1 (incl. free-text value strings) | **deepseek ~89% / rules 80% / baseline 23.3%** |
| **Apply-layer integrity** (sim, 600 onboardings) — exact-provision | **naive 9.2% → engineered 100%** |
| — injected privilege-escalations executed | **naive 100/100 → engineered 0** |
| — duplicate objects on re-run | **naive 643 → engineered 0** |
| — orphaned (dependency-broken) objects | **naive 1,368 → engineered 0** |
| **Unit tests** | **17/17 pass (offline, deterministic)** |
| **HubSpot adapter** | real pipelines + deal-properties (idempotent); roles/automations/integrations = honest manual steps; live scope-probe wired |

> Honesty note: the compile-F1 is now measured with the **real DeepSeek model** (`python3 eval/run_eval.py --llm`), scored against 10 hand-labeled gold scenarios — including 2 messy prose transcripts where the **pure-rule compiler scores 0%** and the LLM scores ~100%, and 2 attack-laden intakes the LLM correctly strips (run-to-run LLM variance ≈99–100%). Caveats kept honest: **N=10 and the gold is self-labeled** — next step is Taash's independent review + expansion to ~20, and a held-out set. The apply-layer numbers come from the credential-free fault simulation.

## Architecture (seams marked ⇄ for real-credential swap)

```
intake.txt ─► policy.screen_intake ─► compiler.compile_engineered ◄═ DeepSeek (LIVE, key wired)
           ─► planner.plan ─► render_diff ──[HUMAN APPROVE]──►
           ─► applier.apply (idempotent · topo-order · retry · rollback)
                              └► adapters.MockSandboxAdapter ⇄ HubSpotAdapter
           ─► reconcile ─► runbook.generate_runbook
```

| File | Role |
|---|---|
| `src/oab/schema.py` | typed desired-state model + dependency graph |
| `src/oab/policy.py` | injection/unsafe screen + operation allow-list |
| `src/oab/compiler.py` | SOW → desired-state (engineered + baseline) |
| `src/oab/llm.py` | LLM seam — MockLLM today, DeepSeekLLM stub |
| `src/oab/planner.py` | diff → plan + terraform-style render + topo order |
| `src/oab/adapters.py` | MockSandboxAdapter (works now) + HubSpotAdapter stub |
| `src/oab/applier.py` | idempotent, dependency-ordered, retried, **reversible** apply |
| `src/oab/reconcile.py` | plan↔actual parity + drift repair |
| `src/oab/runbook.py` | runbook generated from reconciled state |
| `src/oab/api.py` | FastAPI shell (`/health /compile /plan /apply /reconcile /runbook`) |
| `eval/` | gold scenarios + intakes + F1 runner |
| `demo/run_demo.py` | the end-to-end CLI wow |
| `tests/` | the reliability/safety guarantees, as tests |

## Shared-site contract compliance (SHARED_SITE_CONTRACT.md)

Registered slot: slug **`onboarding-builder`** · port **8008** · `https://onboarding-builder.204-168-226-100.sslip.io`.

- **Real-model-only (contract §4):** `OAB_MODE=live` makes the API **refuse (503)** to answer with a mock — a stand-in can never be shown as live. Every response carries `engine:{llm,sandbox,real}`; the demo page renders an honest "About the engine" panel from it.
- **Real `/health`:** checks the providers this mode needs are configured (not just "process up") and does **not** call the LLM.
- **CORS + rate limit + server-side secrets** built in. Keys only in the container env.
- **Deploy artifacts:** `Dockerfile` (port 8008), `DEPLOY.md` (docker run + Caddy block + the CORS/API_BASE matched pair), and `frontend/` Next.js route drop-ins (`page.tsx` case study, `demo/page.tsx`, `projects.entry.ts`, `.env.local.example`).

## v1 cut line
In: compile → plan → approve → idempotent apply → rollback → reconcile → runbook + compile-F1 number + injection block-rate + the Next.js route. Not in v1: production-tenant writes, a PM tool, continuous sync (that's Project 03). See the plan.
