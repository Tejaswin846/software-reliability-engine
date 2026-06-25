# Upstash Redis Integration

Software uses the official `upstash-redis` Python SDK as an ephemeral
infrastructure layer. It does not replace Qdrant or Supabase.

## Responsibilities

| System | Responsibility |
| --- | --- |
| Upstash Redis | Caching, temporary state, sessions, queues, rate limits, locks |
| Qdrant | Durable user-scoped semantic memory |
| Supabase | Durable chats, messages, authentication, and benchmark mirrors |
| SQLite | Reliability, workflow, billing, and SaaS application records |

## Configuration

```text
UPSTASH_REDIS_REST_URL=https://your-database.upstash.io
UPSTASH_REDIS_REST_TOKEN=replace-with-your-upstash-rest-token
```

Optional tuning:

```text
SOFTWARE_REDIS_KEY_PREFIX=software
SOFTWARE_AI_CACHE_TTL_SECONDS=3600
SOFTWARE_CONVERSATION_STATE_TTL_SECONDS=21600
SOFTWARE_SESSION_CACHE_TTL_SECONDS=3600
SOFTWARE_REDIS_QUEUE_MAX_LENGTH=10000
SOFTWARE_REDIS_RETRIES=2
SOFTWARE_REDIS_RETRY_INTERVAL_SECONDS=0.25
SOFTWARE_API_RATE_LIMIT_REQUESTS=300
SOFTWARE_API_RATE_LIMIT_WINDOW_SECONDS=60
```

Do not commit the REST token. Add both required credentials as secret
environment variables in Render.

## Client Behavior

`redis_client.py` initializes one reusable connectionless REST client. The
official SDK retries transient requests. Software performs one additional
client recreation after a failed operation so a stale HTTP transport does not
remain in process.

When Redis is missing or unavailable:

- durable writes still go to Supabase, SQLite, and Qdrant as applicable
- rate limiting fails open
- locks fail open only when Redis itself is unavailable
- cache and queue operations return safe empty results
- health responses report the degraded state

## AI Response Cache

Assistant responses can be cached by user, prompt, and model. User message
creation checks this cache and returns `cached_ai_response` when present.
Assistant message creation stores a response when its metadata contains the
source `prompt` or `request`.

## Conversation and Session State

Chat snapshots use short TTLs and are refreshed after message writes. Supabase
remains the durable source of truth. Authenticated user lookups are cached by a
SHA-256 fingerprint of the session token; raw tokens are never used as Redis
keys.

## Queues

`enqueue_background_job()` and `dequeue_background_job()` provide a bounded
Redis list queue. Benchmark completion currently queues a dashboard refresh
event. A future worker can consume the queue without changing request APIs.

## Rate Limiting

API, authentication, and reliability routes use an atomic Redis script with a
fixed time window. Responses include:

```text
X-RateLimit-Limit
X-RateLimit-Remaining
X-RateLimit-Reset
```

Exhausted callers receive HTTP `429` with `Retry-After`.

## Distributed Locks

`distributed_lock()` uses `SET NX PX` and token-checked Lua release. Benchmark
runs for the same user and model are locked to prevent duplicate concurrent
execution.

## Health and Dashboard

```text
GET /api/integrations/redis/health
GET /health
GET /status
GET /metrics
```

The dashboard shows connection status, latency, cache hits, cache misses, hit
rate, queue depth, and memory usage. The endpoint never returns the Redis URL
path, REST token, or other credentials.
