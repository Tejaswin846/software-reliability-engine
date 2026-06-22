# Intelligent Auto-Recovery Engine Report

Generated: 2026-06-21

## Goal

Move Software from failure detection to automatic failure correction.

## Failure Categories

The recovery engine detects:

```text
search_failure
extraction_failure
model_timeout
tool_timeout
model_failure
low_confidence
```

Signals used:

- failed tool calls
- failed model calls
- error type
- error message
- stage name
- tool name
- latency
- confidence below 0.75

## Recovery Actions

### Search Failure

```text
switch_provider
retry_search
```

### Extraction Failure

```text
retry_extraction
switch_extraction_strategy
```

### Model Failure / Model Timeout

```text
retry_model
switch_backup_model
```

### Tool Timeout

```text
retry_tool
switch_provider
```

### Low Confidence

```text
retry_model
switch_backup_model
```

## Database

Created:

```text
recovery_events
```

Tracked fields:

- workflow_id
- user_id
- project_id
- api_key_id
- failure_category
- recovery_action
- attempt_number
- success
- recovery_latency_ms
- reason
- created_at

## API

Created:

```text
POST /api/sdk/workflows/recover
GET  /api/dashboard/recovery-analytics
```

SDK method:

```python
with monitor.track_workflow("task") as workflow:
    ...
    recovery = workflow.recover()
```

## Dashboard Widgets

Added:

- Recoveries Today
- Recovery Success Rate
- Average Recovery Latency
- Top Failure Categories

## Current Recovery Behavior

The engine is deterministic and offline. It does not call external providers yet.

For this phase, "automatic recovery" means:

1. classify the failure
2. select the best recovery action
3. record the recovery attempt
4. expose recovery metrics

The next production step is connecting these actions to actual tool/model retry handlers.
