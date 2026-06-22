# Render Fix Report

Date: 2026-06-22

## Project Structure Confirmed

The separated Software project lives in its own GitHub/local repository root.

Local path:

```text
C:\Users\user\Desktop\Software
```

Confirmed app files:

```text
Software/
  app.py
  requirements.txt
  render.yaml
  runtime.txt
  software_sdk/
  docs/
  examples/
```

`app.py` exposes:

```python
app = FastAPI(...)
```

## Render Deployment Type

Use a normal Render Python Web Service.

Do not use Docker for this deployment.

Docker files were moved out of the active repository root and preserved under:

```text
docs/docker-legacy/
```

This prevents Render from accidentally treating the service as a Docker deployment.

## Exact Render Settings

Because `app.py`, `requirements.txt`, and `render.yaml` are already at the root of the separated Software repository, the Render root directory should be:

```text
.
```

In the Render UI, this means:

```text
Root Directory: leave blank / repository root
```

Do not set the Root Directory to `Software` when deploying the standalone `software-reliability-engine` repository. That setting is only correct for a monorepo where `Software/` is a top-level subfolder.

Build Command:

```text
pip install -r requirements.txt
```

Start Command:

```text
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Health Check Path:

```text
/health
```

Runtime:

```text
Python
```

## Final render.yaml

```yaml
services:
  - type: web
    name: software-platform
    env: python
    plan: free
    rootDir: .
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /health
```

## Requirements Fixed

`requirements.txt` now includes the deployment/runtime dependencies:

```text
fastapi
uvicorn
python-multipart
bcrypt
PyJWT
requests
pydantic
stripe
```

## Validation Performed

Syntax check:

```powershell
python -m py_compile app.py reliability_database.py reliability_scoring.py
```

Import check:

```powershell
python -c "import app; print(type(app.app).__name__)"
```

Result:

```text
FastAPI
```

Render-style local smoke test:

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8510
```

Health check:

```text
GET http://127.0.0.1:8510/health
```

Result:

```text
200 OK
```

## Final Deployment Checklist

1. Push the latest commit to GitHub.
2. In Render, create a Web Service.
3. Select the `Tejaswin846/software-reliability-engine` repository.
4. Choose Python environment, not Docker.
5. Leave Root Directory blank, or use `.` if Render asks for a value.
6. Set Build Command:

```text
pip install -r requirements.txt
```

7. Set Start Command:

```text
uvicorn app:app --host 0.0.0.0 --port $PORT
```

8. Set Health Check Path:

```text
/health
```

9. Add production environment variables:

```text
SOFTWARE_ENV=production
JWT_SECRET=<generated secret>
PUBLIC_BASE_URL=https://software-platform.onrender.com
SOFTWARE_ALLOWED_ORIGINS=https://software-platform.onrender.com
SOFTWARE_SDK_API_KEYS=<your SDK key>
```

10. Deploy and verify:

```text
https://software-platform.onrender.com/health
https://software-platform.onrender.com/dashboard
https://software-platform.onrender.com/login
https://software-platform.onrender.com/pricing
```

## Notes

Render free tier services may sleep after inactivity, but the `.onrender.com` URL remains permanent.

SQLite will work for an early demo, but without persistent storage the database can reset across redeploys. Add a Render disk or migrate to PostgreSQL before using this for real customers.
