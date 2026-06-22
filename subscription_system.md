# Software Subscription System

Phase 18 adds a subscription foundation to Software.

## Database Tables

### plans

Stores plan definitions:

```text
id
name
max_projects
max_api_keys
monthly_workflow_limit
created_at
metadata_json
```

Seeded plans:

```text
free
pro
enterprise
```

### subscriptions

Stores user subscriptions:

```text
id
user_id
plan_id
status
current_period_start
current_period_end
created_at
updated_at
metadata_json
```

Every new user receives an active Free subscription automatically.

### usage_records

Stores metered usage events:

```text
id
user_id
project_id
api_key_id
metric_type
quantity
created_at
metadata_json
```

## Billing APIs

```text
GET  /api/billing/plans
GET  /api/billing/me
POST /api/billing/subscribe
```

`/api/billing/subscribe` is a placeholder that changes the local subscription record. Before production billing, connect it to a real checkout flow.

## Admin Analytics

```text
GET /api/admin/usage-analytics
GET /api/admin/subscription-analytics
```

Admin access is controlled by:

```text
SOFTWARE_ADMIN_EMAILS=dev@software.local,admin@example.com
```

## Limit Enforcement

Software enforces:

- project count limits on `POST /api/projects`
- active API key limits on `POST /api/projects/{project_id}/api-keys`
- workflow monthly limits on `POST /api/sdk/workflows/start`

When a limit is exceeded, Software returns:

```text
402 Payment Required
```

with an upgrade message.
