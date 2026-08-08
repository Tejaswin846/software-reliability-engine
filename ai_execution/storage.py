from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(
    os.getenv("SOFTWARE_API_DB_PATH", DATA_DIR / "software_reliability.db")
).expanduser()
_STORAGE_INIT_LOCK = threading.Lock()
_INITIALIZED_STORAGE: set[str] = set()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _loads(value: Optional[str], default: Any) -> Any:
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
    db.execute("PRAGMA cache_size = -8192")
    return db


def initialize_storage() -> None:
    database_key = os.path.abspath(os.fspath(DB_PATH))
    if database_key in _INITIALIZED_STORAGE and DB_PATH.exists():
        return
    with _STORAGE_INIT_LOCK:
        if database_key in _INITIALIZED_STORAGE and DB_PATH.exists():
            return
        with connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(
            """
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

            CREATE INDEX IF NOT EXISTS idx_ai_execution_user_created
                ON ai_execution_requests(user_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_ai_execution_status_created
                ON ai_execution_requests(status, created_at);

            CREATE INDEX IF NOT EXISTS idx_ai_execution_audit_request_created
                ON ai_execution_audit_events(request_id, created_at);

            CREATE TABLE IF NOT EXISTS risk_verification_workflows (
                user_id TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                state_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, workflow_id)
            );

            CREATE TABLE IF NOT EXISTS risk_verification_evidence (
                event_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                trusted INTEGER NOT NULL DEFAULT 0,
                independent INTEGER NOT NULL DEFAULT 0,
                success INTEGER,
                event_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS risk_verification_decisions (
                decision_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                phase TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                decision TEXT NOT NULL CHECK (decision IN ('ALLOW', 'RETRY', 'BLOCK', 'REVIEW')),
                verification_level TEXT NOT NULL CHECK (verification_level IN ('A', 'B', 'C', 'S')),
                verifier TEXT NOT NULL,
                current_risk REAL NOT NULL DEFAULT 0,
                cumulative_risk REAL NOT NULL DEFAULT 0,
                uncertainty REAL NOT NULL DEFAULT 0,
                evidence_strength REAL NOT NULL DEFAULT 0,
                original_tokens INTEGER NOT NULL DEFAULT 0,
                verification_tokens INTEGER NOT NULL DEFAULT 0,
                avoided_tokens INTEGER NOT NULL DEFAULT 0,
                latency_ms REAL NOT NULL DEFAULT 0,
                prevented_failure INTEGER NOT NULL DEFAULT 0,
                false_positive INTEGER NOT NULL DEFAULT 0,
                false_negative INTEGER NOT NULL DEFAULT 0,
                audit_sampled INTEGER NOT NULL DEFAULT 0,
                audit_outcome TEXT,
                reason TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS risk_verification_audits (
                audit_id TEXT PRIMARY KEY,
                decision_id TEXT NOT NULL REFERENCES risk_verification_decisions(decision_id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK (outcome IN ('passed', 'hidden_error', 'false_positive', 'false_negative')),
                discovered_error INTEGER NOT NULL DEFAULT 0,
                verifier TEXT NOT NULL,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_risk_evidence_workflow_created
                ON risk_verification_evidence(user_id, workflow_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_risk_decisions_workflow_created
                ON risk_verification_decisions(user_id, workflow_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_risk_decisions_metrics
                ON risk_verification_decisions(user_id, decision, verification_level, created_at);

            CREATE INDEX IF NOT EXISTS idx_risk_audits_workflow_created
                ON risk_verification_audits(user_id, workflow_id, created_at);
            """
            )
        _INITIALIZED_STORAGE.add(database_key)


def save_request(record: Dict[str, Any]) -> None:
    initialize_storage()
    with connect() as db:
        db.execute(
            """
            INSERT INTO ai_execution_requests (
                request_id, user_id, request_text, intent, risk_level, status,
                plan_json, validation_result_json, verification_result_json,
                confirmation_status, execution_result_json, chat_id, workflow_id,
                return_to, created_at, updated_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(request_id) DO UPDATE SET
                status = excluded.status,
                plan_json = excluded.plan_json,
                validation_result_json = excluded.validation_result_json,
                verification_result_json = excluded.verification_result_json,
                confirmation_status = excluded.confirmation_status,
                execution_result_json = excluded.execution_result_json,
                updated_at = excluded.updated_at,
                metadata_json = excluded.metadata_json
            """,
            (
                record["request_id"],
                record["user_id"],
                record["request_text"],
                record["intent"],
                record["risk_level"],
                record["status"],
                _dumps(record.get("plan") or {}),
                _dumps(record.get("validation_result") or {}),
                _dumps(record.get("verification_result") or {}),
                record.get("confirmation_status") or "not_required",
                _dumps(record.get("execution_result") or {}),
                record.get("chat_id"),
                record.get("workflow_id"),
                record.get("return_to") or "/",
                record.get("created_at") or _now_iso(),
                record.get("updated_at") or _now_iso(),
                _dumps(record.get("metadata") or {}),
            ),
        )


def append_audit_event(
    request_id: str,
    user_id: str,
    stage: str,
    status: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    initialize_storage()
    event = {
        "event_id": f"aia_{uuid.uuid4().hex}",
        "request_id": request_id,
        "user_id": user_id,
        "stage": stage,
        "status": status,
        "payload": payload,
        "created_at": _now_iso(),
    }
    with connect() as db:
        db.execute(
            """
            INSERT INTO ai_execution_audit_events (
                event_id, request_id, user_id, stage, status, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["event_id"],
                request_id,
                user_id,
                stage,
                status,
                _dumps(payload),
                event["created_at"],
            ),
        )
    return event


def _record_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    item["plan"] = _loads(item.pop("plan_json"), {})
    item["validation_result"] = _loads(item.pop("validation_result_json"), {})
    item["verification_result"] = _loads(item.pop("verification_result_json"), {})
    item["execution_result"] = _loads(item.pop("execution_result_json"), {})
    item["metadata"] = _loads(item.pop("metadata_json"), {})
    return item


def get_request(request_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    initialize_storage()
    with connect() as db:
        row = db.execute(
            """
            SELECT *
            FROM ai_execution_requests
            WHERE request_id = ? AND user_id = ?
            """,
            (request_id, user_id),
        ).fetchone()
    return _record_from_row(row) if row else None


def get_audit(request_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    request = get_request(request_id, user_id)
    if request is None:
        return None
    with connect() as db:
        rows = db.execute(
            """
            SELECT *
            FROM ai_execution_audit_events
            WHERE request_id = ? AND user_id = ?
            ORDER BY created_at ASC
            """,
            (request_id, user_id),
        ).fetchall()
    events: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["payload"] = _loads(item.pop("payload_json"), {})
        events.append(item)
    return {"request": request, "events": events}


def get_workflow_risk_state(user_id: str, workflow_id: str) -> Dict[str, Any]:
    initialize_storage()
    with connect() as db:
        row = db.execute(
            """
            SELECT policy_version, state_json, created_at, updated_at
            FROM risk_verification_workflows
            WHERE user_id = ? AND workflow_id = ?
            """,
            (user_id, workflow_id),
        ).fetchone()
    if row is None:
        return {}
    state = _loads(row["state_json"], {})
    state["policy_version"] = row["policy_version"]
    state["created_at"] = row["created_at"]
    state["updated_at"] = row["updated_at"]
    return state


def record_verification_evaluation(
    *,
    user_id: str,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    initialize_storage()
    workflow_id = str(result["workflow_id"])
    created_at = str(result.get("created_at") or _now_iso())
    state = dict(result.get("workflow_state") or {})
    evidence = list(result.get("normalized_evidence") or [])
    budget = result.get("budget") or {}
    risk = result.get("risk") or {}
    evidence_score = result.get("evidence") or {}
    audit = result.get("semantic_audit") or {}
    deterministic = result.get("deterministic") or {}
    prevented_failure = bool(
        result.get("decision") == "BLOCK"
        and (
            deterministic.get("hard_failures")
            or deterministic.get("contradiction")
        )
    )
    avoided_tokens = (
        int(budget.get("expected_retry_tokens") or 0)
        if prevented_failure or result.get("decision") == "RETRY"
        else 0
    )
    stored_result = dict(result)
    # Evidence has its own normalized table. The decision retains only references.
    stored_result["normalized_evidence"] = [item.get("event_id") for item in evidence]
    with connect() as db:
        db.execute(
            """
            INSERT INTO risk_verification_workflows (
                user_id, workflow_id, policy_version, state_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, workflow_id) DO UPDATE SET
                policy_version = excluded.policy_version,
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                workflow_id,
                result["policy_version"],
                _dumps(state),
                created_at,
                created_at,
            ),
        )
        for event in evidence:
            success = event.get("success")
            db.execute(
                """
                INSERT INTO risk_verification_evidence (
                    event_id, user_id, workflow_id, step_id, event_type,
                    source, trusted, independent, success, event_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING
                """,
                (
                    event["event_id"],
                    user_id,
                    workflow_id,
                    event["step_id"],
                    event["event_type"],
                    event["source"],
                    1 if event.get("trusted") else 0,
                    1 if event.get("independent") else 0,
                    None if success is None else 1 if success else 0,
                    _dumps(event),
                    event.get("created_at") or created_at,
                ),
            )
        db.execute(
            """
            INSERT INTO risk_verification_decisions (
                decision_id, user_id, workflow_id, step_id, phase,
                policy_version, decision, verification_level, verifier,
                current_risk, cumulative_risk, uncertainty, evidence_strength,
                original_tokens, verification_tokens, avoided_tokens, latency_ms,
                prevented_failure, audit_sampled, reason, details_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result["decision_id"],
                user_id,
                workflow_id,
                result["step_id"],
                result["phase"],
                result["policy_version"],
                result["decision"],
                result["verification_level"],
                result["verifier"],
                float(risk.get("current_action_score") or 0.0),
                float(risk.get("cumulative_workflow_score") or 0.0),
                float(evidence_score.get("uncertainty") or 0.0),
                float(evidence_score.get("score") or 0.0),
                int(budget.get("original_tokens") or 0),
                int(budget.get("current_event_tokens") or 0),
                avoided_tokens,
                float(result.get("decision_latency_ms") or 0.0),
                1 if prevented_failure else 0,
                1 if audit.get("sampled") else 0,
                str(result.get("reason") or ""),
                _dumps(stored_result),
                created_at,
            ),
        )
    return result


def list_workflow_evidence(
    *,
    user_id: str,
    workflow_id: str,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    initialize_storage()
    with connect() as db:
        rows = db.execute(
            """
            SELECT event_json
            FROM risk_verification_evidence
            WHERE user_id = ? AND workflow_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, workflow_id, max(1, min(1000, int(limit)))),
        ).fetchall()
    return [_loads(row["event_json"], {}) for row in rows]


def list_workflow_decisions(
    *,
    user_id: str,
    workflow_id: str,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    initialize_storage()
    with connect() as db:
        rows = db.execute(
            """
            SELECT details_json
            FROM risk_verification_decisions
            WHERE user_id = ? AND workflow_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, workflow_id, max(1, min(500, int(limit)))),
        ).fetchall()
    return [_loads(row["details_json"], {}) for row in rows]


def pending_semantic_audits(*, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    initialize_storage()
    with connect() as db:
        rows = db.execute(
            """
            SELECT decision_id, workflow_id, step_id, verifier, reason, details_json, created_at
            FROM risk_verification_decisions
            WHERE user_id = ? AND audit_sampled = 1 AND audit_outcome IS NULL
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (user_id, max(1, min(500, int(limit)))),
        ).fetchall()
    items: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["decision"] = _loads(item.pop("details_json"), {})
        items.append(item)
    return items


def record_semantic_audit(
    *,
    user_id: str,
    decision_id: str,
    outcome: str,
    verifier: str,
    tokens_used: int = 0,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    initialize_storage()
    normalized_outcome = str(outcome).strip().lower()
    allowed = {"passed", "hidden_error", "false_positive", "false_negative"}
    if normalized_outcome not in allowed:
        raise ValueError("Unsupported semantic audit outcome.")
    created_at = _now_iso()
    audit_id = f"rava_{uuid.uuid4().hex}"
    discovered_error = normalized_outcome in {"hidden_error", "false_negative"}
    with connect() as db:
        decision = db.execute(
            """
            SELECT workflow_id, audit_sampled
            FROM risk_verification_decisions
            WHERE decision_id = ? AND user_id = ?
            """,
            (decision_id, user_id),
        ).fetchone()
        if decision is None:
            raise LookupError("Verification decision not found.")
        db.execute(
            """
            INSERT INTO risk_verification_audits (
                audit_id, decision_id, user_id, workflow_id, outcome,
                discovered_error, verifier, tokens_used, notes, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                decision_id,
                user_id,
                decision["workflow_id"],
                normalized_outcome,
                1 if discovered_error else 0,
                verifier,
                max(0, int(tokens_used)),
                notes,
                created_at,
            ),
        )
        db.execute(
            """
            UPDATE risk_verification_decisions
            SET audit_outcome = ?,
                false_positive = CASE WHEN ? = 'false_positive' THEN 1 ELSE false_positive END,
                false_negative = CASE WHEN ? IN ('hidden_error', 'false_negative') THEN 1 ELSE false_negative END,
                verification_tokens = verification_tokens + ?
            WHERE decision_id = ? AND user_id = ?
            """,
            (
                normalized_outcome,
                normalized_outcome,
                normalized_outcome,
                max(0, int(tokens_used)),
                decision_id,
                user_id,
            ),
        )
        workflow = db.execute(
            """
            SELECT state_json
            FROM risk_verification_workflows
            WHERE user_id = ? AND workflow_id = ?
            """,
            (user_id, decision["workflow_id"]),
        ).fetchone()
        if workflow:
            state = _loads(workflow["state_json"], {})
            stats = dict(state.get("audit_stats") or {})
            stats["completed"] = int(stats.get("completed") or 0) + 1
            if discovered_error:
                stats["errors_discovered"] = int(stats.get("errors_discovered") or 0) + 1
            state["audit_stats"] = stats
            state["verification_tokens_spent"] = int(state.get("verification_tokens_spent") or 0) + max(0, int(tokens_used))
            state["updated_at"] = created_at
            db.execute(
                """
                UPDATE risk_verification_workflows
                SET state_json = ?, updated_at = ?
                WHERE user_id = ? AND workflow_id = ?
                """,
                (_dumps(state), created_at, user_id, decision["workflow_id"]),
            )
    return {
        "audit_id": audit_id,
        "decision_id": decision_id,
        "workflow_id": decision["workflow_id"],
        "outcome": normalized_outcome,
        "discovered_error": discovered_error,
        "verifier": verifier,
        "tokens_used": max(0, int(tokens_used)),
        "notes": notes,
        "created_at": created_at,
    }


def verification_metrics(*, user_id: str) -> Dict[str, Any]:
    initialize_storage()
    with connect() as db:
        summary = db.execute(
            """
            SELECT
                COUNT(*) AS decisions,
                COALESCE(SUM(original_tokens), 0) AS original_tokens,
                COALESCE(SUM(verification_tokens), 0) AS verification_tokens,
                COALESCE(SUM(avoided_tokens), 0) AS avoided_tokens,
                COALESCE(SUM(prevented_failure), 0) AS prevented_failures,
                COALESCE(SUM(false_positive), 0) AS false_positives,
                COALESCE(SUM(false_negative), 0) AS false_negatives,
                COALESCE(SUM(audit_sampled), 0) AS audits_sampled,
                COALESCE(SUM(CASE WHEN audit_outcome = 'hidden_error' THEN 1 ELSE 0 END), 0) AS audit_discoveries,
                COALESCE(SUM(CASE WHEN verification_level IN ('B', 'C', 'S') THEN 1 ELSE 0 END), 0) AS escalations,
                COALESCE(AVG(latency_ms), 0) AS decision_latency_ms
            FROM risk_verification_decisions
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        audits = db.execute(
            "SELECT COUNT(*) AS completed FROM risk_verification_audits WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    decisions = int(summary["decisions"] or 0)
    original_tokens = int(summary["original_tokens"] or 0)
    verification_tokens = int(summary["verification_tokens"] or 0)
    avoided_tokens = int(summary["avoided_tokens"] or 0)
    prevented = int(summary["prevented_failures"] or 0)
    false_positives = int(summary["false_positives"] or 0)
    false_negatives = int(summary["false_negatives"] or 0)
    completed_audits = int(audits["completed"] or 0)
    discoveries = int(summary["audit_discoveries"] or 0)
    return {
        "policy_version": "risk-adaptive-v2.0",
        "decision_count": decisions,
        "verification_overhead": round(verification_tokens / original_tokens, 6) if original_tokens else 0.0,
        "net_token_saving": avoided_tokens - verification_tokens,
        "false_positive_rate": round(false_positives / decisions, 6) if decisions else 0.0,
        "false_negative_rate": round(false_negatives / decisions, 6) if decisions else 0.0,
        "audit_discovery_rate": round(discoveries / completed_audits, 6) if completed_audits else 0.0,
        "escalation_rate": round(int(summary["escalations"] or 0) / decisions, 6) if decisions else 0.0,
        "decision_latency_ms": round(float(summary["decision_latency_ms"] or 0.0), 3),
        "cost_per_prevented_failure_tokens": round(verification_tokens / prevented, 3) if prevented else None,
        "reliability_gain_per_token": round((prevented + discoveries) / verification_tokens, 8) if verification_tokens else 0.0,
        "original_tokens": original_tokens,
        "verification_tokens": verification_tokens,
        "avoided_tokens": avoided_tokens,
        "prevented_failures": prevented,
        "semantic_audits_completed": completed_audits,
        "hidden_errors_discovered": discoveries,
    }
