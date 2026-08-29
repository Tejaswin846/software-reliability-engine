# Matrixs Zero-Code Connector Guide

The `matrixs` CLI connects Python AI-agent projects to the Matrixs reliability
dashboard without requiring source-code instrumentation or a copied permanent API key.

## Install

```bash
pip install git+https://github.com/Tejaswin846/software-reliability-engine.git
```

Local repo development:

```bash
pip install -e .
```

## Generate a One-Time Command

Create or select a cloud project, open `/api-keys`, and choose **Generate
connection command**. The token expires after 15 minutes and works once.

## Connect

Run the generated command beside the Python project:

```bash
matrixs connect --token mxct_... --api-url https://software-reliability-engine.onrender.com
```

Matrixs discovers supported projects, shows the exact plan, asks permission,
creates a timestamped backup, writes reversible configuration, exchanges the
token for a local project credential, and sends a real verification workflow.

## Commands

```bash
matrixs status
matrixs run
matrixs test
matrixs undo
matrixs disconnect
```

Use `matrixs status --offline` for a local-only check. Use `matrixs connect
--dry-run` to inspect the plan without changing the project.

## Files and Safety

```text
.matrixs/config.json       non-secret connection and startup configuration
.matrixs/.env              Git-ignored project credential
.matrixs/runtime/          Matrixs-owned runtime bootstrap
.matrixs/backups/          timestamped reversible backups
```

Matrixs does not edit ordinary application source files. It refuses unsafe
symbolic-link targets, backs up every changed path, hides secrets from plans
and status output, and automatically restores the current backup if connection
verification fails. The former `software` command remains a compatibility alias.
