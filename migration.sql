-- Software Phase 24: SaaS Foundation and Stripe Billing
-- Apply to Software/data/software_reliability.db.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    stripe_customer_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS organization_members (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'developer', 'viewer')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(organization_id, user_id)
);

CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'developer', 'viewer')),
    invited_by_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    accepted_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id TEXT REFERENCES organizations(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    max_projects INTEGER,
    max_api_keys INTEGER,
    monthly_workflow_limit INTEGER,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id TEXT NOT NULL REFERENCES plans(id),
    status TEXT NOT NULL DEFAULT 'active',
    stripe_subscription_id TEXT,
    stripe_price_id TEXT,
    stripe_status TEXT,
    current_period_start TEXT NOT NULL,
    current_period_end TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS usage_records (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    api_key_id TEXT REFERENCES api_keys(id) ON DELETE SET NULL,
    metric_type TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS stripe_invoices (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    stripe_invoice_id TEXT NOT NULL UNIQUE,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    status TEXT,
    amount_paid INTEGER NOT NULL DEFAULT 0,
    amount_due INTEGER NOT NULL DEFAULT 0,
    currency TEXT,
    hosted_invoice_url TEXT,
    invoice_pdf TEXT,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS stripe_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS request_access_requests (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    company TEXT,
    role TEXT,
    use_case TEXT NOT NULL,
    expected_workflows_per_month INTEGER,
    timeline TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS analytics_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    email TEXT,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS recovery_events (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES sdk_workflows(workflow_id) ON DELETE CASCADE,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    api_key_id TEXT REFERENCES api_keys(id) ON DELETE SET NULL,
    failure_category TEXT NOT NULL,
    recovery_action TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    success INTEGER NOT NULL DEFAULT 0,
    recovery_latency_ms INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS recommendations (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'global',
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    category TEXT NOT NULL,
    issue TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    confidence REAL NOT NULL,
    estimated_success_improvement REAL NOT NULL,
    supporting_evidence_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open',
    source TEXT NOT NULL DEFAULT 'reliability_copilot',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS optimization_events (
    id TEXT PRIMARY KEY,
    recommendation_id TEXT REFERENCES recommendations(id) ON DELETE SET NULL,
    scope TEXT NOT NULL DEFAULT 'global',
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    action_type TEXT NOT NULL,
    target TEXT NOT NULL,
    confidence REAL NOT NULL,
    estimated_success_improvement REAL NOT NULL,
    dry_run INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0,
    rollback_supported INTEGER NOT NULL DEFAULT 1,
    rollback_event_id TEXT,
    previous_state_json TEXT NOT NULL DEFAULT '{}',
    new_state_json TEXT NOT NULL DEFAULT '{}',
    supporting_evidence_json TEXT NOT NULL DEFAULT '[]',
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    rolled_back_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ai_decisions (
    id TEXT PRIMARY KEY,
    recommendation_id TEXT REFERENCES recommendations(id) ON DELETE SET NULL,
    optimization_event_id TEXT REFERENCES optimization_events(id) ON DELETE SET NULL,
    source TEXT NOT NULL DEFAULT 'reliability_copilot',
    action_type TEXT NOT NULL,
    target TEXT NOT NULL,
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    rollback_supported INTEGER NOT NULL DEFAULT 0,
    autonomous_allowed INTEGER NOT NULL DEFAULT 0,
    human_approval_required INTEGER NOT NULL DEFAULT 0,
    second_model_required INTEGER NOT NULL DEFAULT 1,
    reason TEXT NOT NULL,
    rule_checks_json TEXT NOT NULL DEFAULT '[]',
    action_json TEXT NOT NULL DEFAULT '{}',
    rollback_plan_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS decision_verifications (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES ai_decisions(id) ON DELETE CASCADE,
    verifier_type TEXT NOT NULL,
    verifier_name TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS human_approvals (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES ai_decisions(id) ON DELETE CASCADE,
    approver_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_execution_requests (
    request_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    request_text TEXT NOT NULL,
    intent TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_json TEXT NOT NULL DEFAULT '{}',
    validation_result_json TEXT NOT NULL DEFAULT '{}',
    verification_result_json TEXT NOT NULL DEFAULT '{}',
    confirmation_status TEXT NOT NULL DEFAULT 'not_required',
    execution_result_json TEXT NOT NULL DEFAULT '{}',
    chat_id TEXT,
    workflow_id TEXT,
    return_to TEXT NOT NULL DEFAULT '/',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ai_execution_audit_events (
    event_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES ai_execution_requests(request_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_user_created
    ON projects(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_organizations_owner_created
    ON organizations(owner_user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_org_members_user
    ON organization_members(user_id, organization_id);

CREATE INDEX IF NOT EXISTS idx_org_members_org_role
    ON organization_members(organization_id, role);

CREATE INDEX IF NOT EXISTS idx_invitations_org_status
    ON invitations(organization_id, status);

CREATE INDEX IF NOT EXISTS idx_invitations_email_status
    ON invitations(email, status);

CREATE INDEX IF NOT EXISTS idx_api_keys_project_active
    ON api_keys(project_id, is_active);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user_status
    ON subscriptions(user_id, status);

CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_subscription
    ON subscriptions(stripe_subscription_id);

CREATE INDEX IF NOT EXISTS idx_usage_records_user_period
    ON usage_records(user_id, metric_type, created_at);

CREATE INDEX IF NOT EXISTS idx_usage_records_project_period
    ON usage_records(project_id, metric_type, created_at);

CREATE INDEX IF NOT EXISTS idx_users_stripe_customer
    ON users(stripe_customer_id);

CREATE INDEX IF NOT EXISTS idx_stripe_invoices_user_created
    ON stripe_invoices(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_stripe_invoices_subscription
    ON stripe_invoices(stripe_subscription_id);

CREATE INDEX IF NOT EXISTS idx_stripe_events_type
    ON stripe_events(event_type);

CREATE INDEX IF NOT EXISTS idx_request_access_created
    ON request_access_requests(created_at);

CREATE INDEX IF NOT EXISTS idx_analytics_events_type_created
    ON analytics_events(event_type, created_at);

CREATE INDEX IF NOT EXISTS idx_analytics_events_user_created
    ON analytics_events(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_recovery_events_workflow_created
    ON recovery_events(workflow_id, created_at);

CREATE INDEX IF NOT EXISTS idx_recovery_events_category_created
    ON recovery_events(failure_category, created_at);

CREATE INDEX IF NOT EXISTS idx_recovery_events_project_created
    ON recovery_events(project_id, created_at);

CREATE INDEX IF NOT EXISTS idx_recommendations_scope_confidence
    ON recommendations(scope, confidence, estimated_success_improvement);

CREATE INDEX IF NOT EXISTS idx_recommendations_project_created
    ON recommendations(project_id, created_at);

CREATE INDEX IF NOT EXISTS idx_recommendations_category_created
    ON recommendations(category, created_at);

CREATE INDEX IF NOT EXISTS idx_optimization_events_created
    ON optimization_events(created_at);

CREATE INDEX IF NOT EXISTS idx_optimization_events_status_created
    ON optimization_events(status, created_at);

CREATE INDEX IF NOT EXISTS idx_optimization_events_action_created
    ON optimization_events(action_type, created_at);

CREATE INDEX IF NOT EXISTS idx_optimization_events_project_created
    ON optimization_events(project_id, created_at);

CREATE INDEX IF NOT EXISTS idx_ai_decisions_status_created
    ON ai_decisions(status, created_at);

CREATE INDEX IF NOT EXISTS idx_ai_decisions_risk_created
    ON ai_decisions(risk_level, created_at);

CREATE INDEX IF NOT EXISTS idx_ai_decisions_recommendation
    ON ai_decisions(recommendation_id);

CREATE INDEX IF NOT EXISTS idx_decision_verifications_decision
    ON decision_verifications(decision_id, created_at);

CREATE INDEX IF NOT EXISTS idx_human_approvals_decision
    ON human_approvals(decision_id, created_at);

CREATE INDEX IF NOT EXISTS idx_ai_execution_user_created
    ON ai_execution_requests(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_ai_execution_status_created
    ON ai_execution_requests(status, created_at);

CREATE INDEX IF NOT EXISTS idx_ai_execution_audit_request_created
    ON ai_execution_audit_events(request_id, created_at);

-- Existing databases need these columns added once. SQLite does not support
-- ADD COLUMN IF NOT EXISTS in all versions, so the application also performs
-- an idempotent migration using PRAGMA table_info().
ALTER TABLE sdk_workflows ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE sdk_workflows ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE sdk_workflows ADD COLUMN api_key_id TEXT REFERENCES api_keys(id) ON DELETE SET NULL;
ALTER TABLE projects ADD COLUMN organization_id TEXT REFERENCES organizations(id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN stripe_customer_id TEXT;
ALTER TABLE subscriptions ADD COLUMN stripe_subscription_id TEXT;
ALTER TABLE subscriptions ADD COLUMN stripe_price_id TEXT;
ALTER TABLE subscriptions ADD COLUMN stripe_status TEXT;

CREATE INDEX IF NOT EXISTS idx_projects_org_created
    ON projects(organization_id, created_at);

CREATE INDEX IF NOT EXISTS idx_sdk_workflows_owner_started
    ON sdk_workflows(user_id, project_id, started_at);
