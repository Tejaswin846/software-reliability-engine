# Software SDK CLI Guide

The `software` CLI connects external AI-agent projects to the Software reliability dashboard.

## Install

```bash
pip install software-sdk
```

Local repo development:

```bash
pip install -e .
```

## Commands

### `software login`

Saves your Software API URL, API key, and default project name.

```bash
software login
```

Non-interactive:

```bash
software login \
  --api-url https://software-platform.onrender.com \
  --api-key sw_... \
  --project-name my-agent
```

Writes:

```text
~/.software/config.json
```

The command verifies the API key by calling:

```text
GET /api/sdk/status
```

### `software init`

Creates project-local config:

```bash
software init
```

Writes:

```text
software.config.json
```

The generated project config includes:

```json
{
  "api_url": "https://software-platform.onrender.com",
  "config_version": 1,
  "project_name": "my-agent",
  "sdk": "software-sdk"
}
```

The API key is not written to this file by default.

### `software test`

Sends a complete test workflow:

```bash
software test
```

The test workflow records:

- workflow start
- stage event
- tool call
- model call
- workflow completion

It uses the same API routes real agents use:

```text
POST /api/sdk/workflows/start
POST /api/sdk/workflows/stage
POST /api/sdk/workflows/tool-call
POST /api/sdk/workflows/model-call
POST /api/sdk/workflows/complete
```

### `software status`

Checks API connectivity and project binding:

```bash
software status
```

It prints:

- API URL
- project name
- connected project ID
- latency
- dashboard URL

## Config Resolution Order

The CLI reads config in this order:

1. Environment variables
2. `software.config.json`
3. `~/.software/config.json`
4. Defaults

Supported environment variables:

```text
SOFTWARE_API_URL
SOFTWARE_API_KEY
SOFTWARE_PROJECT_NAME
```

## Troubleshooting

If `software status` says the API is unreachable:

- confirm the API URL is correct
- confirm the Render service is awake
- open `/health` in the browser

If `software status` says the API key is invalid:

- generate a new key in `/api-keys`
- run `software login` again
- make sure the key belongs to the project you want to track

If `software test` succeeds but you do not see the workflow:

- open `/dashboard`
- check the SDK Workflows panel
- refresh the page
