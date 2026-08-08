-- Software / Matrixs durable execution control plane.
-- Run after supabase_schema.sql in the Supabase SQL editor.
-- Idempotent DDL; PostgreSQL functions provide the transactional boundary used
-- by the backend. Clerk remains the identity provider and service_role remains
-- server-only. No browser or SDK credential may call these tables/functions.

BEGIN;

CREATE TABLE IF NOT EXISTS public.execution_control_states (
    user_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    parent_step_id TEXT,
    state TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    risk_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    cancellation_epoch BIGINT NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    fencing_token BIGINT NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, workflow_id, step_id),
    CONSTRAINT execution_control_risk_range CHECK (risk_score BETWEEN 0 AND 1)
);

CREATE TABLE IF NOT EXISTS public.execution_ledger (
    sequence BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    parent_step_id TEXT,
    before_state TEXT,
    after_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    risk_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    evidence_ids JSONB NOT NULL DEFAULT '[]'::JSONB,
    actor TEXT NOT NULL,
    lease_token TEXT,
    fencing_token BIGINT,
    idempotency_key TEXT,
    cancellation_epoch BIGINT NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.execution_outbox (
    event_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'leased', 'delivered', 'dead_letter')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.execution_idempotency_keys (
    user_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    response JSONB,
    fencing_token BIGINT NOT NULL,
    cancellation_epoch BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS public.execution_action_receipts (
    receipt_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_action_id TEXT,
    request_fingerprint TEXT NOT NULL,
    result_fingerprint TEXT NOT NULL,
    observed_result JSONB NOT NULL DEFAULT '{}'::JSONB,
    fencing_token BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.execution_worker_heartbeats (
    worker_id TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    active_leases INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_execution_ledger_workflow
    ON public.execution_ledger(user_id, workflow_id, step_id, sequence);
CREATE INDEX IF NOT EXISTS idx_execution_outbox_claim
    ON public.execution_outbox(status, available_at, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_execution_receipts_workflow
    ON public.execution_action_receipts(user_id, workflow_id, step_id, created_at);
CREATE INDEX IF NOT EXISTS idx_execution_leases_expiry
    ON public.execution_control_states(lease_expires_at)
    WHERE lease_token IS NOT NULL;

CREATE OR REPLACE FUNCTION public.software_execution_ledger_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    RAISE EXCEPTION 'execution ledger is append-only';
END;
$$;

DROP TRIGGER IF EXISTS software_execution_ledger_no_mutation ON public.execution_ledger;
CREATE TRIGGER software_execution_ledger_no_mutation
BEFORE UPDATE OR DELETE ON public.execution_ledger
FOR EACH ROW EXECUTE FUNCTION public.software_execution_ledger_immutable();

CREATE OR REPLACE FUNCTION public.software_execution_transition_internal(
    p_user_id TEXT,
    p_workflow_id TEXT,
    p_step_id TEXT,
    p_after_state TEXT,
    p_reason TEXT,
    p_actor TEXT,
    p_evidence_ids JSONB DEFAULT '[]'::JSONB,
    p_idempotency_key TEXT DEFAULT NULL,
    p_payload JSONB DEFAULT '{}'::JSONB
)
RETURNS public.execution_control_states
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_before TEXT;
    v_row public.execution_control_states%ROWTYPE;
    v_allowed BOOLEAN := FALSE;
    v_ledger_id TEXT := 'led_' || REPLACE(gen_random_uuid()::TEXT, '-', '');
BEGIN
    SELECT * INTO v_row
    FROM public.execution_control_states
    WHERE user_id = p_user_id
      AND workflow_id = p_workflow_id
      AND step_id = p_step_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'execution control state was not found';
    END IF;

    v_before := v_row.state;
    v_allowed := CASE v_before
        WHEN 'RECEIVED' THEN p_after_state IN ('PLANNED', 'CANCELLED')
        WHEN 'PLANNED' THEN p_after_state IN ('EVIDENCE_REQUIRED', 'BLOCK', 'CANCELLED')
        WHEN 'EVIDENCE_REQUIRED' THEN p_after_state IN ('VERIFYING', 'BLOCK', 'CANCELLED')
        WHEN 'VERIFYING' THEN p_after_state IN ('ALLOW', 'RETRY', 'REVIEW', 'BLOCK', 'CANCELLED')
        WHEN 'RETRY' THEN p_after_state IN ('PLANNED', 'BLOCK', 'CANCELLED')
        WHEN 'ALLOW' THEN p_after_state IN ('AUTHORIZED', 'CANCELLED')
        WHEN 'REVIEW' THEN p_after_state IN ('AUTHORIZED', 'BLOCK', 'CANCELLED')
        WHEN 'AUTHORIZED' THEN p_after_state IN ('EXECUTION_LEASED', 'CANCELLED')
        WHEN 'EXECUTION_LEASED' THEN p_after_state IN ('EXECUTING', 'AUTHORIZED', 'CANCELLED', 'ESCALATED')
        WHEN 'EXECUTING' THEN p_after_state IN ('POST_VERIFYING', 'COMPENSATING', 'ESCALATED', 'CANCELLED')
        WHEN 'POST_VERIFYING' THEN p_after_state IN ('VERIFIED', 'COMPENSATING', 'ESCALATED', 'CANCELLED')
        WHEN 'VERIFIED' THEN p_after_state IN ('COMPLETED', 'ESCALATED')
        WHEN 'COMPENSATING' THEN p_after_state IN ('COMPLETED', 'ESCALATED')
        ELSE FALSE
    END;

    IF NOT v_allowed THEN
        RAISE EXCEPTION 'execution cannot transition from % to %', v_before, p_after_state;
    END IF;

    UPDATE public.execution_control_states
    SET state = p_after_state, updated_at = NOW()
    WHERE user_id = p_user_id
      AND workflow_id = p_workflow_id
      AND step_id = p_step_id
    RETURNING * INTO v_row;

    INSERT INTO public.execution_ledger (
        event_id, user_id, workflow_id, step_id, parent_step_id,
        before_state, after_state, reason, policy_version, risk_score,
        evidence_ids, actor, lease_token, fencing_token, idempotency_key,
        cancellation_epoch, payload
    ) VALUES (
        v_ledger_id, v_row.user_id, v_row.workflow_id, v_row.step_id,
        v_row.parent_step_id, v_before, p_after_state, p_reason,
        v_row.policy_version, v_row.risk_score, COALESCE(p_evidence_ids, '[]'::JSONB),
        p_actor, v_row.lease_token, v_row.fencing_token, p_idempotency_key,
        v_row.cancellation_epoch, COALESCE(p_payload, '{}'::JSONB)
    );

    INSERT INTO public.execution_outbox (
        event_id, user_id, workflow_id, step_id, event_type, payload
    ) VALUES (
        'out_' || REPLACE(gen_random_uuid()::TEXT, '-', ''),
        v_row.user_id, v_row.workflow_id, v_row.step_id,
        'execution.state_changed',
        JSONB_BUILD_OBJECT(
            'ledger_event_id', v_ledger_id,
            'before', v_before,
            'after', p_after_state,
            'reason', p_reason,
            'cancellation_epoch', v_row.cancellation_epoch
        ) || COALESCE(p_payload, '{}'::JSONB)
    );
    RETURN v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.software_execution_start(
    p_user_id TEXT,
    p_workflow_id TEXT,
    p_step_id TEXT,
    p_parent_step_id TEXT DEFAULT NULL,
    p_policy_version TEXT DEFAULT 'execution-control-v1',
    p_risk_score DOUBLE PRECISION DEFAULT 0,
    p_metadata JSONB DEFAULT '{}'::JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_row public.execution_control_states%ROWTYPE;
    v_ledger_id TEXT := 'led_' || REPLACE(gen_random_uuid()::TEXT, '-', '');
BEGIN
    INSERT INTO public.execution_control_states (
        user_id, workflow_id, step_id, parent_step_id, state,
        policy_version, risk_score, metadata
    ) VALUES (
        p_user_id, p_workflow_id, p_step_id, p_parent_step_id, 'RECEIVED',
        p_policy_version, GREATEST(0, LEAST(1, p_risk_score)), COALESCE(p_metadata, '{}'::JSONB)
    )
    ON CONFLICT (user_id, workflow_id, step_id) DO NOTHING
    RETURNING * INTO v_row;

    IF NOT FOUND THEN
        SELECT * INTO v_row FROM public.execution_control_states
        WHERE user_id = p_user_id AND workflow_id = p_workflow_id AND step_id = p_step_id;
        RETURN TO_JSONB(v_row);
    END IF;

    INSERT INTO public.execution_ledger (
        event_id, user_id, workflow_id, step_id, parent_step_id,
        before_state, after_state, reason, policy_version, risk_score,
        actor, cancellation_epoch
    ) VALUES (
        v_ledger_id, p_user_id, p_workflow_id, p_step_id, p_parent_step_id,
        NULL, 'RECEIVED', 'Authenticated execution request received.',
        p_policy_version, v_row.risk_score, 'api', 0
    );
    INSERT INTO public.execution_outbox (
        event_id, user_id, workflow_id, step_id, event_type, payload
    ) VALUES (
        'out_' || REPLACE(gen_random_uuid()::TEXT, '-', ''),
        p_user_id, p_workflow_id, p_step_id, 'execution.state_changed',
        JSONB_BUILD_OBJECT('ledger_event_id', v_ledger_id, 'before', NULL, 'after', 'RECEIVED')
    );
    v_row := public.software_execution_transition_internal(
        p_user_id, p_workflow_id, p_step_id, 'PLANNED',
        'Execution plan created.', 'planner'
    );
    RETURN TO_JSONB(v_row);
END;
$$;

CREATE OR REPLACE FUNCTION public.software_execution_verify(
    p_user_id TEXT,
    p_workflow_id TEXT,
    p_step_id TEXT,
    p_decision TEXT,
    p_reason TEXT,
    p_policy_version TEXT,
    p_risk_score DOUBLE PRECISION,
    p_evidence_ids JSONB DEFAULT '[]'::JSONB,
    p_auto_authorize BOOLEAN DEFAULT FALSE
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_row public.execution_control_states%ROWTYPE;
BEGIN
    IF p_decision NOT IN ('ALLOW', 'RETRY', 'REVIEW', 'BLOCK') THEN
        RAISE EXCEPTION 'unsupported verification decision';
    END IF;
    SELECT * INTO v_row FROM public.execution_control_states
    WHERE user_id = p_user_id AND workflow_id = p_workflow_id AND step_id = p_step_id
    FOR UPDATE;
    IF v_row.state = 'RETRY' THEN
        v_row := public.software_execution_transition_internal(
            p_user_id, p_workflow_id, p_step_id, 'PLANNED',
            'Verification retry started.', 'verification-engine'
        );
    END IF;
    IF v_row.state <> 'PLANNED' THEN
        IF v_row.state = p_decision OR (v_row.state = 'AUTHORIZED' AND p_decision = 'ALLOW') THEN
            RETURN TO_JSONB(v_row);
        END IF;
        RAISE EXCEPTION 'verification requires PLANNED state, not %', v_row.state;
    END IF;
    UPDATE public.execution_control_states
    SET policy_version = p_policy_version,
        risk_score = GREATEST(0, LEAST(1, p_risk_score)),
        updated_at = NOW()
    WHERE user_id = p_user_id AND workflow_id = p_workflow_id AND step_id = p_step_id;
    v_row := public.software_execution_transition_internal(
        p_user_id, p_workflow_id, p_step_id, 'EVIDENCE_REQUIRED',
        'Verification evidence contract selected.', 'verification-engine', p_evidence_ids
    );
    v_row := public.software_execution_transition_internal(
        p_user_id, p_workflow_id, p_step_id, 'VERIFYING',
        'Independent verification started.', 'verification-engine', p_evidence_ids
    );
    v_row := public.software_execution_transition_internal(
        p_user_id, p_workflow_id, p_step_id, p_decision,
        p_reason, 'verification-engine', p_evidence_ids
    );
    IF p_decision = 'ALLOW' AND p_auto_authorize THEN
        v_row := public.software_execution_transition_internal(
            p_user_id, p_workflow_id, p_step_id, 'AUTHORIZED',
            'Verified low-risk action authorized by policy.', 'policy-engine', p_evidence_ids
        );
    END IF;
    RETURN TO_JSONB(v_row);
END;
$$;

CREATE OR REPLACE FUNCTION public.software_execution_authorize(
    p_user_id TEXT,
    p_workflow_id TEXT,
    p_step_id TEXT,
    p_actor TEXT,
    p_reason TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE v_row public.execution_control_states%ROWTYPE;
BEGIN
    SELECT * INTO v_row FROM public.execution_control_states
    WHERE user_id = p_user_id AND workflow_id = p_workflow_id AND step_id = p_step_id
    FOR UPDATE;
    IF v_row.state = 'AUTHORIZED' THEN RETURN TO_JSONB(v_row); END IF;
    v_row := public.software_execution_transition_internal(
        p_user_id, p_workflow_id, p_step_id, 'AUTHORIZED', p_reason, p_actor
    );
    RETURN TO_JSONB(v_row);
END;
$$;

CREATE OR REPLACE FUNCTION public.software_execution_cancel(
    p_user_id TEXT,
    p_workflow_id TEXT,
    p_step_id TEXT,
    p_actor TEXT,
    p_reason TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE v_row public.execution_control_states%ROWTYPE;
BEGIN
    SELECT * INTO v_row FROM public.execution_control_states
    WHERE user_id = p_user_id AND workflow_id = p_workflow_id AND step_id = p_step_id
    FOR UPDATE;
    IF v_row.state = 'CANCELLED' THEN RETURN TO_JSONB(v_row); END IF;
    IF v_row.state IN ('COMPLETED', 'BLOCK', 'ESCALATED') THEN
        RAISE EXCEPTION 'a % execution cannot be cancelled', v_row.state;
    END IF;
    UPDATE public.execution_control_states
    SET cancellation_epoch = cancellation_epoch + 1,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        updated_at = NOW()
    WHERE user_id = p_user_id AND workflow_id = p_workflow_id AND step_id = p_step_id;
    v_row := public.software_execution_transition_internal(
        p_user_id, p_workflow_id, p_step_id, 'CANCELLED', p_reason, p_actor
    );
    RETURN TO_JSONB(v_row);
END;
$$;

CREATE OR REPLACE FUNCTION public.software_execution_begin(
    p_user_id TEXT,
    p_workflow_id TEXT,
    p_step_id TEXT,
    p_idempotency_key TEXT,
    p_request_fingerprint TEXT,
    p_owner TEXT,
    p_lease_seconds INTEGER DEFAULT 120
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_row public.execution_control_states%ROWTYPE;
    v_idem public.execution_idempotency_keys%ROWTYPE;
    v_token TEXT := 'lease_' || REPLACE(gen_random_uuid()::TEXT, '-', '');
    v_expires TIMESTAMPTZ := NOW() + MAKE_INTERVAL(secs => GREATEST(5, p_lease_seconds));
BEGIN
    SELECT * INTO v_idem FROM public.execution_idempotency_keys
    WHERE user_id = p_user_id AND idempotency_key = p_idempotency_key
    FOR UPDATE;
    IF FOUND THEN
        IF v_idem.request_fingerprint <> p_request_fingerprint THEN
            RAISE EXCEPTION 'idempotency key was used for a different action';
        END IF;
        IF v_idem.status = 'completed' THEN
            RETURN JSONB_BUILD_OBJECT(
                'workflow_id', p_workflow_id, 'step_id', p_step_id,
                'owner', p_owner, 'token', 'replay',
                'fencing_token', v_idem.fencing_token,
                'cancellation_epoch', v_idem.cancellation_epoch,
                'expires_at', NOW(), 'idempotency_key', p_idempotency_key,
                'replay', TRUE, 'response', v_idem.response
            );
        END IF;
        RAISE EXCEPTION 'action is already executing';
    END IF;

    SELECT * INTO v_row FROM public.execution_control_states
    WHERE user_id = p_user_id AND workflow_id = p_workflow_id AND step_id = p_step_id
    FOR UPDATE;
    IF v_row.state = 'CANCELLED' OR v_row.cancellation_epoch > 0 THEN
        RAISE EXCEPTION 'execution was cancelled';
    END IF;
    IF v_row.lease_token IS NOT NULL AND v_row.lease_expires_at > NOW() THEN
        RAISE EXCEPTION 'another worker owns the execution lease';
    END IF;
    IF v_row.state <> 'AUTHORIZED' THEN
        RAISE EXCEPTION 'execution requires AUTHORIZED state, not %', v_row.state;
    END IF;

    UPDATE public.execution_control_states
    SET lease_owner = p_owner, lease_token = v_token,
        lease_expires_at = v_expires, fencing_token = fencing_token + 1,
        updated_at = NOW()
    WHERE user_id = p_user_id AND workflow_id = p_workflow_id AND step_id = p_step_id
    RETURNING * INTO v_row;

    INSERT INTO public.execution_idempotency_keys (
        user_id, idempotency_key, workflow_id, step_id,
        request_fingerprint, status, fencing_token, cancellation_epoch
    ) VALUES (
        p_user_id, p_idempotency_key, p_workflow_id, p_step_id,
        p_request_fingerprint, 'pending', v_row.fencing_token, v_row.cancellation_epoch
    );
    v_row := public.software_execution_transition_internal(
        p_user_id, p_workflow_id, p_step_id, 'EXECUTION_LEASED',
        'Durable execution lease acquired.', p_owner, '[]'::JSONB,
        p_idempotency_key, JSONB_BUILD_OBJECT('fencing_token', v_row.fencing_token)
    );
    v_row := public.software_execution_transition_internal(
        p_user_id, p_workflow_id, p_step_id, 'EXECUTING',
        'Authorized side effect started.', p_owner, '[]'::JSONB,
        p_idempotency_key, JSONB_BUILD_OBJECT('fencing_token', v_row.fencing_token)
    );
    RETURN JSONB_BUILD_OBJECT(
        'workflow_id', p_workflow_id, 'step_id', p_step_id,
        'owner', p_owner, 'token', v_token,
        'fencing_token', v_row.fencing_token,
        'cancellation_epoch', v_row.cancellation_epoch,
        'expires_at', v_expires, 'idempotency_key', p_idempotency_key,
        'replay', FALSE, 'response', NULL
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.software_execution_finalize(
    p_user_id TEXT,
    p_workflow_id TEXT,
    p_step_id TEXT,
    p_owner TEXT,
    p_lease_token TEXT,
    p_fencing_token BIGINT,
    p_cancellation_epoch BIGINT,
    p_idempotency_key TEXT,
    p_result JSONB,
    p_result_fingerprint TEXT,
    p_verified BOOLEAN,
    p_provider TEXT,
    p_provider_action_id TEXT DEFAULT NULL,
    p_evidence_ids JSONB DEFAULT '[]'::JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_row public.execution_control_states%ROWTYPE;
    v_request_fingerprint TEXT;
    v_receipt_id TEXT := 'rcpt_' || REPLACE(gen_random_uuid()::TEXT, '-', '');
BEGIN
    SELECT * INTO v_row FROM public.execution_control_states
    WHERE user_id = p_user_id AND workflow_id = p_workflow_id AND step_id = p_step_id
    FOR UPDATE;
    IF v_row.state = 'CANCELLED' OR v_row.cancellation_epoch <> p_cancellation_epoch THEN
        RAISE EXCEPTION 'cancellation superseded this execution attempt';
    END IF;
    IF v_row.lease_owner <> p_owner OR v_row.lease_token <> p_lease_token
       OR v_row.fencing_token <> p_fencing_token THEN
        RAISE EXCEPTION 'stale execution lease or fencing token';
    END IF;
    v_row := public.software_execution_transition_internal(
        p_user_id, p_workflow_id, p_step_id, 'POST_VERIFYING',
        'External action finished; post-condition verification started.',
        p_owner, p_evidence_ids, p_idempotency_key
    );
    v_row := public.software_execution_transition_internal(
        p_user_id, p_workflow_id, p_step_id,
        CASE WHEN p_verified THEN 'VERIFIED' ELSE 'ESCALATED' END,
        CASE WHEN p_verified
            THEN 'Observed result satisfied the post-condition contract.'
            ELSE 'Observed result did not satisfy the post-condition contract.' END,
        'post-condition-verifier', p_evidence_ids, p_idempotency_key
    );
    IF p_verified THEN
        v_row := public.software_execution_transition_internal(
            p_user_id, p_workflow_id, p_step_id, 'COMPLETED',
            'Execution and post-condition verification completed.',
            'execution-control-plane', p_evidence_ids, p_idempotency_key
        );
    END IF;
    SELECT request_fingerprint INTO v_request_fingerprint
    FROM public.execution_idempotency_keys
    WHERE user_id = p_user_id AND idempotency_key = p_idempotency_key;
    INSERT INTO public.execution_action_receipts (
        receipt_id, user_id, workflow_id, step_id, idempotency_key,
        provider, provider_action_id, request_fingerprint, result_fingerprint,
        observed_result, fencing_token
    ) VALUES (
        v_receipt_id, p_user_id, p_workflow_id, p_step_id, p_idempotency_key,
        p_provider, p_provider_action_id, v_request_fingerprint,
        p_result_fingerprint, p_result, p_fencing_token
    );
    UPDATE public.execution_idempotency_keys
    SET status = CASE WHEN p_verified THEN 'completed' ELSE 'failed' END,
        response = p_result, updated_at = NOW()
    WHERE user_id = p_user_id AND idempotency_key = p_idempotency_key;
    UPDATE public.execution_control_states
    SET lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        updated_at = NOW()
    WHERE user_id = p_user_id AND workflow_id = p_workflow_id AND step_id = p_step_id;
    RETURN JSONB_BUILD_OBJECT('state', v_row.state, 'receipt_id', v_receipt_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.software_execution_fail(
    p_user_id TEXT,
    p_workflow_id TEXT,
    p_step_id TEXT,
    p_owner TEXT,
    p_lease_token TEXT,
    p_fencing_token BIGINT,
    p_cancellation_epoch BIGINT,
    p_idempotency_key TEXT,
    p_error TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE v_row public.execution_control_states%ROWTYPE;
BEGIN
    SELECT * INTO v_row FROM public.execution_control_states
    WHERE user_id = p_user_id AND workflow_id = p_workflow_id AND step_id = p_step_id
    FOR UPDATE;
    IF v_row.state = 'CANCELLED' OR v_row.cancellation_epoch <> p_cancellation_epoch THEN
        RAISE EXCEPTION 'cancellation superseded this execution attempt';
    END IF;
    IF v_row.lease_owner <> p_owner OR v_row.lease_token <> p_lease_token
       OR v_row.fencing_token <> p_fencing_token THEN
        RAISE EXCEPTION 'stale execution lease or fencing token';
    END IF;
    IF v_row.state IN ('EXECUTION_LEASED', 'EXECUTING', 'POST_VERIFYING') THEN
        v_row := public.software_execution_transition_internal(
            p_user_id, p_workflow_id, p_step_id, 'ESCALATED',
            'Execution failed and requires operator review.', p_owner,
            '[]'::JSONB, p_idempotency_key,
            JSONB_BUILD_OBJECT('error', LEFT(p_error, 1000))
        );
    END IF;
    UPDATE public.execution_idempotency_keys
    SET status = 'failed', response = JSONB_BUILD_OBJECT('ok', FALSE, 'error', LEFT(p_error, 1000)),
        updated_at = NOW()
    WHERE user_id = p_user_id AND idempotency_key = p_idempotency_key;
    UPDATE public.execution_control_states
    SET lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        updated_at = NOW()
    WHERE user_id = p_user_id AND workflow_id = p_workflow_id AND step_id = p_step_id;
    RETURN JSONB_BUILD_OBJECT('state', v_row.state);
END;
$$;

CREATE OR REPLACE FUNCTION public.software_execution_snapshot(
    p_user_id TEXT,
    p_workflow_id TEXT,
    p_step_id TEXT
)
RETURNS JSONB
LANGUAGE sql
SECURITY INVOKER
SET search_path = public
AS $$
    SELECT JSONB_BUILD_OBJECT(
        'backend', 'supabase',
        'state', TO_JSONB(state_row),
        'ledger', COALESCE((
            SELECT JSONB_AGG(TO_JSONB(ledger_row) ORDER BY ledger_row.sequence)
            FROM public.execution_ledger AS ledger_row
            WHERE ledger_row.user_id = p_user_id
              AND ledger_row.workflow_id = p_workflow_id
              AND ledger_row.step_id = p_step_id
        ), '[]'::JSONB),
        'receipts', COALESCE((
            SELECT JSONB_AGG(TO_JSONB(receipt_row) ORDER BY receipt_row.created_at)
            FROM public.execution_action_receipts AS receipt_row
            WHERE receipt_row.user_id = p_user_id
              AND receipt_row.workflow_id = p_workflow_id
              AND receipt_row.step_id = p_step_id
        ), '[]'::JSONB)
    )
    FROM public.execution_control_states AS state_row
    WHERE state_row.user_id = p_user_id
      AND state_row.workflow_id = p_workflow_id
      AND state_row.step_id = p_step_id;
$$;

CREATE OR REPLACE FUNCTION public.software_execution_worker_heartbeat(
    p_worker_id TEXT,
    p_instance_id TEXT,
    p_active_leases INTEGER DEFAULT 0,
    p_metadata JSONB DEFAULT '{}'::JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.execution_worker_heartbeats (
        worker_id, instance_id, active_leases, metadata
    ) VALUES (p_worker_id, p_instance_id, GREATEST(0, p_active_leases), p_metadata)
    ON CONFLICT (worker_id) DO UPDATE SET
        instance_id = EXCLUDED.instance_id,
        active_leases = EXCLUDED.active_leases,
        metadata = EXCLUDED.metadata,
        heartbeat_at = NOW();
    RETURN JSONB_BUILD_OBJECT('ok', TRUE, 'worker_id', p_worker_id, 'heartbeat_at', NOW());
END;
$$;

CREATE OR REPLACE FUNCTION public.software_execution_claim_outbox(
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 20,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_token TEXT := 'joblease_' || REPLACE(gen_random_uuid()::TEXT, '-', '');
    v_result JSONB;
BEGIN
    WITH candidates AS (
        SELECT event_id
        FROM public.execution_outbox
        WHERE (status = 'pending' AND available_at <= NOW())
           OR (status = 'leased' AND lease_expires_at < NOW())
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT GREATEST(1, LEAST(200, p_limit))
    ), claimed AS (
        UPDATE public.execution_outbox AS jobs
        SET status = 'leased',
            attempts = jobs.attempts + 1,
            lease_owner = p_worker_id,
            lease_token = v_token,
            lease_expires_at = NOW() + MAKE_INTERVAL(secs => GREATEST(5, p_lease_seconds)),
            updated_at = NOW()
        FROM candidates
        WHERE jobs.event_id = candidates.event_id
        RETURNING jobs.*
    )
    SELECT COALESCE(JSONB_AGG(TO_JSONB(claimed) ORDER BY claimed.created_at), '[]'::JSONB)
    INTO v_result
    FROM claimed;
    RETURN v_result;
END;
$$;

CREATE OR REPLACE FUNCTION public.software_execution_ack_outbox(
    p_event_id TEXT,
    p_worker_id TEXT,
    p_lease_token TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    UPDATE public.execution_outbox
    SET status = 'delivered', lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, updated_at = NOW()
    WHERE event_id = p_event_id AND status = 'leased'
      AND lease_owner = p_worker_id AND lease_token = p_lease_token;
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION public.software_execution_reject_outbox(
    p_event_id TEXT,
    p_worker_id TEXT,
    p_lease_token TEXT,
    p_error TEXT,
    p_retry_delay_seconds INTEGER DEFAULT 5
)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_job public.execution_outbox%ROWTYPE;
    v_status TEXT;
BEGIN
    SELECT * INTO v_job FROM public.execution_outbox
    WHERE event_id = p_event_id AND status = 'leased'
      AND lease_owner = p_worker_id AND lease_token = p_lease_token
    FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'outbox job lease is no longer valid'; END IF;
    v_status := CASE WHEN v_job.attempts >= v_job.max_attempts
        THEN 'dead_letter' ELSE 'pending' END;
    UPDATE public.execution_outbox
    SET status = v_status,
        available_at = NOW() + MAKE_INTERVAL(secs => GREATEST(0, p_retry_delay_seconds)),
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        last_error = LEFT(p_error, 1000), updated_at = NOW()
    WHERE event_id = p_event_id;
    RETURN v_status;
END;
$$;

CREATE OR REPLACE FUNCTION public.software_execution_stale_workers(
    p_stale_after_seconds INTEGER DEFAULT 90
)
RETURNS JSONB
LANGUAGE sql
SECURITY INVOKER
SET search_path = public
AS $$
    SELECT COALESCE(JSONB_AGG(TO_JSONB(workers) ORDER BY workers.heartbeat_at), '[]'::JSONB)
    FROM public.execution_worker_heartbeats AS workers
    WHERE workers.heartbeat_at < NOW() - MAKE_INTERVAL(secs => GREATEST(1, p_stale_after_seconds));
$$;

ALTER TABLE public.execution_control_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.execution_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.execution_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.execution_idempotency_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.execution_action_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.execution_worker_heartbeats ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.execution_control_states FROM anon, authenticated;
REVOKE ALL ON public.execution_ledger FROM anon, authenticated;
REVOKE ALL ON public.execution_outbox FROM anon, authenticated;
REVOKE ALL ON public.execution_idempotency_keys FROM anon, authenticated;
REVOKE ALL ON public.execution_action_receipts FROM anon, authenticated;
REVOKE ALL ON public.execution_worker_heartbeats FROM anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.execution_control_states TO service_role;
GRANT SELECT, INSERT ON public.execution_ledger TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.execution_outbox TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.execution_idempotency_keys TO service_role;
GRANT SELECT, INSERT ON public.execution_action_receipts TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.execution_worker_heartbeats TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.execution_ledger_sequence_seq TO service_role;

REVOKE ALL ON FUNCTION public.software_execution_transition_internal(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, JSONB) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.software_execution_start(TEXT, TEXT, TEXT, TEXT, TEXT, DOUBLE PRECISION, JSONB) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.software_execution_verify(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, DOUBLE PRECISION, JSONB, BOOLEAN) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.software_execution_authorize(TEXT, TEXT, TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.software_execution_cancel(TEXT, TEXT, TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.software_execution_begin(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.software_execution_finalize(TEXT, TEXT, TEXT, TEXT, TEXT, BIGINT, BIGINT, TEXT, JSONB, TEXT, BOOLEAN, TEXT, TEXT, JSONB) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.software_execution_fail(TEXT, TEXT, TEXT, TEXT, TEXT, BIGINT, BIGINT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.software_execution_snapshot(TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.software_execution_worker_heartbeat(TEXT, TEXT, INTEGER, JSONB) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.software_execution_claim_outbox(TEXT, INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.software_execution_ack_outbox(TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.software_execution_reject_outbox(TEXT, TEXT, TEXT, TEXT, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.software_execution_stale_workers(INTEGER) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.software_execution_transition_internal(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.software_execution_start(TEXT, TEXT, TEXT, TEXT, TEXT, DOUBLE PRECISION, JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.software_execution_verify(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, DOUBLE PRECISION, JSONB, BOOLEAN) TO service_role;
GRANT EXECUTE ON FUNCTION public.software_execution_authorize(TEXT, TEXT, TEXT, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.software_execution_cancel(TEXT, TEXT, TEXT, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.software_execution_begin(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.software_execution_finalize(TEXT, TEXT, TEXT, TEXT, TEXT, BIGINT, BIGINT, TEXT, JSONB, TEXT, BOOLEAN, TEXT, TEXT, JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.software_execution_fail(TEXT, TEXT, TEXT, TEXT, TEXT, BIGINT, BIGINT, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.software_execution_snapshot(TEXT, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.software_execution_worker_heartbeat(TEXT, TEXT, INTEGER, JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.software_execution_claim_outbox(TEXT, INTEGER, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.software_execution_ack_outbox(TEXT, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.software_execution_reject_outbox(TEXT, TEXT, TEXT, TEXT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.software_execution_stale_workers(INTEGER) TO service_role;

COMMIT;

-- Verification: all tables should exist and have RLS enabled.
SELECT c.relname AS table_name, c.relrowsecurity AS rls_enabled
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN (
      'execution_control_states', 'execution_ledger', 'execution_outbox',
      'execution_idempotency_keys', 'execution_action_receipts',
      'execution_worker_heartbeats'
  )
ORDER BY c.relname;
