-- Software Reliability Supabase tables.
-- Run this in the Supabase SQL editor before enabling the integration.

CREATE TABLE IF NOT EXISTS public.chats (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT,
    title TEXT NOT NULL DEFAULT 'New chat',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE TABLE IF NOT EXISTS public.messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL REFERENCES public.chats(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE TABLE IF NOT EXISTS public.benchmark_runs (
    run_id TEXT PRIMARY KEY,
    user_id TEXT,
    model TEXT NOT NULL,
    provider_url TEXT,
    environment TEXT NOT NULL DEFAULT 'real_world',
    total_workflows INTEGER NOT NULL DEFAULT 0,
    successful INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    success_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    failure_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    reliability_score_v2 DOUBLE PRECISION NOT NULL DEFAULT 0,
    reliability_band_v2 TEXT,
    average_execution_time DOUBLE PRECISION NOT NULL DEFAULT 0,
    average_confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    retries INTEGER NOT NULL DEFAULT 0,
    rollbacks INTEGER NOT NULL DEFAULT 0,
    escalations INTEGER NOT NULL DEFAULT 0,
    stops INTEGER NOT NULL DEFAULT 0,
    tool_reliability DOUBLE PRECISION NOT NULL DEFAULT 0,
    timeout_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    workflow_results JSONB NOT NULL DEFAULT '[]'::JSONB
);

ALTER TABLE public.benchmark_runs
    ADD COLUMN IF NOT EXISTS user_id TEXT;

CREATE INDEX IF NOT EXISTS idx_chats_user_updated
    ON public.chats(user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_messages_chat_created
    ON public.messages(chat_id, created_at);

CREATE INDEX IF NOT EXISTS idx_benchmark_runs_created
    ON public.benchmark_runs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_benchmark_runs_user_created
    ON public.benchmark_runs(user_id, created_at DESC);

ALTER TABLE public.chats ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.benchmark_runs ENABLE ROW LEVEL SECURITY;

-- Software keeps SUPABASE_ANON_KEY server-side and performs user ownership checks
-- in FastAPI. These policies permit that server-side client to access the tables.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.chats TO anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.messages TO anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.benchmark_runs TO anon;

DROP POLICY IF EXISTS "software_server_chats" ON public.chats;
CREATE POLICY "software_server_chats"
    ON public.chats FOR ALL TO anon
    USING (TRUE) WITH CHECK (TRUE);

DROP POLICY IF EXISTS "software_server_messages" ON public.messages;
CREATE POLICY "software_server_messages"
    ON public.messages FOR ALL TO anon
    USING (TRUE) WITH CHECK (TRUE);

DROP POLICY IF EXISTS "software_server_benchmark_runs" ON public.benchmark_runs;
CREATE POLICY "software_server_benchmark_runs"
    ON public.benchmark_runs FOR ALL TO anon
    USING (TRUE) WITH CHECK (TRUE);
