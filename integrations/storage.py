from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(
    os.getenv("SOFTWARE_API_DB_PATH", DATA_DIR / "software_reliability.db")
).expanduser()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _key_source() -> str:
    return (
        os.getenv("INTEGRATION_ENCRYPTION_KEY", "").strip()
        or os.getenv("SOFTWARE_JWT_SECRET", "").strip()
        or os.getenv("JWT_SECRET", "").strip()
        or "software-local-integration-encryption-key"
    )


def encryption_is_production_configured() -> bool:
    return bool(
        os.getenv("INTEGRATION_ENCRYPTION_KEY", "").strip()
        or os.getenv("SOFTWARE_JWT_SECRET", "").strip()
        or os.getenv("JWT_SECRET", "").strip()
    )


def _fernet() -> Fernet:
    digest = hashlib.sha256(_key_source().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_payload(user_id: str, payload: Dict[str, Any]) -> str:
    wrapped = {"user_id": user_id, "payload": payload}
    raw = json.dumps(wrapped, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _fernet().encrypt(raw).decode("ascii")


def decrypt_payload(user_id: str, token: Optional[str]) -> Dict[str, Any]:
    if not token:
        return {}
    try:
        raw = _fernet().decrypt(token.encode("ascii"))
        wrapped = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
        return {}
    if wrapped.get("user_id") != user_id:
        return {}
    payload = wrapped.get("payload")
    return payload if isinstance(payload, dict) else {}


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_storage() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS integration_connections (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                app_id TEXT NOT NULL,
                toolkit_slug TEXT NOT NULL,
                encrypted_metadata TEXT NOT NULL,
                status TEXT NOT NULL,
                health TEXT NOT NULL,
                last_sync_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, app_id)
            );

            CREATE TABLE IF NOT EXISTS integration_pending_actions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                app_id TEXT NOT NULL,
                encrypted_action TEXT NOT NULL,
                encrypted_result TEXT,
                status TEXT NOT NULL,
                return_to TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_integration_connections_user
                ON integration_connections(user_id, app_id);

            CREATE INDEX IF NOT EXISTS idx_integration_pending_user
                ON integration_pending_actions(user_id, status, created_at);
            """
        )


def save_connection(
    user_id: str,
    app_id: str,
    toolkit_slug: str,
    *,
    status: str,
    health: str,
    metadata: Dict[str, Any],
    last_sync_at: Optional[str] = None,
) -> None:
    init_storage()
    now = _now_iso()
    encrypted = encrypt_payload(user_id, metadata)
    with connect() as db:
        db.execute(
            """
            INSERT INTO integration_connections (
                id, user_id, app_id, toolkit_slug, encrypted_metadata,
                status, health, last_sync_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, app_id) DO UPDATE SET
                toolkit_slug = excluded.toolkit_slug,
                encrypted_metadata = excluded.encrypted_metadata,
                status = excluded.status,
                health = excluded.health,
                last_sync_at = excluded.last_sync_at,
                updated_at = excluded.updated_at
            """,
            (
                f"int_{uuid.uuid4().hex}",
                user_id,
                app_id,
                toolkit_slug,
                encrypted,
                status,
                health,
                last_sync_at,
                now,
                now,
            ),
        )


def get_connection(user_id: str, app_id: str) -> Optional[Dict[str, Any]]:
    init_storage()
    with connect() as db:
        row = db.execute(
            """
            SELECT * FROM integration_connections
            WHERE user_id = ? AND app_id = ?
            """,
            (user_id, app_id),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["metadata"] = decrypt_payload(user_id, result.pop("encrypted_metadata"))
    return result


def create_pending_action(
    user_id: str,
    app_id: str,
    action: Dict[str, Any],
    return_to: str,
) -> str:
    init_storage()
    action_id = f"resume_{uuid.uuid4().hex}"
    created_at = _now()
    with connect() as db:
        db.execute(
            """
            INSERT INTO integration_pending_actions (
                id, user_id, app_id, encrypted_action, status,
                return_to, created_at, expires_at
            )
            VALUES (?, ?, ?, ?, 'waiting_for_connection', ?, ?, ?)
            """,
            (
                action_id,
                user_id,
                app_id,
                encrypt_payload(user_id, action),
                return_to,
                created_at.isoformat(),
                (created_at + timedelta(hours=1)).isoformat(),
            ),
        )
    return action_id


def get_pending_action(user_id: str, action_id: str) -> Optional[Dict[str, Any]]:
    init_storage()
    with connect() as db:
        row = db.execute(
            """
            SELECT * FROM integration_pending_actions
            WHERE id = ? AND user_id = ?
            """,
            (action_id, user_id),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["action"] = decrypt_payload(user_id, result.pop("encrypted_action"))
    result["result"] = decrypt_payload(user_id, result.pop("encrypted_result"))
    return result


def complete_pending_action(
    user_id: str,
    action_id: str,
    *,
    status: str,
    result: Dict[str, Any],
) -> None:
    init_storage()
    with connect() as db:
        db.execute(
            """
            UPDATE integration_pending_actions
            SET status = ?, encrypted_result = ?, completed_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                status,
                encrypt_payload(user_id, result),
                _now_iso(),
                action_id,
                user_id,
            ),
        )
