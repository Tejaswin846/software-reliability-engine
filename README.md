# Software

Software is an AI-agent reliability platform.

It helps developers measure, predict, and improve real-world agent reliability by tracking:

- workflows
- stages
- model calls
- tool calls
- errors
- confidence
- latency
- failure predictions
- guardrail recommendations
- automatic recovery attempts

Software includes:

- FastAPI backend
- SQLite database
- multi-user accounts
- projects
- hashed API keys
- usage plans
- subscription limits
- customer-validation analytics
- Python SDK
- reliability dashboard
- developer documentation
- runnable examples

## Why Software Exists

AI agents often work in demos and simulations, then fail in real execution because of:

- tool failures
- provider timeouts
- context loss
- low confidence
- bad planning
- missing recovery paths

Software gives developers the reliability layer around those agents.

## Quick Start

Install the SDK:

```bash
pip install software-sdk
software login
software init
software test
software status
```

For local development from this repo:

```bash
python -m pip install --upgrade pip
pip install -e .
```

Run the backend:

```bash
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8300
```

Open:

```text
http://127.0.0.1:8300
```

Then:

1. Create an account at `/register`
2. Create a project at `/projects`
3. Generate an API key at `/api-keys`
4. Install the SDK with `pip install software-sdk`
5. Run `software login`
6. Run `software init`
7. Run `software test`
8. Open `/dashboard`

Example:

```bash
software login --api-url http://127.0.0.1:8300 --api-key sw_your_key --project-name my-agent
software init
software test
```

Track SDK installation analytics:

```bash
python -m software_sdk status
```

## Basic SDK Usage

```python
from software_sdk import ReliabilityMonitor

monitor = ReliabilityMonitor(
    project_name="my-agent",
    api_url="https://YOUR_SOFTWARE_URL",
    api_key="sw_..."
)

with monitor.track_workflow("research-task") as workflow:
    workflow.track_stage("search", status="completed", success=True, latency_ms=1200, confidence=0.94)
    workflow.log_tool_call("parallel_search", success=True, latency_ms=1200, result_count=5)
    workflow.log_model_call("llama3.2:3b", success=True, latency_ms=5000, confidence=0.91)
    workflow.complete(success=True, confidence=0.91)
```

## Pages

```text
/                  Landing page
/install           One-click SDK installer page
/benchmarks        Benchmark runner and sample data generator
/register          Create account
/login             Login
/projects          Manage projects
/api-keys          Manage API keys
/pricing           Usage plans
/demo              Demo and request access
/dashboard         Reliability dashboard
/developer-docs    Documentation home
/docs/quick-start  Quick start guide
```

## Documentation

- [QUICKSTART.md](QUICKSTART.md)
- [INSTALL.md](INSTALL.md)
- [SDK_CLI_GUIDE.md](SDK_CLI_GUIDE.md)
- [installer_report.md](installer_report.md)
- [DOCS.md](DOCS.md)
- [authentication.md](authentication.md)
- [api_key_management.md](api_key_management.md)
- [pricing.md](pricing.md)
- [subscription_system.md](subscription_system.md)
- [usage_tracking.md](usage_tracking.md)
- [SDK_INTEGRATION_GUIDE.md](SDK_INTEGRATION_GUIDE.md)

## Examples

```text
examples/simple_agent.py
examples/search_agent.py
examples/research_agent.py
examples/multi_step_workflow.py
```

## API

Auth:

```text
POST /auth/register
POST /auth/login
POST /auth/logout
GET  /auth/me
```

Projects:

```text
POST   /api/projects
GET    /api/projects
GET    /api/projects/{project_id}
DELETE /api/projects/{project_id}
```

API Keys:

```text
POST   /api/projects/{project_id}/api-keys
GET    /api/projects/{project_id}/api-keys
DELETE /api/projects/{project_id}/api-keys/{key_id}
```

Billing:

```text
GET  /api/billing/plans
GET  /api/billing/me
POST /api/billing/checkout
POST /api/billing/portal
POST /api/billing/webhook
POST /api/billing/subscribe
GET  /api/admin/usage-analytics
GET  /api/admin/subscription-analytics
```

Customer validation:

```text
POST /api/request-access
POST /api/analytics/sdk-installation
GET  /api/admin/customer-validation
```

Auto-recovery:

```text
POST /api/sdk/workflows/recover
GET  /api/dashboard/recovery-analytics
```

Reliability Copilot:

```text
GET  /api/copilot/recommendations
GET  /api/copilot/summary
```

Autonomous optimizer:

```text
POST /api/optimizer/run
POST /api/optimizer/rollback
GET  /api/optimizer/history
GET  /api/optimizer/stats
```

Meta-reliability decisions:

```text
POST /api/decisions/validate
POST /api/decisions/approve
POST /api/decisions/reject
GET  /api/decisions/pending
```

Team workspaces:

```text
POST /api/orgs
GET  /api/orgs
POST /api/orgs/invite
POST /api/orgs/remove
POST /api/orgs/transfer-ownership
GET  /api/orgs/members
```

SDK ingestion:

```text
POST /api/sdk/workflows/start
POST /api/sdk/workflows/stage
POST /api/sdk/workflows/model-call
POST /api/sdk/workflows/tool-call
POST /api/sdk/workflows/error
POST /api/sdk/workflows/predict
POST /api/sdk/workflows/complete
```

## Supabase Persistence

Software can mirror benchmark runs and persist authenticated chat history in
Supabase. Configure `SUPABASE_URL` and `SUPABASE_ANON_KEY`, then run
[`supabase_schema.sql`](supabase_schema.sql) in the Supabase SQL editor.

Setup and API details are in [`SUPABASE_SETUP.md`](SUPABASE_SETUP.md).
Supabase Authentication provides sign-up, login, logout, password reset,
persistent browser sessions, protected dashboard pages, and user-scoped
benchmark history.

## Production Notes

Set these environment variables:

```text
SOFTWARE_JWT_SECRET=replace-with-a-long-random-secret
SOFTWARE_ENABLE_BOOTSTRAP_DEV_KEY=false
SOFTWARE_API_DB_PATH=/app/Software/data/software_reliability.db
RELIABILITY_DB_PATH=/app/Software/data/reliability.db
```

See [deployment.md](deployment.md) for deployment details.

