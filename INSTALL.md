# Install Software SDK

Software is designed to feel like a normal developer tool:

```bash
pip install software-sdk
software login
software init
software test
software status
```

## 1. Create a Project

Open your Software dashboard:

```text
https://software-platform.onrender.com/projects
```

Create a project for your AI agent, for example:

```text
customer-support-agent
```

## 2. Generate an API Key

Open:

```text
https://software-platform.onrender.com/api-keys
```

Generate a project API key. The full key is shown once.

## 3. Install the SDK

In your own AI-agent project:

```bash
pip install software-sdk
```

For local development from this repository:

```bash
pip install -e .
```

## 4. Log In From the CLI

```bash
software login
```

You will be asked for:

- API URL
- API key
- default project name

The CLI stores credentials in:

```text
~/.software/config.json
```

You can also pass values directly:

```bash
software login --api-url https://software-platform.onrender.com --api-key sw_... --project-name my-agent
```

## 5. Initialize Your Agent Project

```bash
software init
```

This creates:

```text
software.config.json
```

The file stores the project name and API URL. The API key remains in your user-level config or `SOFTWARE_API_KEY`.

## 6. Send a Test Workflow

```bash
software test
```

This sends a complete test workflow to the dashboard:

- workflow started
- stage tracked
- tool call logged
- model call logged
- workflow completed

## 7. Check Status

```bash
software status
```

This verifies:

- API connection
- API key validity
- connected project
- dashboard URL

## Environment Variables

The CLI also supports:

```bash
SOFTWARE_API_URL=https://software-platform.onrender.com
SOFTWARE_API_KEY=sw_...
SOFTWARE_PROJECT_NAME=my-agent
```

Environment variables override saved config.

## Minimal Python Example

```python
from software_sdk import ReliabilityMonitor

monitor = ReliabilityMonitor(
    project_name="my-agent",
    api_url="https://software-platform.onrender.com",
    api_key="sw_..."
)

with monitor.track_workflow("research-task") as workflow:
    workflow.track_stage("search", status="completed", success=True, latency_ms=1200, confidence=0.94)
    workflow.log_tool_call("parallel_search", success=True, latency_ms=1200, result_count=5)
    workflow.log_model_call("llama3.2:3b", success=True, latency_ms=5000, confidence=0.91)
    workflow.complete(success=True, confidence=0.91)
```
