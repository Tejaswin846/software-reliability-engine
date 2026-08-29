# Matrixs Zero-Code Connector Guide

The `matrixs` CLI connects Python AI-agent projects to the Matrixs reliability
dashboard without requiring source-code instrumentation or putting credentials in the command.

## Install

```bash
pip install git+https://github.com/Tejaswin846/software-reliability-engine.git
```

Local repo development:

```bash
pip install -e .
```

## Prepare Project Credentials

Create or select a cloud project, open `/api-keys`, and keep its Project ID and
API key ready. They are entered later on a page served only by the local CLI.

## Connect

Run the same clean command beside the Python project:

```bash
matrixs connect
```

Matrixs discovers supported projects and asks permission. If approved, it opens a
nonce-protected loopback page for the Project ID and API key, creates a timestamped
backup, writes reversible configuration, saves the credential in `.matrixs/.env`,
and sends a real verification workflow.

Decline automatic integration when prompted, or run `matrixs connect --manual`,
to open the manual guide without changing project files.

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
