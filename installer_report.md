# Installer Report

Date: 2026-06-23

## Goal

Make Software feel installable from the website:

```text
Open website -> create project -> generate API key -> install SDK -> test connection -> view dashboard
```

## Added Website Page

Route:

```text
/install
```

Page file:

```text
install.html
```

The page shows:

- selected user project
- SDK project name
- API URL
- API key input
- SDK installation status
- step-by-step setup instructions
- copyable install commands
- downloadable Windows installer scripts
- test connection button

## Install Commands

PyPI future:

```bash
pip install software-sdk
```

Current GitHub install:

```bash
pip install git+https://github.com/Tejaswin846/software-reliability-engine.git
```

Local/development:

```bash
pip install -e .
```

## Downloadable Installer Files

Batch installer:

```text
install_software_sdk.bat
```

PowerShell installer:

```text
install_software_sdk.ps1
```

Download routes:

```text
/install_software_sdk.bat
/install_software_sdk.ps1
```

The installers:

- check that Python exists
- install the SDK from GitHub
- ask for API URL
- ask for API key
- ask for project name
- run `software login`
- run `software init`
- run `software test`
- run `software status`
- print success/failure

## Safety Note

The browser does not silently install software.

The install page only:

- copies commands
- downloads installer scripts
- tests API key connectivity when the user clicks Test Connection

The user still chooses whether to run the installer locally.

## API Added

Added:

```text
POST /api/sdk/test-workflow
```

This endpoint uses the same SDK API key authentication as normal SDK workflow ingestion. It creates a completed test workflow so the install page can prove the API key, project, and dashboard are connected.

## Dashboard Link

Added dashboard topbar link:

```text
Dashboard -> Install SDK
```

## CLI Support

The SDK already supports:

```bash
software login
software init
software test
software status
```

These commands are now used by the installer scripts and displayed on the install page.

## Validation Checklist

- `app.py` exposes `/install`
- `/health` includes installer assets in startup checks
- installer downloads are served by FastAPI
- install page is public
- install page loads projects after optional sign-in
- install page can generate a new API key
- install page can test an SDK workflow
- dashboard links to install page

## Result

Software now has a one-click install entry point for developers:

```text
/install
```

A new user can click Install SDK, download a Windows installer or copy a command, run the setup, and see a test workflow in the dashboard.
