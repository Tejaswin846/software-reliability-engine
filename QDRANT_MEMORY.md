# Qdrant Cloud Memory

Software uses Qdrant Cloud for user-scoped long-term chat memory.

## Configuration

Set these environment variables locally and on Render:

```text
QDRANT_URL=https://your-cluster.region.cloud.qdrant.io
QDRANT_API_KEY=replace-with-your-qdrant-api-key
```

Do not commit the API key. The application creates the `software_memory`
collection automatically with 256-dimensional cosine vectors and indexes the
`user_id` and `created_at` payload fields.

## Chat Integration

For every authenticated user message sent to:

```text
POST /api/chats/{chat_id}/messages
```

Software:

1. searches Qdrant for relevant memories belonging to that user,
2. saves the chat message in Supabase,
3. stores the user message in Qdrant,
4. returns relevant items in `memory_context`.

The response generator can prepend `memory_context` to its model prompt.

## Memory APIs

```text
GET /api/memory/health
GET /api/memory/recent
GET /api/memory/search?query=...
```

If Qdrant is unavailable, search returns an empty list and saves return a
structured failure result. Chat persistence remains operational.
