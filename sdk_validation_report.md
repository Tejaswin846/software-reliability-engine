# Software SDK Validation Report

Generated: 2026-06-21T14:50:47+05:30

## Goal

Validate that an external AI agent can install and use the Software SDK end to end:

```text
Demo Agent
  -> software_sdk
  -> Public Software API
  -> SQLite database
  -> Dashboard
```

## Validation Setup

External demo agent location:

```text
C:\Users\user\Desktop\nexora-sdk-demo-agent
```

SDK source installed from:

```text
C:\Users\user\Desktop\Nexora ai
```

Public API used:

```text
https://auction-identical-ranger-daily.trycloudflare.com
```

Project name used for the clean validation run:

```text
external-demo-agent-phase15-final
```

## Installation Proof

The demo agent was created outside the Software project and used its own virtual environment.

Commands used:

```bash
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e "C:\Users\user\Desktop\Nexora ai"
.\.venv\Scripts\python -c "import software_sdk; print(software_sdk.__file__)"
```

Installed SDK import path:

```text
C:\Users\user\Desktop\Nexora ai\software_sdk\__init__.py
```

Package installed:

```text
software-sdk==0.1.0
```

## Demo Agent Run

Command used:

```bash
$env:SOFTWARE_PROJECT_NAME='external-demo-agent-phase15-final'
$env:SOFTWARE_API_URL='https://auction-identical-ranger-daily.trycloudflare.com'
$env:SOFTWARE_API_KEY='dev-key'
.\.venv\Scripts\python -u demo_agent.py
```

Run artifacts:

```text
C:\Users\user\Desktop\nexora-sdk-demo-agent\validation_artifacts\demo_agent_run_final.log
C:\Users\user\Desktop\nexora-sdk-demo-agent\validation_artifacts\run_summary.json
C:\Users\user\Desktop\nexora-sdk-demo-agent\validation_artifacts\dashboard_sdk_snapshot.json
C:\Users\user\Desktop\nexora-sdk-demo-agent\validation_artifacts\database_verification.json
C:\Users\user\Desktop\nexora-sdk-demo-agent\validation_artifacts\public_metrics_snapshot.json
```

## Run Results

```text
Total workflows: 100
Successful workflows: 77
Failed workflows: 23
Success rate: 77.0%
Failure rate: 23.0%
Average confidence: 0.844
Average latency: 4272.88 ms
Model calls tracked: 100
Search tool calls tracked: 100
Extract tool calls tracked: 100
Prediction calls generated: 200
Guardrail calls generated: 200
SDK buffer remaining: 0
```

Final demo log excerpt:

```text
097/100 success=False confidence=0.683 latency_ms=4584 guardrail=escalate
098/100 success=True confidence=0.911 latency_ms=4440 guardrail=continue
099/100 success=True confidence=0.819 latency_ms=4327 guardrail=continue
100/100 success=True confidence=0.840 latency_ms=4869 guardrail=continue
```

## Public API Verification

Dashboard endpoint:

```text
GET /dashboard -> 200
```

SDK dashboard endpoint:

```text
GET /api/dashboard/sdk-workflows -> 200
```

Metrics endpoint:

```text
GET /metrics -> 200
```

Metrics snapshot:

```text
sdk_workflows: 201
sdk_success_rate: 77.11%
sdk_failure_rate: 22.89%
```

The total SDK workflow count is 201 because the public database also contains earlier Phase 14/partial Phase 15 validation records. The clean Phase 15 project-specific run contains exactly 100 workflows.

## Database Verification

Remote database:

```text
/home/azureuser/software-platform/Software/data/software_reliability.db
```

Project-specific database counts:

```text
project_name: external-demo-agent-phase15-final
workflows: 100
completed: 100
successful: 77
failed: 23
average_confidence: 0.84364
average_latency_ms: 4272.88
predictions_saved: 100
guardrails_saved: 100
```

SDK event distribution:

```text
workflow_start: 100
stage: 400
tool_call: 200
model_call: 100
error: 28
workflow_complete: 100
```

Guardrail distribution:

```text
continue: 77
increase_observation: 13
retry_failed_stage: 5
escalate: 5
```

## Validation Checklist

```text
External demo agent created: PASS
SDK installed into demo virtual environment: PASS
100 workflows executed: PASS
Workflows appeared in dashboard API: PASS
Model calls tracked: PASS
Tool calls tracked: PASS
Predictions generated: PASS
Guardrails logged: PASS
SQLite records created: PASS
Public dashboard reachable: PASS
```

## Evidence Chain

```text
Demo Agent:
  C:\Users\user\Desktop\nexora-sdk-demo-agent\demo_agent.py

SDK:
  software-sdk==0.1.0 installed in demo venv

Public API:
  https://auction-identical-ranger-daily.trycloudflare.com

Database:
  sdk_workflows rows for external-demo-agent-phase15-final: 100
  sdk_events rows for external-demo-agent-phase15-final: 928

Dashboard:
  /dashboard returned 200
  /api/dashboard/sdk-workflows returned SDK workflow data
```

## Conclusion

Phase 15 is validated.

Software now works as an installable monitoring SDK for external AI agents. A separate demo agent installed the SDK, submitted 100 workflow traces through the public API, created database records, generated predictions, logged guardrails, and surfaced the results through the dashboard.
