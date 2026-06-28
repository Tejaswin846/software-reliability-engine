# Software SDK Integration Guide

Software is now usable as an installable Python SDK for AI-agent reliability monitoring.

The SDK lets developers send workflow telemetry into the Software dashboard:

- workflow starts
- stage events
- model calls
- tool calls
- errors
- completion state
- failure prediction requests
- guardrail recommendations

## Install Locally

From the project root:

```bash
pip install -e .
```

The SDK uses only Python standard libraries.

For normal SDK installation:

```bash
pip install software-sdk
npm install software-sdk
```

No login is required for installation, local validation, local plans, dry-run
examples, or sandbox workflows.

Optional cloud mode requires a project API key:

```bash
software login
software init
software test
software status
```

## API Key

The development API key is:

```text
dev-key
```

The server accepts keys from:

```text
SOFTWARE_SDK_API_KEYS
```

Example:

```bash
SOFTWARE_SDK_API_KEYS=dev-key,team-key uvicorn app:app --host 0.0.0.0 --port 8300
```

All SDK requests must send:

```text
X-Software-API-Key: dev-key
```

The SDK does this automatically.

## Basic Usage

```python
from software_sdk import ReliabilityMonitor

monitor = ReliabilityMonitor(
    project_name="my-agent",
    api_url="https://YOUR_PUBLIC_URL",
    api_key="dev-key",
)

with monitor.track_workflow("research-task") as workflow:
    workflow.track_stage("search")
    workflow.log_tool_call("parallel_search", success=True, latency_ms=1200)

    workflow.track_stage("extraction")
    workflow.log_tool_call("parallel_extract", success=True, latency_ms=1800)

    workflow.track_stage("generation")
    workflow.log_model_call("llama3.2:3b", success=True, latency_ms=5000)

    prediction = workflow.predict_failure()
    guardrail = workflow.apply_guardrail()

    workflow.complete(
        success=True,
        confidence=0.91,
        metadata={
            "prediction": prediction,
            "guardrail": guardrail,
        },
    )

monitor.flush()
```

## Run The Example

For local Software:

```bash
set SOFTWARE_API_URL=http://127.0.0.1:8300
set SOFTWARE_API_KEY=dev-key
python examples/custom_agent_example.py
```

For the cloud deployment:

```bash
set SOFTWARE_API_URL=https://YOUR_PUBLIC_URL
set SOFTWARE_API_KEY=dev-key
python examples/custom_agent_example.py
```

Then open:

```text
https://YOUR_PUBLIC_URL/dashboard
```

The dashboard now includes an `SDK Workflows` section.

## Server API Endpoints

The SDK sends data to:

- `POST /api/sdk/workflows/start`
- `POST /api/sdk/workflows/stage`
- `POST /api/sdk/workflows/model-call`
- `POST /api/sdk/workflows/tool-call`
- `POST /api/sdk/workflows/error`
- `POST /api/sdk/workflows/complete`
- `POST /api/sdk/workflows/predict`

Dashboard API:

- `GET /api/dashboard/sdk-workflows`

## ReliabilityMonitor Methods

```python
monitor.track_workflow(workflow_name)
monitor.track_stage(workflow_id, stage_name)
monitor.log_model_call(workflow_id, model, success, latency_ms)
monitor.log_tool_call(workflow_id, tool_name, success, latency_ms)
monitor.log_error(workflow_id, error_message, error_type="error")
monitor.predict_failure(workflow_id)
monitor.apply_guardrail(workflow_id)
monitor.flush()
```

## Workflow Methods

```python
workflow.track_stage(stage_name)
workflow.log_tool_call(tool_name, success, latency_ms)
workflow.log_model_call(model, success, latency_ms)
workflow.log_error(error_type, error_message)
workflow.predict_failure()
workflow.apply_guardrail()
workflow.complete(success=True, confidence=0.91)
```

## Failure Handling

By default, the SDK does not crash your agent if Software is temporarily unavailable.

Failed sends are buffered locally:

```python
monitor.flush()
```

Use strict mode when you want SDK failures to raise exceptions:

```python
monitor = ReliabilityMonitor(
    project_name="my-agent",
    api_url="https://YOUR_PUBLIC_URL",
    api_key="dev-key",
    raise_on_error=True,
)
```

## What Appears In The Dashboard

The Software dashboard shows:

- total SDK workflows
- SDK success rate
- average SDK latency
- recent workflow names
- workflow status
- predicted risk
- guardrail action

This turns Software from a passive benchmark dashboard into a developer integration layer for real AI agents.
