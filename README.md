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
- production error, log, and performance monitoring with Sentry

## Sentry Monitoring

Install project dependencies and configure Sentry entirely through environment
variables:

```bash
pip install -r requirements.txt
```

```text
SENTRY_DSN=https://public-key@o0.ingest.sentry.io/0
SENTRY_TRACES_SAMPLE_RATE=0.2
SENTRY_ENABLE_LOGS=true
SENTRY_ENVIRONMENT=production
SENTRY_RELEASE=software@0.2.0
```

`SENTRY_DSN` is optional locally. When it is absent, monitoring is disabled
without preventing the application from starting. In production, Software
captures unhandled FastAPI and async-task exceptions, failed SDK agent/model/tool
events, Qdrant failures, and traced outgoing HTTPX calls. OpenAI and Claude
failures reported through the SDK model-call or error endpoints are categorized
without recording prompts, request bodies, authorization headers, cookies, API
keys, or passwords.

The `/health` and `/status` responses include a `monitoring` object showing
whether Sentry is configured and initialized. `SENTRY_TRACES_SAMPLE_RATE`
defaults to `0.2` and accepts values from `0.0` to `1.0`.

## Connected Apps

Set the connection-provider API key and Software encryption secrets in the
environment:

```text
COMPOSIO_API_KEY=replace-with-your-composio-api-key
INTEGRATION_ENCRYPTION_KEY=replace-with-a-long-random-secret
INTEGRATION_STATE_SECRET=replace-with-a-long-random-secret
```

Open `/apps` to search and connect Gmail, Outlook, Google and Microsoft
productivity apps, developer tools, storage providers, communication apps,
databases, and AI providers. Each user has isolated connections, connection
health, permission status, last-sync details, retry, and disconnect controls.
Provider credentials remain in the managed connection vault. Software stores
only encrypted connection metadata and resumable action state.

Server-side agent orchestration can attach native OpenAI Agents tools without
replacing existing tools:

```python
from integrations.composio_service import attach_user_tools

agent_tools = attach_user_tools(user_id, existing_tools)
```

SDK workflows receive available tool descriptors when the workflow starts:

```python
with monitor.track_workflow("connected-agent") as workflow:
    print(workflow.available_tools)
    result = workflow.execute_tool(
        "GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER",
        {},
        agent_name="research-agent",
    )
```

When an action requires an app that is not connected, the API returns a
`connection_required` response. The browser displays a native Software dialog,
starts authorization, returns to the original conversation, executes the
pending action, and emits a `software:integration-resumed` browser event with
the result.

Connected Apps routes:

```text
GET  /api/integrations
GET  /api/integrations/status
POST /api/integrations/connect
POST /api/integrations/disconnect
GET  /api/integrations/resume/{action_id}
GET  /api/sdk/tools
POST /api/sdk/tools/refresh
POST /api/sdk/tools/execute
```

Tool arguments and credentials are not written to reliability logs or Sentry.
Tool execution is never placed in the SDK retry buffer because repeating a
non-idempotent action could send a duplicate email, message, or calendar event.
See [CONNECTED_APPS.md](CONNECTED_APPS.md) for the complete flow and operations
guide.

## Upstash Redis

Software uses Upstash Redis only for ephemeral infrastructure:

- AI response caching
- temporary conversation snapshots
- authenticated session caching
- background job queues
- API rate limiting
- distributed workflow locks

Qdrant remains the long-term semantic memory store, and Supabase remains the
durable chat source of truth.

Configure the official Upstash Redis Python SDK with environment variables:

```text
UPSTASH_REDIS_REST_URL=https://your-database.upstash.io
UPSTASH_REDIS_REST_TOKEN=replace-with-your-upstash-rest-token
```

The SDK performs HTTP retry automatically. Software additionally recreates the
client after transport failures and degrades gracefully when Redis is not
configured. Operational status is available at:

```text
GET /api/integrations/redis/health
```

The dashboard displays connection status, latency, cache hits, cache misses,
cache hit rate, queue depth, and Redis memory usage. See
[UPSTASH_REDIS.md](UPSTASH_REDIS.md) for the complete architecture and
configuration reference.

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
/apps              Connect and manage external applications
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

Microsoft Clarity analytics is loaded globally when `CLARITY_PROJECT_ID` is
set. It tracks dashboard visits, benchmark runner visits, install clicks, and
completed benchmark runs.

Qdrant Cloud provides user-scoped long-term chat memory when `QDRANT_URL` and
`QDRANT_API_KEY` are configured. User messages are stored in the
`software_memory` collection, relevant memories are returned as
`memory_context`, and Qdrant outages do not interrupt chat persistence.

Upstash Redis provides short-lived caches, conversation and session state,
queues, rate limits, and distributed locks when
`UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` are configured. Redis
does not replace Qdrant memory or durable Supabase chat storage.

## Production Notes

Set these environment variables:

```text
SOFTWARE_JWT_SECRET=replace-with-a-long-random-secret
SOFTWARE_ENABLE_BOOTSTRAP_DEV_KEY=false
SOFTWARE_API_DB_PATH=/app/Software/data/software_reliability.db
RELIABILITY_DB_PATH=/app/Software/data/reliability.db
```

See [deployment.md](deployment.md) for deployment details.

