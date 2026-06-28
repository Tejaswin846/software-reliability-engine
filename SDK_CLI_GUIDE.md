# Software SDK CLI Guide

The `software` CLI connects external AI-agent projects to the Software
reliability dashboard. Installing the SDK is public; protected cloud APIs need
Clerk login or a project API key.

## Install

```bash
pip install software-sdk
npm install software-sdk
```

Local repo development:

```bash
pip install -e .
```

## Public/Local Mode

No login is required for local validation, local plan creation, dry-run
examples, sandbox workflows, docs, or downloads.

## Optional Cloud Login

`software login` saves your Software API URL, API key, and default project name.

```bash
software login
```

Non-interactive:

```bash
software login \
  --api-url https://software-reliability-engine.onrender.com \
  --api-key sw_... \
  --project-name my-agent
```

The CLI also supports:

```text
SOFTWARE_API_URL
SOFTWARE_API_KEY
SOFTWARE_PROJECT_NAME
```

## Commands

`software init` creates `software.config.json`.

`software test` sends a complete cloud test workflow when an API key is
configured.

`software status` checks API connectivity, project binding, and dashboard URL.

Protected API calls without credentials return a clear message that local SDK
use remains available without signing in.
