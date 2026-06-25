from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(
    os.getenv("SOFTWARE_API_DB_PATH", DATA_DIR / "software_reliability.db")
).expanduser()


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
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize_storage() -> None:
    with connect() as db:
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
            """
        )


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
