# Software Quick Start

This guide takes a new developer from install to visible workflow telemetry in about five minutes.

## 1. Install

For normal SDK use:

```bash
pip install software-sdk
python -m software_sdk
```

For local development from this repository:

```bash
python -m pip install --upgrade pip
pip install -e .
python -m software_sdk
```

## 2. Start Software

```bash
pip install -r requirements.txt
uvicorn Software.app:app --host 127.0.0.1 --port 8300
```

Open:

```text
http://127.0.0.1:8300
```

## 3. Create Account

Open:

```text
http://127.0.0.1:8300/register
```

Create an account with email and password.

## 4. Create Project

Open:

```text
http://127.0.0.1:8300/projects
```

Create a project named:

```text
my-agent-dev
```

## 5. Generate API Key

Open:

```text
http://127.0.0.1:8300/api-keys
```

Select your project and create an API key.

Copy the full key immediately. Software only shows it once.

## 6. Run Example Agent

PowerShell:

```powershell
$env:SOFTWARE_API_URL="http://127.0.0.1:8300"
$env:SOFTWARE_API_KEY="sw_your_key"
python examples/simple_agent.py
```

Command Prompt:

```bat
set SOFTWARE_API_URL=http://127.0.0.1:8300
set SOFTWARE_API_KEY=sw_your_key
python examples/simple_agent.py
```

## 7. View Dashboard

Open:

```text
http://127.0.0.1:8300/dashboard
```

You should see your workflow in the SDK Workflows section.

## Other Examples

```bash
python examples/search_agent.py
python examples/research_agent.py
python examples/multi_step_workflow.py
```

## Expected Output

```text
Simple workflow sent to Software.
```

## Common Issues

`403 Invalid SDK API key`

Generate a new API key at `/api-keys` and update `SOFTWARE_API_KEY`.

`Workflow not visible`

Confirm you are viewing the same Software URL used by `SOFTWARE_API_URL`.

`Missing bearer token`

Login again at `/login`.
