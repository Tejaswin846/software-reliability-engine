# Supabase Setup

Software uses Supabase as optional remote persistence for Clerk user profiles,
chats, messages, and benchmark run mirrors. Clerk owns authentication. SQLite
remains active for the existing reliability dashboard and APIs.

## Configure

1. Create a Supabase project.
2. Run `supabase_schema.sql` in the Supabase SQL editor.
   The file is migration-safe and can be run again if `chats`, `messages`, or
   `benchmark_runs` already exist. It creates missing tables and indexes, adds
   missing columns, restores constraints where possible, enables RLS, recreates
   the required policies, and installs the `chats.updated_at` trigger.
3. Set these server-only environment variables:

```text
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
```

Do not commit a real key. On Render, add both values under the Web Service
environment settings. Do not expose `SUPABASE_SERVICE_ROLE_KEY` to browser
JavaScript, SDK clients, or public docs.

## Verify

Start Software and request:

```text
GET /api/supabase/health
```

When Supabase is not configured or cannot be reached, existing benchmark and
dashboard APIs continue using SQLite. Benchmark responses include a
`supabase_sync` object describing whether the remote mirror succeeded.

## Chat APIs

These routes require a Clerk-authenticated Software user:

```text
POST /api/chats
POST /api/chats/{chat_id}/messages
GET  /api/chats/{chat_id}
GET  /api/chats/{chat_id}/messages
```

Opening a chat with `GET /api/chats/{chat_id}` returns the chat and its complete
ordered message history.

## Authentication

Clerk handles sign-up, login, logout, password reset, email verification,
Google OAuth, GitHub OAuth, and session/JWT validation. Software stores the
Clerk `sub` as the user id in SQLite and Supabase `user_profiles`, then uses
that same id on chats, messages, benchmark mirrors, projects, workflows, memory,
audit logs, API keys, and settings.

## Schema Verification

The final queries in `supabase_schema.sql` verify:

- every required Software column exists,
- the `public.user_profiles` table exists,
- RLS is enabled on all Software storage tables,
- the expected policies exist,
- the Software updated-at triggers exist.

The missing-column query should return zero rows.

Do not use Supabase Auth for Software account flows. The
server uses `SUPABASE_SERVICE_ROLE_KEY` only for storage writes and enforces
Clerk user ownership in the API before reading or writing user-scoped rows.
