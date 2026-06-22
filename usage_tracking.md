# Software Usage Tracking

Phase 18 adds usage tracking for commercial SaaS plans.

## Tracked Metrics

Software records these usage metrics:

```text
workflow
model_call
tool_call
api_request
```

## When Usage Is Recorded

### workflow

Recorded when a new SDK workflow starts:

```text
POST /api/sdk/workflows/start
```

Duplicate starts with the same workflow ID do not count again.

### model_call

Recorded when an SDK model call is logged:

```text
POST /api/sdk/workflows/model-call
```

### tool_call

Recorded when an SDK tool call is logged:

```text
POST /api/sdk/workflows/tool-call
```

### api_request

Recorded for:

- authenticated user API requests
- SDK requests with valid API keys

## Monthly Periods

Subscriptions store:

```text
current_period_start
current_period_end
```

If a period is stale, Software rolls it forward to the current month before calculating quota.

## Dashboard Usage

The dashboard shows:

- Current Plan
- Monthly Workflows
- Remaining Quota
- API Requests
- project count
- active API key count

Authenticated users see project-scoped billing data from:

```text
GET /api/me/dashboard
```

Direct billing data is available from:

```text
GET /api/billing/me
```

## Admin Usage Analytics

Admins can view aggregate usage with:

```text
GET /api/admin/usage-analytics
```

This returns totals grouped by metric type and by user.
