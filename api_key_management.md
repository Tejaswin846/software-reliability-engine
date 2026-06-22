# Software API Key Management

Phase 16 makes SDK ingestion project-scoped.

## Project Endpoints

```text
POST   /api/projects
GET    /api/projects
GET    /api/projects/{project_id}
DELETE /api/projects/{project_id}
```

All project routes require:

```text
Authorization: Bearer YOUR_JWT
```

## API Key Endpoints

```text
POST   /api/projects/{project_id}/api-keys
GET    /api/projects/{project_id}/api-keys
DELETE /api/projects/{project_id}/api-keys/{key_id}
```

## Create API Key

```bash
curl -X POST http://127.0.0.1:8300/api/projects/PROJECT_ID/api-keys \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/json" \
  -d "{}"
```

The full API key is returned only once:

```json
{
  "ok": true,
  "api_key": "sw_...",
  "message": "Copy this API key now. It will not be shown again."
}
```

## SDK Usage

```python
from software_sdk import ReliabilityMonitor

monitor = ReliabilityMonitor(
    project_name="my-agent",
    api_url="https://YOUR_PUBLIC_URL",
    api_key="sw_..."
)
```

SDK requests send the API key in:

```text
X-Software-API-Key: sw_...
```

## Security

- Full API keys are never stored.
- Software stores SHA-256 hashes of API keys.
- API key lists only show prefixes.
- Deleting a key deactivates it by setting `is_active = 0`.
- SDK requests are rejected when a key is missing, invalid, inactive, or tied to another project.

## Dashboard Scope

Authenticated dashboard requests use:

```text
GET /api/me/dashboard
```

This endpoint only returns projects and SDK workflows owned by the authenticated user.
