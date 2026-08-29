# Matrixs Quick Start

## 1. Install Matrixs

```bash
pip install git+https://github.com/Tejaswin846/software-reliability-engine.git
```

No sign-in is required for install, docs, local validation, local plans, dry-run
examples, or sandbox workflow tests.

## 2. Start Matrixs Locally

```bash
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8300
```

Open:

```text
http://127.0.0.1:8300
```

## 3. Connect a Cloud Project

Create or select a project at `/projects`, open `/api-keys`, and keep its Project ID
and API key ready. Run the same secret-free command beside every Python project.

```bash
MATRIXS_API_URL=http://127.0.0.1:8300 matrixs connect
matrixs status
matrixs run
```

Matrixs asks permission first. Approve automatic integration to open a secure local
page for the Project ID and API key, or decline to use the manual integration guide.

## 4. View Dashboard

Open:

```text
http://127.0.0.1:8300/dashboard
```

After sign-in, the SDK Workflows section shows your project-scoped workflow
telemetry.

## Common Issues

`403 Invalid SDK API key`

Create a new API key at `/api-keys`, then run `matrixs connect` again.

`Workflow not visible`

Confirm you are viewing the same Matrixs URL stored in `.matrixs/config.json`.

`401 Authentication required`

The endpoint is a protected cloud feature. Sign in with Clerk or send a project
API key. Local SDK use remains available without signing in.
