# 🚀 Deploy — Onboarding Auto-Builder (SHARED_SITE_CONTRACT compliant)

**Claimed registry slot:** slug `onboarding-builder` · **port 8008** · `https://onboarding-builder.204-168-226-100.sslip.io`

## Backend (on the shared VPS `204.168.226.100`)
```bash
# 1. build (from this repo on the VPS, or push an image)
docker build -t onboarding-builder .

# 2. run — secrets server-side only, live mode (real model + real sandbox)
docker run -d --name onboarding-builder --restart unless-stopped \
  -p 127.0.0.1:8008:8008 \
  -e OAB_MODE=live \
  -e OAB_DEEPSEEK_KEY="sk-..." \
  -e OAB_HUBSPOT_TOKEN="pat-..." \
  -e OAB_CORS_ORIGINS="https://taash-chikosi-portfolio.vercel.app" \
  onboarding-builder

# 3. Caddy site block -> then: sudo systemctl reload caddy
#   onboarding-builder.204-168-226-100.sslip.io {
#       reverse_proxy localhost:8008
#   }

# 4. verify the REAL endpoint before calling it live (health alone is not enough, per contract §4)
curl -s https://onboarding-builder.204-168-226-100.sslip.io/health      # {"status":"ok","engine":{...,"real":true}}
curl -s -XPOST https://onboarding-builder.204-168-226-100.sslip.io/plan \
  -H 'content-type: application/json' -d '{"intake":"Customer: Test\nPipelines:\n- P: a,b"}'
```

## Frontend (in `Taash_Chikosi_Portfolio`, dir `frontend/`)
- Drop in `frontend/app/onboarding-builder/page.tsx` + `frontend/app/onboarding-builder/demo/page.tsx` (provided in `frontend/` here).
- Add the `projects.ts` entry (snippet in `frontend/projects.entry.ts`).
- Set in Vercel **Production** env: `NEXT_PUBLIC_ONBOARDING_BUILDER_API_BASE=https://onboarding-builder.204-168-226-100.sslip.io`
- ⚠️ **Matched pair:** that API base origin must be allowed by the backend's `OAB_CORS_ORIGINS`, or the browser blocks every call.

## The honesty contract (§4)
- `OAB_MODE=live` makes the service **refuse** (503) to answer with a mock — a stand-in can never be shown as live.
- Every response carries `engine: {llm, sandbox, real}`; the demo page renders an "About the engine" panel from it.
- Keys are only ever in the container env. `NEXT_PUBLIC_*` is public — never put a secret there.
