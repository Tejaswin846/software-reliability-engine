# GitHub Setup

The Software project is already initialized as a local Git repository.

Local path:

```powershell
C:\Users\user\Desktop\Software
```

Initial commit:

```text
a93a94e Initial Software reliability platform
```

## Recommended Repository

Create a private GitHub repository:

```text
Tejaswin846/software-reliability-engine
```

Private is recommended because this is product infrastructure and may later contain deployment configuration.

## Option 1: GitHub CLI

Install GitHub CLI:

```powershell
winget install --id GitHub.cli
```

Authenticate:

```powershell
gh auth login
```

Create the repo and push:

```powershell
cd C:\Users\user\Desktop\Software
gh repo create Tejaswin846/software-reliability-engine --private --source . --remote origin --push
```

## Option 2: Browser

1. Open GitHub.
2. Create a new repository named:

```text
software-reliability-engine
```

3. Keep it empty. Do not initialize with README, `.gitignore`, or license.
4. Then run:

```powershell
cd C:\Users\user\Desktop\Software
git remote add origin https://github.com/Tejaswin846/software-reliability-engine.git
git push -u origin main
```

## Files Intentionally Not Committed

The repository excludes local/runtime files:

- `.env`
- `data/`
- `logs/`
- `artifacts/`
- SQLite databases
- generated SDK egg metadata
- Python cache files

This keeps secrets, runtime data, benchmark databases, and generated archives out of GitHub.
