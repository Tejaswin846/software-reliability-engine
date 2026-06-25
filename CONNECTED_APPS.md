# Connected Apps

Software exposes external applications as a native part of the existing agent
orchestration. It does not create a second agent or replace the current model,
workflow, authentication, memory, monitoring, or reliability layers.

## Supported Apps

Productivity:

- Gmail
- Outlook
- Google Calendar
- Google Sheets
- Microsoft Excel
- Notion

Communication:

- Slack
- Microsoft Teams
- Discord
- Telegram
- Webhooks

Development:

- GitHub
- GitLab
- Jira
- Linear

Storage:

- Google Drive
- OneDrive
- Dropbox
- Box

Database:

- Supabase
- PostgreSQL

AI:

- OpenAI
- Anthropic Claude
- Google Gemini
- Perplexity AI

## User Flow

1. The authenticated user opens `/apps`.
2. Software loads only that user's connections.
3. Connect starts the hosted OAuth or API-key authorization flow.
4. The provider redirects to `/api/integrations/callback`.
5. Software refreshes the user's available tools and returns to the original
   page.
6. Disconnect revokes and removes the selected user's connection.
7. Failed or expired authorization can be retried from the same app card.

The Apps page refreshes connection health every 15 seconds.

## Automatic Agent Flow

Existing workflows receive connected-app tool descriptors when they start.
When an agent requests a tool for an app that is not connected, Software
returns:

```json
{
  "connection_required": true,
  "app": {
    "id": "gmail",
    "name": "Gmail"
  },
  "pending_action_id": "resume_..."
}
```

The browser shows:

```text
This action requires Gmail.
Connect Gmail?
```

After authorization, Software executes the encrypted pending action, records
the result in the original reliability workflow, stores a non-sensitive resume
event in existing memory, returns to the same page, and dispatches:

```javascript
window.addEventListener("software:integration-resumed", (event) => {
  console.log(event.detail);
});
```

The user does not need to repeat the request.

## Security

- OAuth tokens and API keys are stored by the managed connection provider.
- Software never stores provider credentials.
- Opaque connection IDs, permissions, and pending actions are encrypted with
  Fernet before SQLite storage.
- Every connection and pending action is scoped to the authenticated user ID.
- Callback state is signed and expires after 20 minutes.
- Return URLs are restricted to local application paths.
- Tool arguments are excluded from workflow logs and Sentry.
- Non-idempotent app actions are never automatically replayed by the SDK retry
  buffer.

Required production variables:

```text
COMPOSIO_API_KEY=...
INTEGRATION_ENCRYPTION_KEY=...
INTEGRATION_STATE_SECRET=...
```

If the two integration secrets are omitted, Software derives them from
`SOFTWARE_JWT_SECRET` or `JWT_SECRET`. Dedicated values are recommended.

## API

```text
GET  /api/integrations
GET  /api/integrations/status
POST /api/integrations/connect
POST /api/integrations/disconnect
GET  /api/integrations/resume/{action_id}
```

Legacy tool endpoints remain available so existing integrations continue to
work.
