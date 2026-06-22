# Render Deployment Guide

## Goal

Deploy Software on Render with a stable public URL:

```text
https://software-platform.onrender.com
```

Only the Render Web Service URL is valid for Phase 26 verification.

## Render Service

Use:

```text
Service type: Web Service
Runtime: Python
Health check path: /health
```

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Render provides `PORT` automatically. Software also defaults to port `8000` when run outside Render.

## Blueprint

The `render.yaml` blueprint creates:

```text
Service name: software-platform
Public URL: https://software-platform.onrender.com
Persistent disk: /var/data
```

If Render changes the generated service slug, update:

```text
PUBLIC_BASE_URL
SOFTWARE_ALLOWED_ORIGINS
STRIPE_SUCCESS_URL
STRIPE_CANCEL_URL
STRIPE_PORTAL_RETURN_URL
```

to the actual `.onrender.com` URL.

## Required Render Files

```text
render.yaml
requirements.txt
runtime.txt
render_env.example
```

## Environment Variables

Set these in Render:

```text
SOFTWARE_ENV=production
JWT_SECRET=replace-with-a-long-random-secret
PUBLIC_BASE_URL=https://software-platform.onrender.com
SOFTWARE_ALLOWED_ORIGINS=https://software-platform.onrender.com
SOFTWARE_API_DB_PATH=/var/data/software_reliability.db
RELIABILITY_DB_PATH=/var/data/reliability.db
SOFTWARE_SDK_API_KEYS=sw_replace_with_initial_render_sdk_key
SOFTWARE_ENABLE_BOOTSTRAP_DEV_KEY=true
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRO_PRICE_ID=
STRIPE_ENTERPRISE_PRICE_ID=
```

`JWT_SECRET` is supported directly. `SOFTWARE_JWT_SECRET` also works.

`PUBLIC_BASE_URL` is supported directly. `SOFTWARE_PUBLIC_URL` also works.

## Database

Software uses SQLite for this Render phase.

Attach a Render persistent disk:

```text
Name: software-data
Mount path: /var/data
Size: 1 GB or larger
```

Use:

```text
SOFTWARE_API_DB_PATH=/var/data/software_reliability.db
RELIABILITY_DB_PATH=/var/data/reliability.db
```

Important:

```text
Without a Render persistent disk, SQLite data may reset after deploys, restarts, or instance replacement.
```

For a larger SaaS production system, upgrade the persistence layer to PostgreSQL later.

## Deployment Checklist

1. Push the Software project to GitHub.
2. In Render, create a Web Service or use the `render.yaml` blueprint.
3. Connect the GitHub repository.
4. Confirm build command:

```bash
pip install -r requirements.txt
```

5. Confirm start command:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

6. Set health check path:

```text
/health
```

7. Add environment variables from `render_env.example`.
8. Attach persistent disk at `/var/data`.
9. Deploy.
10. Confirm the public URL ends with:

```text
.onrender.com
```

## Permanent Render Routes To Verify

Verify only against the Render URL:

```bash
curl -I https://software-platform.onrender.com/
curl -I https://software-platform.onrender.com/health
curl -I https://software-platform.onrender.com/status
curl -I https://software-platform.onrender.com/metrics
curl -I https://software-platform.onrender.com/dashboard
curl -I https://software-platform.onrender.com/login
curl -I https://software-platform.onrender.com/register
curl -I https://software-platform.onrender.com/pricing
curl -I https://software-platform.onrender.com/api/dashboard
curl -I https://software-platform.onrender.com/api/billing/plans
```

Expected:

```text
/health returns 200
/dashboard returns 200
/login returns 200
/register returns 200
/pricing returns 200
/api/dashboard returns 200
/api/billing/plans returns 200
```

## SDK Verification

Use the Render URL as the SDK API base:

```python
from software_sdk import ReliabilityMonitor

monitor = ReliabilityMonitor(
    project_name="render-smoke-test",
    api_url="https://software-platform.onrender.com",
    api_key="sw_your_project_api_key"
)
```

Run one workflow and confirm it appears in the dashboard.

## Free Tier Note

Render free tier services may sleep after inactivity, so the first request can be slow. The public URL remains permanent:

```text
https://software-platform.onrender.com
```

