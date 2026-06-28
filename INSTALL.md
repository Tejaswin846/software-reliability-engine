# Install Software SDK

Software SDK installation is public. You do not need to sign in to read docs,
download the SDK, run local validation, create local plans, use dry-run
examples, or test sandbox workflows.

```bash
pip install software-sdk
npm install software-sdk
```

For local development from this repository:

```bash
pip install -e .
```

## Public/Local Mode

No login is required for:

- local validation
- local plan creation
- dry-run examples
- sandbox workflow tests
- SDK docs and examples

## Authenticated Cloud Mode

Login or a project API key is required for:

- cloud workflow execution
- saved projects
- user memory
- audit logs
- external app integrations
- team/workspace features

```bash
software login
# or
SOFTWARE_API_KEY=sw_...
```

If an unauthenticated client calls a protected cloud API, Software returns:

```text
Authentication required for this cloud feature. You can still install and use the SDK locally without signing in.
```

## Connect Cloud

Create a project and API key from the signed-in dashboard, then configure the
CLI:

```bash
software login --api-url https://software-reliability-engine.onrender.com --api-key sw_... --project-name my-agent
software init
software test
software status
```

The CLI stores credentials in:

```text
~/.software/config.json
```

Environment variables override saved config:

```bash
SOFTWARE_API_URL=https://software-reliability-engine.onrender.com
SOFTWARE_API_KEY=sw_...
SOFTWARE_PROJECT_NAME=my-agent
```
