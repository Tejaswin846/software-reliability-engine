# Software Quick Start

## 1. Install Publicly

```bash
pip install software-sdk
npm install software-sdk
```

No sign-in is required for install, docs, local validation, local plans, dry-run
examples, or sandbox workflow tests.

## 2. Start Software Locally

```bash
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8300
```

Open:

```text
http://127.0.0.1:8300
```

## 3. Use Cloud Features When Needed

Sign in with Clerk only when you need saved projects, cloud execution, user
memory, audit logs, integrations, API keys, or team features.

```bash
software login --api-url http://127.0.0.1:8300 --api-key sw_your_key --project-name my-agent-dev
software init
software test
software status
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

Generate a new API key at `/api-keys` and update `SOFTWARE_API_KEY`.

`Workflow not visible`

Confirm you are viewing the same Software URL used by `SOFTWARE_API_URL`.

`401 Authentication required`

The endpoint is a protected cloud feature. Sign in with Clerk or send a project
API key. Local SDK use remains available without signing in.
