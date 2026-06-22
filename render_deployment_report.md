# Render Deployment Report

## Phase 26 Goal

Deploy Software on Render with a stable permanent Render public URL:

```text
https://software-reliability-engine.onrender.com
```

Only the Render Web Service URL is valid for Phase 26 verification.

## Current Deployment Status

```text
Prepared, not deployed.
```

Reason:

```text
No Render API key, Render service ID, or connected GitHub repository is available in this environment.
```

This report must not be treated as a completed Render deployment until the final verified URL ends with:

```text
.onrender.com
```

## Render Files Updated

```text
render.yaml
runtime.txt
deployment_render.md
render_env.example
render_deployment_report.md
```

## Render Service Configuration

Service type:

```text
Web Service
```

Runtime:

```text
Python 3.12.4
```

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn Software.app:app --host 0.0.0.0 --port $PORT
```

Health check path:

```text
/health
```

Render provides `PORT`. Software defaults to port `8000` outside Render.

## Permanent Render URL

Target URL:

```text
https://software-reliability-engine.onrender.com
```

Set:

```text
PUBLIC_BASE_URL=https://software-reliability-engine.onrender.com
SOFTWARE_ALLOWED_ORIGINS=https://software-reliability-engine.onrender.com
```

If Render generates a different service slug, update every URL to the actual final `.onrender.com` URL.

## Required Environment Variables

```text
SOFTWARE_ENV=production
JWT_SECRET=replace-with-a-long-random-secret
PUBLIC_BASE_URL=https://software-reliability-engine.onrender.com
SOFTWARE_ALLOWED_ORIGINS=https://software-reliability-engine.onrender.com
SOFTWARE_API_DB_PATH=/var/data/software_reliability.db
RELIABILITY_DB_PATH=/var/data/reliability.db
SOFTWARE_SDK_API_KEYS=sw_replace_with_initial_render_sdk_key
SOFTWARE_ENABLE_BOOTSTRAP_DEV_KEY=true
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRO_PRICE_ID=
STRIPE_ENTERPRISE_PRICE_ID=
```

## Database Plan

SQLite is supported when Render persistent disk is attached:

```text
Disk name: software-data
Mount path: /var/data
Size: 1 GB or larger
```

Without persistent disk, SQLite data may reset after deploys, restarts, or instance replacement.

## Permanent Render Routes To Verify

These must be checked against the final Render URL only:

```text
https://software-reliability-engine.onrender.com/
https://software-reliability-engine.onrender.com/health
https://software-reliability-engine.onrender.com/status
https://software-reliability-engine.onrender.com/metrics
https://software-reliability-engine.onrender.com/dashboard
https://software-reliability-engine.onrender.com/login
https://software-reliability-engine.onrender.com/register
https://software-reliability-engine.onrender.com/pricing
https://software-reliability-engine.onrender.com/api/dashboard
https://software-reliability-engine.onrender.com/api/billing/plans
```

## Verification Status

Prepared files:

```text
PASS
```

Permanent Render route verification:

```text
NOT RUN
```

Health check status:

```text
NOT VERIFIED ON RENDER
```

Dashboard status:

```text
NOT VERIFIED ON RENDER
```

## Render Free Tier Note

Render free tier services may sleep after inactivity. The first request after sleep can be slow, but the `.onrender.com` URL remains permanent.

## Deployment Completion Rule

Phase 26 is complete only when:

1. The app is deployed on Render.
2. The final public URL ends with `.onrender.com`.
3. `/health` returns 200 from that Render URL.
4. `/dashboard` returns 200 from that Render URL.
5. `/api/billing/plans` returns 200 from that Render URL.

## Final Output

Final permanent Render URL:

```text
https://nexora-ai-wcu1.onrender.com
```

Health check status:

```text
200, but this is the old Nexora Agent health endpoint, not Software.
```

Dashboard status:

```text
404
```

Login status:

```text
404
```

Pricing status:

```text
404
```

## Render Verification Result

The Render Web Service is live at:

```text
https://nexora-ai-wcu1.onrender.com
```

However, it is not running the Software reliability platform yet.

Verified response from `/health`:

```text
app: Nexora Agent
```

The connected GitHub repository is:

```text
Tejaswin846/nexora-ai
```

That repository currently contains the older Nexora app and its `render.yaml` points to:

```text
backend/main.py
```

It does not contain the current Software project folder and Render blueprint from this workspace.

Current route verification:

```text
/health    -> 200, wrong app
/dashboard -> 404
/login     -> 404
/pricing   -> 404
/status    -> 404
```

## Required Fix

Deploy a GitHub repository or branch that contains the current Software project files:

```text
Software/
software_sdk/
render.yaml
requirements.txt
runtime.txt
deployment_render.md
render_env.example
```

Do not overwrite the existing Nexora app unless that is explicitly intended.
