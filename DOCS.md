# Software Documentation

Software is a reliability platform for AI agents.

## Documentation Map

| Page | Purpose |
| --- | --- |
| Getting Started | Understand core concepts and workflow |
| Installation | Install SDK and run the server |
| Authentication | Clerk sign-up, login, reset, OAuth, and JWT/session usage |
| Projects | Create and manage project scopes |
| API Keys | Generate, store, and revoke SDK keys |
| Pricing | Free, Pro, and Enterprise plan limits |
| Subscription System | Plan, subscription, and billing-period behavior |
| Usage Tracking | Workflow, model-call, tool-call, and API request metering |
| Customer Validation | Request access, SDK-install analytics, and funnel reporting |
| Auto-Recovery | Failure categories, recovery actions, and recovery metrics |
| SDK Usage | Instrument external agents |
| API Reference | Endpoint reference |
| Dashboard Guide | Understand metrics and views |
| Guardrails Guide | Use prediction and guardrail recommendations |
| Troubleshooting | Fix common setup issues |

The same docs are available in the web app:

```text
/developer-docs
/docs/quick-start
/docs/getting-started
/docs/installation
/docs/authentication
/docs/projects
/docs/api-keys
/docs/sdk-usage
/docs/api-reference
/docs/dashboard-guide
/docs/guardrails-guide
/docs/troubleshooting
/pricing
/demo
```

## Core Concepts

### User

An account owner authenticated by Clerk. Software stores the Clerk user id on user-owned rows.

### Project

A project groups workflows and API keys. Users only see their own projects and project-scoped telemetry.

### API Key

A project-scoped SDK credential. Full keys are shown once and stored only as hashes.

### Workflow

One complete agent run, such as a research task or coding task.

### Stage

A step inside a workflow, such as planning, search, extraction, generation, validation, or completion.

### Model Call

A call to an LLM or model wrapper. Software tracks model name, success, latency, and confidence.

### Tool Call

A call to an external or internal tool. Software tracks tool name, success, latency, result count, and confidence.

### Prediction

A probability estimate for workflow failure based on submitted events.

### Guardrail

A recommended action:

- continue
- increase_observation
- retry_failed_stage
- escalate

### Plan

A usage tier that controls project, API key, and monthly workflow limits.

### Subscription

The active plan for a user.

### Usage Record

A metered event for workflows, model calls, tool calls, or API requests.

## SDK Example

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
    workflow.track_stage("generation", status="completed", success=True, latency_ms=5000, confidence=0.91)
    workflow.log_model_call("llama3.2:3b", success=True, latency_ms=5000, confidence=0.91)
    workflow.complete(success=True, confidence=0.91)
```

## Auth Endpoints

```text
POST /auth/register
POST /auth/login
POST /auth/logout
GET  /auth/me
```

Clerk handles the browser sign-up, login, password reset, email verification,
Google OAuth, GitHub OAuth, and session lifecycle. SDK installation remains
public:

```bash
pip install software-sdk
npm install software-sdk
```

## Project Endpoints

```text
POST   /api/projects
GET    /api/projects
GET    /api/projects/{project_id}
DELETE /api/projects/{project_id}
```

## API Key Endpoints

```text
POST   /api/projects/{project_id}/api-keys
GET    /api/projects/{project_id}/api-keys
DELETE /api/projects/{project_id}/api-keys/{key_id}
```

## Billing Endpoints

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

## Customer Validation Endpoints

```text
POST /api/request-access
POST /api/analytics/sdk-installation
GET  /api/admin/customer-validation
```

## Auto-Recovery Endpoints

```text
POST /api/sdk/workflows/recover
GET  /api/dashboard/recovery-analytics
```

## Reliability Copilot Endpoints

```text
GET  /api/copilot/recommendations
GET  /api/copilot/summary
```

## Autonomous Optimizer Endpoints

```text
POST /api/optimizer/run
POST /api/optimizer/rollback
GET  /api/optimizer/history
GET  /api/optimizer/stats
```

## Meta-Reliability Endpoints

```text
POST /api/decisions/validate
POST /api/decisions/approve
POST /api/decisions/reject
GET  /api/decisions/pending
```

## Team Workspace Endpoints

```text
POST /api/orgs
GET  /api/orgs
POST /api/orgs/invite
POST /api/orgs/remove
POST /api/orgs/transfer-ownership
GET  /api/orgs/members
```

## SDK Endpoints

```text
POST /api/sdk/workflows/start
POST /api/sdk/workflows/stage
POST /api/sdk/workflows/model-call
POST /api/sdk/workflows/tool-call
POST /api/sdk/workflows/error
POST /api/sdk/workflows/predict
POST /api/sdk/workflows/complete
```

## Dashboard

The dashboard is available at:

```text
/dashboard
```

If a user is logged in, the dashboard loads project-scoped data from:

```text
/api/me/dashboard
```

Otherwise it loads global data from:

```text
/api/dashboard
```

## Troubleshooting

### Invalid API key

Generate a new key at `/api-keys`.

### No workflow appears

Check:

- `SOFTWARE_API_URL`
- `SOFTWARE_API_KEY`
- workflow completion
- server health at `/health`

### Cannot access project

Projects are user-owned. Sign in with the Clerk account that created the project.
