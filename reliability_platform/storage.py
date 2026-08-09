from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = Path(
    os.getenv(
        "SOFTWARE_RELIABILITY_PLATFORM_DB_PATH",
        BASE_DIR / "data" / "reliability_platform.db",
    )
).expanduser()
_INIT_LOCK = threading.Lock()
_INITIALIZED: set[str] = set()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 30000")
    db.execute("PRAGMA synchronous = NORMAL")
    db.execute("PRAGMA temp_store = MEMORY")
    db.execute("PRAGMA cache_size = -16384")
    return db


@contextmanager
def transaction(*, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    initialize()
    db = connect()
    try:
        if immediate:
            db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize() -> None:
    database_key = os.path.abspath(os.fspath(DB_PATH))
    if database_key in _INITIALIZED and DB_PATH.exists():
        return
    with _INIT_LOCK:
        if database_key in _INITIALIZED and DB_PATH.exists():
            return
        with connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS reliability_observations (
                    observation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    trace_id TEXT NOT NULL,
                    span_id TEXT NOT NULL,
                    parent_span_id TEXT,
                    workflow_id TEXT,
                    agent_id TEXT,
                    observation_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    tool_name TEXT,
                    model TEXT,
                    provider TEXT,
                    status TEXT NOT NULL,
                    risk_score REAL NOT NULL DEFAULT 0,
                    evidence_strength REAL NOT NULL DEFAULT 0,
                    decision TEXT,
                    error_type TEXT,
                    latency_ms REAL NOT NULL DEFAULT 0,
                    token_cost INTEGER NOT NULL DEFAULT 0,
                    input_ref TEXT,
                    output_ref TEXT,
                    source TEXT NOT NULL,
                    framework TEXT,
                    sampled INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reliability_tool_contracts (
                    contract_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    tool_name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    input_schema_json TEXT NOT NULL DEFAULT '{}',
                    output_schema_json TEXT NOT NULL DEFAULT '{}',
                    permissions_json TEXT NOT NULL DEFAULT '[]',
                    risk_level TEXT NOT NULL,
                    side_effect TEXT NOT NULL,
                    reversible INTEGER NOT NULL DEFAULT 0,
                    idempotent INTEGER NOT NULL DEFAULT 0,
                    expected_side_effects_json TEXT NOT NULL DEFAULT '[]',
                    expected_state_changes_json TEXT NOT NULL DEFAULT '[]',
                    evidence_contract_json TEXT NOT NULL DEFAULT '{}',
                    max_retries INTEGER NOT NULL DEFAULT 0,
                    risk_floor REAL NOT NULL DEFAULT 0,
                    human_confirmation_required INTEGER NOT NULL DEFAULT 0,
                    compensation_tool TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, project_id, tool_name, version)
                );

                CREATE TABLE IF NOT EXISTS reliability_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    workflow_id TEXT NOT NULL,
                    step_id TEXT,
                    source TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    provider_request_id TEXT,
                    provider_response_id TEXT,
                    content_hash TEXT NOT NULL,
                    trust_level TEXT NOT NULL,
                    independence_group TEXT,
                    derived_from_json TEXT NOT NULL DEFAULT '[]',
                    verified_by_json TEXT NOT NULL DEFAULT '[]',
                    taint_status TEXT NOT NULL DEFAULT 'trusted'
                        CHECK (taint_status IN ('trusted', 'untrusted', 'tainted', 'reverified')),
                    freshness_at TEXT NOT NULL,
                    expires_at TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reliability_evidence_edges (
                    edge_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    parent_evidence_id TEXT NOT NULL,
                    child_evidence_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    contaminated INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(parent_evidence_id, child_evidence_id, relation)
                );

                CREATE TABLE IF NOT EXISTS reliability_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    workflow_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    workflow_state_json TEXT NOT NULL DEFAULT '{}',
                    verified_facts_json TEXT NOT NULL DEFAULT '[]',
                    pending_actions_json TEXT NOT NULL DEFAULT '[]',
                    completed_side_effects_json TEXT NOT NULL DEFAULT '[]',
                    compensation_actions_json TEXT NOT NULL DEFAULT '[]',
                    risk_score REAL NOT NULL DEFAULT 0,
                    budget_json TEXT NOT NULL DEFAULT '{}',
                    tool_permissions_json TEXT NOT NULL DEFAULT '[]',
                    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                    goal_hash TEXT,
                    cancellation_epoch INTEGER NOT NULL DEFAULT 0,
                    verified INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, workflow_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS reliability_sagas (
                    saga_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    workflow_id TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('running', 'compensating', 'completed', 'failed', 'cancelled')),
                    cancellation_epoch INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reliability_saga_steps (
                    step_id TEXT PRIMARY KEY,
                    saga_id TEXT NOT NULL REFERENCES reliability_sagas(saga_id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    compensation_action TEXT,
                    reversible INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL
                        CHECK (status IN ('pending', 'completed', 'failed', 'compensated', 'compensation_failed')),
                    action_receipt_json TEXT NOT NULL DEFAULT '{}',
                    compensation_receipt_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(saga_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS reliability_datasets (
                    dataset_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    protected INTEGER NOT NULL DEFAULT 1,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, project_id, name, version)
                );

                CREATE TABLE IF NOT EXISTS reliability_dataset_cases (
                    case_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL REFERENCES reliability_datasets(dataset_id) ON DELETE CASCADE,
                    input_json TEXT NOT NULL DEFAULT '{}',
                    initial_state_json TEXT NOT NULL DEFAULT '{}',
                    expected_state_json TEXT NOT NULL DEFAULT '{}',
                    tool_availability_json TEXT NOT NULL DEFAULT '[]',
                    expected_tool_sequence_json TEXT NOT NULL DEFAULT '[]',
                    expected_output_json TEXT NOT NULL DEFAULT '{}',
                    expected_failure_type TEXT,
                    risk_score REAL NOT NULL DEFAULT 0,
                    correct_decision TEXT NOT NULL,
                    source_failure_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reliability_experiments (
                    experiment_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    dataset_id TEXT REFERENCES reliability_datasets(dataset_id) ON DELETE SET NULL,
                    control_json TEXT NOT NULL DEFAULT '{}',
                    candidate_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL CHECK (status IN ('draft', 'running', 'completed', 'failed')),
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS reliability_experiment_results (
                    result_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL REFERENCES reliability_experiments(experiment_id) ON DELETE CASCADE,
                    case_id TEXT,
                    variant TEXT NOT NULL,
                    evaluator TEXT NOT NULL,
                    evaluator_version TEXT NOT NULL,
                    score REAL NOT NULL,
                    passed INTEGER NOT NULL,
                    latency_ms REAL NOT NULL DEFAULT 0,
                    token_cost INTEGER NOT NULL DEFAULT 0,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reliability_evaluator_versions (
                    evaluator_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    evaluator_type TEXT NOT NULL,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, project_id, name, version)
                );

                CREATE TABLE IF NOT EXISTS reliability_annotations (
                    annotation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    workflow_id TEXT,
                    observation_id TEXT,
                    decision_id TEXT,
                    queue_reason TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'claimed', 'completed')),
                    assigned_to TEXT,
                    label TEXT,
                    notes TEXT,
                    reviewer_confidence REAL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS reliability_failure_clusters (
                    cluster_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    signature TEXT NOT NULL,
                    failure_type TEXT NOT NULL,
                    provider TEXT,
                    tool_name TEXT,
                    model TEXT,
                    workflow_count INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(user_id, project_id, signature)
                );

                CREATE TABLE IF NOT EXISTS reliability_failure_members (
                    member_id TEXT PRIMARY KEY,
                    cluster_id TEXT NOT NULL REFERENCES reliability_failure_clusters(cluster_id) ON DELETE CASCADE,
                    workflow_id TEXT NOT NULL,
                    observation_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(cluster_id, workflow_id, observation_id)
                );

                CREATE TABLE IF NOT EXISTS reliability_drift_reports (
                    report_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    component_type TEXT NOT NULL,
                    component_name TEXT NOT NULL,
                    baseline_window_json TEXT NOT NULL,
                    current_window_json TEXT NOT NULL,
                    drift_score REAL NOT NULL,
                    signals_json TEXT NOT NULL DEFAULT '{}',
                    severity TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reliability_causal_edges (
                    edge_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    root_failure_id TEXT NOT NULL,
                    cause_id TEXT NOT NULL,
                    effect_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    blast_radius INTEGER NOT NULL DEFAULT 0,
                    contaminated_outputs_json TEXT NOT NULL DEFAULT '[]',
                    external_side_effects_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reliability_policies (
                    policy_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    mode TEXT NOT NULL CHECK (mode IN ('shadow', 'partial', 'enforce')),
                    rollout_percent REAL NOT NULL DEFAULT 0,
                    rules_json TEXT NOT NULL DEFAULT '[]',
                    tenant_overrides_json TEXT NOT NULL DEFAULT '{}',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, project_id, name, version)
                );

                CREATE TABLE IF NOT EXISTS reliability_policy_decisions (
                    decision_id TEXT PRIMARY KEY,
                    policy_id TEXT NOT NULL REFERENCES reliability_policies(policy_id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    workflow_id TEXT,
                    mode TEXT NOT NULL,
                    predicted_decision TEXT NOT NULL,
                    enforced_decision TEXT NOT NULL,
                    actual_outcome TEXT,
                    matched_rules_json TEXT NOT NULL DEFAULT '[]',
                    risk_score REAL NOT NULL DEFAULT 0,
                    sample_rate REAL NOT NULL DEFAULT 0,
                    versions_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reliability_alert_rules (
                    rule_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    threshold REAL NOT NULL,
                    severity TEXT NOT NULL,
                    destinations_json TEXT NOT NULL DEFAULT '[]',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reliability_alerts (
                    alert_id TEXT PRIMARY KEY,
                    rule_id TEXT REFERENCES reliability_alert_rules(rule_id) ON DELETE SET NULL,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    signal TEXT NOT NULL,
                    observed_value REAL NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('open', 'acknowledged', 'resolved')),
                    context_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS reliability_incidents (
                    incident_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    title TEXT NOT NULL,
                    root_signal TEXT NOT NULL,
                    likely_cause TEXT,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('open', 'investigating', 'resolved')),
                    affected_workflows INTEGER NOT NULL DEFAULT 0,
                    affected_customers INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS reliability_incident_members (
                    member_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL REFERENCES reliability_incidents(incident_id) ON DELETE CASCADE,
                    workflow_id TEXT NOT NULL,
                    failure_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(incident_id, workflow_id, failure_id)
                );

                CREATE TABLE IF NOT EXISTS reliability_component_calibration (
                    calibration_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    component_type TEXT NOT NULL,
                    component_name TEXT NOT NULL,
                    total_events INTEGER NOT NULL,
                    successes INTEGER NOT NULL,
                    failures INTEGER NOT NULL,
                    false_positives INTEGER NOT NULL,
                    false_negatives INTEGER NOT NULL,
                    reliability REAL NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reliability_replay_runs (
                    replay_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    source_trace_id TEXT NOT NULL,
                    model_version TEXT,
                    prompt_version TEXT,
                    policy_version TEXT,
                    verifier_version TEXT,
                    tool_schema_version TEXT,
                    simulation_only INTEGER NOT NULL DEFAULT 1,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reliability_workflow_goals (
                    goal_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    workflow_id TEXT NOT NULL,
                    original_goal TEXT NOT NULL,
                    goal_hash TEXT NOT NULL,
                    current_plan_json TEXT NOT NULL DEFAULT '{}',
                    completed_milestones_json TEXT NOT NULL DEFAULT '[]',
                    verified_milestones_json TEXT NOT NULL DEFAULT '[]',
                    remaining_milestones_json TEXT NOT NULL DEFAULT '[]',
                    context_degradation REAL NOT NULL DEFAULT 0,
                    goal_drift_score REAL NOT NULL DEFAULT 0,
                    budget_json TEXT NOT NULL DEFAULT '{}',
                    cumulative_risk REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, workflow_id)
                );

                CREATE TABLE IF NOT EXISTS reliability_subagent_links (
                    link_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    parent_agent_id TEXT,
                    agent_id TEXT NOT NULL,
                    depth INTEGER NOT NULL DEFAULT 0,
                    token_cost INTEGER NOT NULL DEFAULT 0,
                    risk_score REAL NOT NULL DEFAULT 0,
                    cancellation_epoch INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'running',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, workflow_id, agent_id)
                );

                CREATE TABLE IF NOT EXISTS reliability_protected_benchmarks (
                    benchmark_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    baseline_json TEXT NOT NULL DEFAULT '{}',
                    protected_json TEXT NOT NULL DEFAULT '{}',
                    deltas_json TEXT NOT NULL DEFAULT '{}',
                    passed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reliability_service_accounts (
                    account_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    scopes_json TEXT NOT NULL DEFAULT '[]',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, project_id, name)
                );

                CREATE TABLE IF NOT EXISTS reliability_service_account_keys (
                    key_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES reliability_service_accounts(account_id) ON DELETE CASCADE,
                    key_hash TEXT NOT NULL UNIQUE,
                    key_prefix TEXT NOT NULL,
                    scopes_json TEXT NOT NULL DEFAULT '[]',
                    expires_at TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT
                );

                CREATE TABLE IF NOT EXISTS reliability_deletion_audit (
                    deletion_id TEXT PRIMARY KEY,
                    subject_hash TEXT NOT NULL,
                    project_hash TEXT,
                    deleted_counts_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reliability_tenant_controls (
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    max_requests_per_minute INTEGER NOT NULL DEFAULT 600,
                    max_active_workflows INTEGER NOT NULL DEFAULT 100,
                    max_queue_depth INTEGER NOT NULL DEFAULT 10000,
                    max_monthly_tokens INTEGER NOT NULL DEFAULT 10000000,
                    retention_days INTEGER NOT NULL DEFAULT 90,
                    region TEXT NOT NULL DEFAULT 'auto',
                    encryption_key_ref TEXT,
                    sso_config_json TEXT NOT NULL DEFAULT '{}',
                    backup_verified_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, project_id)
                );

                CREATE TABLE IF NOT EXISTS reliability_admission_windows (
                    user_id TEXT NOT NULL,
                    project_id TEXT,
                    window_start TEXT NOT NULL,
                    request_count INTEGER NOT NULL DEFAULT 0,
                    active_workflows INTEGER NOT NULL DEFAULT 0,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, project_id, window_start)
                );

                CREATE INDEX IF NOT EXISTS idx_observations_query
                    ON reliability_observations(user_id, project_id, status, risk_score, created_at);
                CREATE INDEX IF NOT EXISTS idx_observations_trace
                    ON reliability_observations(user_id, trace_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_observations_tool
                    ON reliability_observations(user_id, tool_name, status, created_at);
                CREATE INDEX IF NOT EXISTS idx_observations_workflow
                    ON reliability_observations(user_id, workflow_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_evidence_workflow
                    ON reliability_evidence(user_id, workflow_id, taint_status, created_at);
                CREATE INDEX IF NOT EXISTS idx_checkpoints_restore
                    ON reliability_checkpoints(user_id, workflow_id, verified, sequence DESC);
                CREATE INDEX IF NOT EXISTS idx_annotations_queue
                    ON reliability_annotations(user_id, project_id, status, queue_reason, created_at);
                CREATE INDEX IF NOT EXISTS idx_failures_cluster
                    ON reliability_failure_clusters(user_id, project_id, last_seen_at);
                CREATE INDEX IF NOT EXISTS idx_policy_decisions_analysis
                    ON reliability_policy_decisions(user_id, project_id, predicted_decision, actual_outcome, created_at);
                CREATE INDEX IF NOT EXISTS idx_alerts_open
                    ON reliability_alerts(user_id, project_id, status, severity, created_at);
                CREATE INDEX IF NOT EXISTS idx_incidents_open
                    ON reliability_incidents(user_id, project_id, status, last_seen_at);
                CREATE INDEX IF NOT EXISTS idx_service_accounts_owner
                    ON reliability_service_accounts(user_id, project_id, active);
                CREATE INDEX IF NOT EXISTS idx_benchmarks_owner
                    ON reliability_protected_benchmarks(user_id, project_id, created_at);
                """
            )
        _INITIALIZED.add(database_key)


def rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    initialize()
    with connect() as db:
        return [dict(row) for row in db.execute(query, params).fetchall()]


def row(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    initialize()
    with connect() as db:
        result = db.execute(query, params).fetchone()
        return dict(result) if result is not None else None


__all__ = [
    "DB_PATH",
    "connect",
    "dumps",
    "initialize",
    "loads",
    "now_iso",
    "row",
    "rows",
    "transaction",
]
