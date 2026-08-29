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

Create or select a project at `/projects`, open `/api-keys`, and generate a
single-use connection command. Run it beside the Python project within 15 minutes.

```bash
matrixs connect --token mxct_... --api-url http://127.0.0.1:8300
matrixs status
matrixs run
```

## 4. View Dashboard

Open:

```text
http://127.0.0.1:8300/dashboard
```

After sign-in, the SDK Workflows section shows your project-scoped workflow
telemetry.

## Common Issues

`403 Invalid SDK API key`

Generate a new one-time command at `/api-keys` and reconnect the project.

`Workflow not visible`

Confirm you are viewing the same Matrixs URL stored in `.matrixs/config.json`.

`401 Authentication required`

The endpoint is a protected cloud feature. Sign in with Clerk or send a project
API key. Local SDK use remains available without signing in.
