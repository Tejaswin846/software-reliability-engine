# Software Production Deployment

Software is a FastAPI reliability platform for AI-agent benchmarks, model comparisons, tool reliability, prediction analytics, guardrails, and the browser dashboard.

## Production Files

- `Software/app.py` - FastAPI application and dashboard APIs.
- `Software/dashboard.html` - Browser dashboard.
- `Software/dashboard.css` - Dashboard styling.
- `Software/dashboard.js` - Dashboard data renderer.
- `Software/data/reliability.db` - Reliability benchmark database.
- `Software/data/software_reliability.db` - API-created benchmark database.
- `requirements.txt` - Python dependencies.
- `production.env.example` - Production environment template.
- `Dockerfile` - Container image.
- `docker-compose.yml` - Local production-like deployment.

## Environment Variables

Copy `production.env.example` to your cloud provider or local `.env` equivalent and change values as needed.

```text
SOFTWARE_ENV=production
SOFTWARE_APP_NAME=Software Reliability Engine
SOFTWARE_VERSION=0.2.0
SOFTWARE_ALLOWED_ORIGINS=
SOFTWARE_PUBLIC_URL=https://software.yourdomain.com
SOFTWARE_PRIMARY_HOST=software.yourdomain.com
SOFTWARE_PRODUCTION_HOSTS=software.yourdomain.com,app.yourdomain.com,api.yourdomain.com
SOFTWARE_REDIRECT_HOSTS=yourdomain.com,www.yourdomain.com,www.software.yourdomain.com,www.app.yourdomain.com,www.api.yourdomain.com
SOFTWARE_FORCE_HTTPS=true
SOFTWARE_REDIRECT_WWW=true
SOFTWARE_API_DB_PATH=/app/Software/data/software_reliability.db
RELIABILITY_DB_PATH=/app/Software/data/reliability.db
HOST=0.0.0.0
PORT=8000
```

Use `SOFTWARE_ALLOWED_ORIGINS` only if a separate frontend domain needs browser access to the API. The built-in dashboard is served from the same FastAPI app and does not need CORS.

For permanent domain hosting, see:

- `domain_setup.md`
- `production_dns.md`
- `ssl_setup.md`

For Render hosting, see:

- `deployment_render.md`
- `render.yaml`
- `render_env.example`

## Run Locally

```bash
pip install -r requirements.txt
uvicorn Software.app:app --host 0.0.0.0 --port 8000
```

Open:

```text
http://127.0.0.1:8000/dashboard
```

## Run With Docker Compose

```bash
docker compose up --build
```

The compose file bind-mounts `./Software/data` into the container so the SQLite benchmark databases remain persistent and visible.

Open:

```text
http://127.0.0.1:8000/dashboard
```

## Health And Operations Endpoints

- `GET /health` - Load-balancer health check. Returns `503` if startup checks fail.
- `GET /version` - Service version and environment.
- `GET /status` - Detailed startup, database, and dashboard asset checks.
- `GET /metrics` - Reliability metrics for monitoring.
- `GET /dashboard` - Browser dashboard.
- `GET /api/dashboard` - Full dashboard JSON payload.

## Render Deployment

1. Create a new Web Service from this project repository.
2. Set the build command:

```bash
pip install -r requirements.txt
```

3. Set the start command:

```bash
uvicorn Software.app:app --host 0.0.0.0 --port $PORT
```

4. Add the environment variables from `production.env.example`.
5. Add persistent disk storage for `Software/data` if benchmark history must survive deploys.
6. Set the health check path to `/health`.

For a full Render checklist, persistent disk notes, and route verification, use `deployment_render.md`.

## Azure Deployment

For Azure App Service or Azure Container Apps:

1. Build from the Dockerfile or deploy the Python app directly.
2. Set the startup command:

```bash
uvicorn Software.app:app --host 0.0.0.0 --port 8000
```

3. Add environment variables from `production.env.example`.
4. Mount persistent storage at `/app/Software/data`.
5. Configure the health probe path as `/health`.

For an Azure VM deployment with a permanent domain:

1. Point DNS records to the VM public IP.
2. Install Caddy or Nginx as a reverse proxy.
3. Proxy `software.yourdomain.com`, `app.yourdomain.com`, and `api.yourdomain.com` to `127.0.0.1:8300`.
4. Set `SOFTWARE_PUBLIC_URL=https://software.yourdomain.com`.
5. Set `SOFTWARE_FORCE_HTTPS=true`.
6. Set `SOFTWARE_PRIMARY_HOST=software.yourdomain.com`.
7. Open Azure inbound ports `80/tcp` and `443/tcp`.

## Production Checklist

- `/health` returns `ok: true`.
- `/status` shows both SQLite databases as reachable.
- `/dashboard` loads the browser dashboard.
- `/api/dashboard` returns model, tool, workflow, prediction, and guardrail data.
- Persistent storage is mounted for `Software/data`.
- `SOFTWARE_ENV=production` is set.
- API docs are disabled in production mode.
