# Supabase Setup

Software uses Supabase as optional remote persistence for chats, messages, and
benchmark run mirrors. SQLite remains active for the existing reliability
dashboard and APIs.

## Configure

1. Create a Supabase project.
2. Run `supabase_schema.sql` in the Supabase SQL editor.
3. In Supabase Authentication URL Configuration, add:

```text
https://YOUR_SOFTWARE_DOMAIN/login
https://YOUR_SOFTWARE_DOMAIN/reset-password
```

4. Enable Email authentication in Supabase.
5. Set these server environment variables:

```text
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
```

Do not commit a real key. On Render, add both values under the Web Service
environment settings.

## Verify

Start Software and request:

```text
GET /api/supabase/health
```

When Supabase is not configured or cannot be reached, existing benchmark and
dashboard APIs continue using SQLite. Benchmark responses include a
`supabase_sync` object describing whether the remote mirror succeeded.

## Chat APIs

These routes use the existing Software JWT authentication:

```text
POST /api/chats
POST /api/chats/{chat_id}/messages
GET  /api/chats/{chat_id}
GET  /api/chats/{chat_id}/messages
```

Opening a chat with `GET /api/chats/{chat_id}` returns the chat and its complete
ordered message history.

## Authentication

When Supabase is configured, these routes use Supabase Authentication:

```text
POST /auth/register
POST /auth/login
POST /auth/logout
GET  /auth/me
POST /auth/password-reset
POST /auth/password-update
```

Software sets an HttpOnly application session cookie after Supabase verifies the
credentials. This keeps the session across browser refreshes and protects
`/dashboard`, `/benchmarks`, `/failures`, `/install`, `/projects`, and
`/api-keys`.

If Supabase is not configured, local development continues to use the existing
SQLite authentication flow. Password reset requires Supabase.
