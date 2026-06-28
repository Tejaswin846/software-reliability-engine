-- Software Reliability Supabase migration.
-- Safe to run repeatedly in the Supabase SQL editor.

BEGIN;

-- Fail with a useful message if a same-named object exists but is not a table.
DO $$
DECLARE
    object_name TEXT;
    object_kind "char";
BEGIN
    FOREACH object_name IN ARRAY ARRAY['chats', 'messages', 'benchmark_runs']
    LOOP
        SELECT relation.relkind
        INTO object_kind
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname = object_name;

        IF object_kind IS NOT NULL AND object_kind NOT IN ('r', 'p') THEN
            RAISE EXCEPTION
                'public.% exists but is not a table. Rename or remove that object before running this migration.',
                object_name;
        END IF;
    END LOOP;
END
$$;

CREATE TABLE IF NOT EXISTS public.user_profiles (
    id TEXT PRIMARY KEY,
    clerk_user_id TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB
);

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

-- CREATE TABLE IF NOT EXISTS does not add missing columns to partial tables.
ALTER TABLE public.chats
    ADD COLUMN IF NOT EXISTS id TEXT,
    ADD COLUMN IF NOT EXISTS user_id TEXT,
    ADD COLUMN IF NOT EXISTS project_id TEXT,
    ADD COLUMN IF NOT EXISTS title TEXT DEFAULT 'New chat',
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::JSONB;

ALTER TABLE public.messages
    ADD COLUMN IF NOT EXISTS id TEXT,
    ADD COLUMN IF NOT EXISTS chat_id TEXT,
    ADD COLUMN IF NOT EXISTS user_id TEXT,
    ADD COLUMN IF NOT EXISTS role TEXT,
    ADD COLUMN IF NOT EXISTS content TEXT,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::JSONB;

ALTER TABLE public.benchmark_runs
    ADD COLUMN IF NOT EXISTS run_id TEXT,
    ADD COLUMN IF NOT EXISTS user_id TEXT,
    ADD COLUMN IF NOT EXISTS model TEXT,
    ADD COLUMN IF NOT EXISTS provider_url TEXT,
    ADD COLUMN IF NOT EXISTS environment TEXT DEFAULT 'real_world',
    ADD COLUMN IF NOT EXISTS total_workflows INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS successful INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS failed INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS success_rate DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS failure_rate DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reliability_score_v2 DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reliability_band_v2 TEXT,
    ADD COLUMN IF NOT EXISTS average_execution_time DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS average_confidence DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS retries INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS rollbacks INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS escalations INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS stops INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tool_reliability DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS timeout_rate DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS workflow_results JSONB DEFAULT '[]'::JSONB;

-- Normalize nullable legacy values before enforcing defaults and constraints.
UPDATE public.chats
SET title = COALESCE(title, 'New chat'),
    created_at = COALESCE(created_at, NOW()),
    updated_at = COALESCE(updated_at, created_at, NOW()),
    metadata = COALESCE(metadata, '{}'::JSONB);

UPDATE public.messages
SET role = COALESCE(role, 'system'),
    content = COALESCE(content, ''),
    created_at = COALESCE(created_at, NOW()),
    metadata = COALESCE(metadata, '{}'::JSONB);

UPDATE public.benchmark_runs
SET model = COALESCE(model, 'unknown'),
    environment = COALESCE(environment, 'real_world'),
    total_workflows = COALESCE(total_workflows, 0),
    successful = COALESCE(successful, 0),
    failed = COALESCE(failed, 0),
    success_rate = COALESCE(success_rate, 0),
    failure_rate = COALESCE(failure_rate, 0),
    reliability_score_v2 = COALESCE(reliability_score_v2, 0),
    average_execution_time = COALESCE(average_execution_time, 0),
    average_confidence = COALESCE(average_confidence, 0),
    retries = COALESCE(retries, 0),
    rollbacks = COALESCE(rollbacks, 0),
    escalations = COALESCE(escalations, 0),
    stops = COALESCE(stops, 0),
    tool_reliability = COALESCE(tool_reliability, 0),
    timeout_rate = COALESCE(timeout_rate, 0),
    created_at = COALESCE(created_at, NOW()),
    metadata = COALESCE(metadata, '{}'::JSONB),
    workflow_results = COALESCE(workflow_results, '[]'::JSONB);

ALTER TABLE public.chats
    ALTER COLUMN title SET DEFAULT 'New chat',
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN updated_at SET DEFAULT NOW(),
    ALTER COLUMN metadata SET DEFAULT '{}'::JSONB;

ALTER TABLE public.messages
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN metadata SET DEFAULT '{}'::JSONB;

ALTER TABLE public.benchmark_runs
    ALTER COLUMN environment SET DEFAULT 'real_world',
    ALTER COLUMN total_workflows SET DEFAULT 0,
    ALTER COLUMN successful SET DEFAULT 0,
    ALTER COLUMN failed SET DEFAULT 0,
    ALTER COLUMN success_rate SET DEFAULT 0,
    ALTER COLUMN failure_rate SET DEFAULT 0,
    ALTER COLUMN reliability_score_v2 SET DEFAULT 0,
    ALTER COLUMN average_execution_time SET DEFAULT 0,
    ALTER COLUMN average_confidence SET DEFAULT 0,
    ALTER COLUMN retries SET DEFAULT 0,
    ALTER COLUMN rollbacks SET DEFAULT 0,
    ALTER COLUMN escalations SET DEFAULT 0,
    ALTER COLUMN stops SET DEFAULT 0,
    ALTER COLUMN tool_reliability SET DEFAULT 0,
    ALTER COLUMN timeout_rate SET DEFAULT 0,
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN metadata SET DEFAULT '{}'::JSONB,
    ALTER COLUMN workflow_results SET DEFAULT '[]'::JSONB;

ALTER TABLE public.chats
    ALTER COLUMN title SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET NOT NULL,
    ALTER COLUMN metadata SET NOT NULL;

ALTER TABLE public.messages
    ALTER COLUMN role SET NOT NULL,
    ALTER COLUMN content SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN metadata SET NOT NULL;

ALTER TABLE public.benchmark_runs
    ALTER COLUMN model SET NOT NULL,
    ALTER COLUMN environment SET NOT NULL,
    ALTER COLUMN total_workflows SET NOT NULL,
    ALTER COLUMN successful SET NOT NULL,
    ALTER COLUMN failed SET NOT NULL,
    ALTER COLUMN success_rate SET NOT NULL,
    ALTER COLUMN failure_rate SET NOT NULL,
    ALTER COLUMN reliability_score_v2 SET NOT NULL,
    ALTER COLUMN average_execution_time SET NOT NULL,
    ALTER COLUMN average_confidence SET NOT NULL,
    ALTER COLUMN retries SET NOT NULL,
    ALTER COLUMN rollbacks SET NOT NULL,
    ALTER COLUMN escalations SET NOT NULL,
    ALTER COLUMN stops SET NOT NULL,
    ALTER COLUMN tool_reliability SET NOT NULL,
    ALTER COLUMN timeout_rate SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN metadata SET NOT NULL,
    ALTER COLUMN workflow_results SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.chats WHERE id IS NULL) THEN
        ALTER TABLE public.chats ALTER COLUMN id SET NOT NULL;
    ELSE
        RAISE WARNING 'chats.id remains nullable because legacy NULL values exist.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM public.chats WHERE user_id IS NULL) THEN
        ALTER TABLE public.chats ALTER COLUMN user_id SET NOT NULL;
    ELSE
        RAISE WARNING 'chats.user_id remains nullable because legacy NULL values exist.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM public.messages WHERE id IS NULL) THEN
        ALTER TABLE public.messages ALTER COLUMN id SET NOT NULL;
    ELSE
        RAISE WARNING 'messages.id remains nullable because legacy NULL values exist.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM public.messages WHERE chat_id IS NULL) THEN
        ALTER TABLE public.messages ALTER COLUMN chat_id SET NOT NULL;
    ELSE
        RAISE WARNING 'messages.chat_id remains nullable because legacy NULL values exist.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM public.messages WHERE user_id IS NULL) THEN
        ALTER TABLE public.messages ALTER COLUMN user_id SET NOT NULL;
    ELSE
        RAISE WARNING 'messages.user_id remains nullable because legacy NULL values exist.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM public.benchmark_runs WHERE run_id IS NULL) THEN
        ALTER TABLE public.benchmark_runs ALTER COLUMN run_id SET NOT NULL;
    ELSE
        RAISE WARNING 'benchmark_runs.run_id remains nullable because legacy NULL values exist.';
    END IF;
END
$$;

-- Add primary keys only when a partial table does not already have one.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.chats'::REGCLASS
          AND contype = 'p'
    ) THEN
        IF EXISTS (SELECT 1 FROM public.chats WHERE id IS NULL)
           OR EXISTS (
               SELECT id FROM public.chats
               GROUP BY id HAVING COUNT(*) > 1
           ) THEN
            RAISE WARNING 'chats primary key was not added because id contains NULL or duplicate values.';
        ELSE
            ALTER TABLE public.chats
                ADD CONSTRAINT chats_pkey PRIMARY KEY (id);
        END IF;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.messages'::REGCLASS
          AND contype = 'p'
    ) THEN
        IF EXISTS (SELECT 1 FROM public.messages WHERE id IS NULL)
           OR EXISTS (
               SELECT id FROM public.messages
               GROUP BY id HAVING COUNT(*) > 1
           ) THEN
            RAISE WARNING 'messages primary key was not added because id contains NULL or duplicate values.';
        ELSE
            ALTER TABLE public.messages
                ADD CONSTRAINT messages_pkey PRIMARY KEY (id);
        END IF;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.benchmark_runs'::REGCLASS
          AND contype = 'p'
    ) THEN
        IF EXISTS (SELECT 1 FROM public.benchmark_runs WHERE run_id IS NULL)
           OR EXISTS (
               SELECT run_id FROM public.benchmark_runs
               GROUP BY run_id HAVING COUNT(*) > 1
           ) THEN
            RAISE WARNING 'benchmark_runs primary key was not added because run_id contains NULL or duplicate values.';
        ELSE
            ALTER TABLE public.benchmark_runs
                ADD CONSTRAINT benchmark_runs_pkey PRIMARY KEY (run_id);
        END IF;
    END IF;
END
$$;

-- Ensure application identifier columns are unique even when a legacy table
-- already has a different primary key.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_index AS index_record
        JOIN pg_attribute AS column_record
          ON column_record.attrelid = index_record.indrelid
         AND column_record.attnum = ANY(index_record.indkey)
        WHERE index_record.indrelid = 'public.chats'::REGCLASS
          AND index_record.indisunique
          AND index_record.indpred IS NULL
          AND index_record.indnatts = 1
          AND column_record.attname = 'id'
    ) THEN
        IF EXISTS (
            SELECT id
            FROM public.chats
            WHERE id IS NOT NULL
            GROUP BY id
            HAVING COUNT(*) > 1
        ) THEN
            RAISE WARNING 'chats.id unique index was not added because duplicate values exist.';
        ELSE
            CREATE UNIQUE INDEX IF NOT EXISTS uq_chats_id
                ON public.chats(id);
        END IF;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_index AS index_record
        JOIN pg_attribute AS column_record
          ON column_record.attrelid = index_record.indrelid
         AND column_record.attnum = ANY(index_record.indkey)
        WHERE index_record.indrelid = 'public.messages'::REGCLASS
          AND index_record.indisunique
          AND index_record.indpred IS NULL
          AND index_record.indnatts = 1
          AND column_record.attname = 'id'
    ) THEN
        IF EXISTS (
            SELECT id
            FROM public.messages
            WHERE id IS NOT NULL
            GROUP BY id
            HAVING COUNT(*) > 1
        ) THEN
            RAISE WARNING 'messages.id unique index was not added because duplicate values exist.';
        ELSE
            CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_id
                ON public.messages(id);
        END IF;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_index AS index_record
        JOIN pg_attribute AS column_record
          ON column_record.attrelid = index_record.indrelid
         AND column_record.attnum = ANY(index_record.indkey)
        WHERE index_record.indrelid = 'public.benchmark_runs'::REGCLASS
          AND index_record.indisunique
          AND index_record.indpred IS NULL
          AND index_record.indnatts = 1
          AND column_record.attname = 'run_id'
    ) THEN
        IF EXISTS (
            SELECT run_id
            FROM public.benchmark_runs
            WHERE run_id IS NOT NULL
            GROUP BY run_id
            HAVING COUNT(*) > 1
        ) THEN
            RAISE WARNING 'benchmark_runs.run_id unique index was not added because duplicate values exist.';
        ELSE
            CREATE UNIQUE INDEX IF NOT EXISTS uq_benchmark_runs_run_id
                ON public.benchmark_runs(run_id);
        END IF;
    END IF;
END
$$;

-- Add constraints missing from partially-created message tables.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.messages'::REGCLASS
          AND conname = 'messages_chat_id_fkey'
    ) THEN
        IF EXISTS (
            SELECT 1
            FROM pg_index AS index_record
            JOIN pg_attribute AS column_record
              ON column_record.attrelid = index_record.indrelid
             AND column_record.attnum = ANY(index_record.indkey)
            WHERE index_record.indrelid = 'public.chats'::REGCLASS
              AND index_record.indisunique
              AND index_record.indpred IS NULL
              AND index_record.indnatts = 1
              AND column_record.attname = 'id'
        ) THEN
            ALTER TABLE public.messages
                ADD CONSTRAINT messages_chat_id_fkey
                FOREIGN KEY (chat_id)
                REFERENCES public.chats(id)
                ON DELETE CASCADE
                NOT VALID;
        ELSE
            RAISE WARNING 'messages_chat_id_fkey was not added because chats.id is not unique.';
        END IF;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.messages'::REGCLASS
          AND conname = 'messages_role_check'
    ) THEN
        ALTER TABLE public.messages
            ADD CONSTRAINT messages_role_check
            CHECK (role IN ('user', 'assistant', 'system', 'tool'))
            NOT VALID;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_chats_user_updated
    ON public.chats(user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_profiles_email
    ON public.user_profiles(email);

CREATE INDEX IF NOT EXISTS idx_chats_project_updated
    ON public.chats(project_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_messages_chat_created
    ON public.messages(chat_id, created_at);

CREATE INDEX IF NOT EXISTS idx_messages_user_created
    ON public.messages(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_benchmark_runs_created
    ON public.benchmark_runs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_benchmark_runs_user_created
    ON public.benchmark_runs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_benchmark_runs_user_model
    ON public.benchmark_runs(user_id, model);

-- Keep chats.updated_at correct for API and direct SQL updates.
CREATE OR REPLACE FUNCTION public.software_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS software_chats_updated_at ON public.chats;
CREATE TRIGGER software_chats_updated_at
BEFORE UPDATE ON public.chats
FOR EACH ROW
EXECUTE FUNCTION public.software_set_updated_at();

DROP TRIGGER IF EXISTS software_user_profiles_updated_at ON public.user_profiles;
CREATE TRIGGER software_user_profiles_updated_at
BEFORE UPDATE ON public.user_profiles
FOR EACH ROW
EXECUTE FUNCTION public.software_set_updated_at();

ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chats ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.benchmark_runs ENABLE ROW LEVEL SECURITY;

-- Clerk owns authentication. Supabase is used only as server-side storage.
-- Store the Clerk user id in every user-owned row and use
-- SUPABASE_SERVICE_ROLE_KEY only from the backend. Do not expose service_role
-- credentials to browsers or SDK clients.
REVOKE ALL ON public.user_profiles FROM anon, authenticated;
REVOKE ALL ON public.chats FROM anon, authenticated;
REVOKE ALL ON public.messages FROM anon, authenticated;
REVOKE ALL ON public.benchmark_runs FROM anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_profiles TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.chats TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.messages TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.benchmark_runs TO service_role;

DROP POLICY IF EXISTS "software_server_user_profiles" ON public.user_profiles;

DROP POLICY IF EXISTS "software_server_chats" ON public.chats;
DROP POLICY IF EXISTS "software_server_messages" ON public.messages;
DROP POLICY IF EXISTS "software_server_benchmark_runs" ON public.benchmark_runs;

COMMIT;

-- Verification 1: this query should return zero rows.
WITH expected_columns(table_name, column_name) AS (
    VALUES
        ('user_profiles', 'id'),
        ('user_profiles', 'clerk_user_id'),
        ('user_profiles', 'email'),
        ('user_profiles', 'created_at'),
        ('user_profiles', 'updated_at'),
        ('user_profiles', 'metadata'),
        ('chats', 'id'),
        ('chats', 'user_id'),
        ('chats', 'project_id'),
        ('chats', 'title'),
        ('chats', 'created_at'),
        ('chats', 'updated_at'),
        ('chats', 'metadata'),
        ('messages', 'id'),
        ('messages', 'chat_id'),
        ('messages', 'user_id'),
        ('messages', 'role'),
        ('messages', 'content'),
        ('messages', 'created_at'),
        ('messages', 'metadata'),
        ('benchmark_runs', 'run_id'),
        ('benchmark_runs', 'user_id'),
        ('benchmark_runs', 'model'),
        ('benchmark_runs', 'provider_url'),
        ('benchmark_runs', 'environment'),
        ('benchmark_runs', 'total_workflows'),
        ('benchmark_runs', 'successful'),
        ('benchmark_runs', 'failed'),
        ('benchmark_runs', 'success_rate'),
        ('benchmark_runs', 'failure_rate'),
        ('benchmark_runs', 'reliability_score_v2'),
        ('benchmark_runs', 'reliability_band_v2'),
        ('benchmark_runs', 'average_execution_time'),
        ('benchmark_runs', 'average_confidence'),
        ('benchmark_runs', 'retries'),
        ('benchmark_runs', 'rollbacks'),
        ('benchmark_runs', 'escalations'),
        ('benchmark_runs', 'stops'),
        ('benchmark_runs', 'tool_reliability'),
        ('benchmark_runs', 'timeout_rate'),
        ('benchmark_runs', 'created_at'),
        ('benchmark_runs', 'metadata'),
        ('benchmark_runs', 'workflow_results')
)
SELECT expected.table_name, expected.column_name
FROM expected_columns AS expected
LEFT JOIN information_schema.columns AS actual
  ON actual.table_schema = 'public'
 AND actual.table_name = expected.table_name
 AND actual.column_name = expected.column_name
WHERE actual.column_name IS NULL
ORDER BY expected.table_name, expected.column_name;

-- Verification 2: review any required columns that remain nullable because of
-- legacy rows. This query should normally return zero rows.
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND is_nullable = 'YES'
  AND (
      (table_name = 'chats'
       AND column_name IN ('id', 'user_id', 'title', 'created_at', 'updated_at', 'metadata'))
      OR
      (table_name = 'user_profiles'
       AND column_name IN ('id', 'clerk_user_id', 'email', 'created_at', 'updated_at', 'metadata'))
      OR
      (table_name = 'messages'
       AND column_name IN ('id', 'chat_id', 'user_id', 'role', 'content', 'created_at', 'metadata'))
      OR
      (table_name = 'benchmark_runs'
       AND column_name IN (
           'run_id', 'model', 'environment', 'total_workflows', 'successful',
           'failed', 'success_rate', 'failure_rate', 'reliability_score_v2',
           'average_execution_time', 'average_confidence', 'retries',
           'rollbacks', 'escalations', 'stops', 'tool_reliability',
           'timeout_rate', 'created_at', 'metadata', 'workflow_results'
       ))
  )
ORDER BY table_name, column_name;

-- Verification 3: Clerk profile storage exists.
SELECT TO_REGCLASS('public.user_profiles') AS software_user_profiles;

-- Verification 4: confirm RLS and policies.
SELECT namespace.nspname AS schema_name,
       relation.relname AS table_name,
       relation.relrowsecurity AS rls_enabled
FROM pg_class AS relation
JOIN pg_namespace AS namespace
  ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relname IN ('user_profiles', 'chats', 'messages', 'benchmark_runs')
ORDER BY relation.relname;

SELECT schemaname, tablename, policyname, roles, cmd
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('user_profiles', 'chats', 'messages', 'benchmark_runs')
ORDER BY tablename, policyname;

-- Verification 5: confirm the updated_at trigger.
SELECT event_object_schema,
       event_object_table,
       trigger_name,
       action_timing,
       event_manipulation
FROM information_schema.triggers
WHERE event_object_schema = 'public'
  AND trigger_name IN ('software_chats_updated_at', 'software_user_profiles_updated_at');
