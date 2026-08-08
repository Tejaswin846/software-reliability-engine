from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from . import storage

POLICY_VERSION = "execution-control-v1"
TERMINAL_STATES = {"BLOCK", "CANCELLED", "COMPLETED", "ESCALATED"}
ALLOWED_TRANSITIONS = {
    "RECEIVED": {"PLANNED", "CANCELLED"},
    "PLANNED": {"EVIDENCE_REQUIRED", "BLOCK", "CANCELLED"},
    "EVIDENCE_REQUIRED": {"VERIFYING", "BLOCK", "CANCELLED"},
    "VERIFYING": {"ALLOW", "RETRY", "REVIEW", "BLOCK", "CANCELLED"},
    "RETRY": {"PLANNED", "BLOCK", "CANCELLED"},
    "ALLOW": {"AUTHORIZED", "CANCELLED"},
    "REVIEW": {"AUTHORIZED", "BLOCK", "CANCELLED"},
    "AUTHORIZED": {"EXECUTION_LEASED", "CANCELLED"},
    "EXECUTION_LEASED": {"EXECUTING", "AUTHORIZED", "CANCELLED", "ESCALATED"},
    "EXECUTING": {"POST_VERIFYING", "COMPENSATING", "ESCALATED", "CANCELLED"},
    "POST_VERIFYING": {"VERIFIED", "COMPENSATING", "ESCALATED", "CANCELLED"},
    "VERIFIED": {"COMPLETED", "ESCALATED"},
    "COMPENSATING": {"COMPLETED", "ESCALATED"},
    "BLOCK": set(),
    "CANCELLED": set(),
    "COMPLETED": set(),
    "ESCALATED": set(),
}


class ControlPlaneError(RuntimeError):
    """Base exception for durable execution-control failures."""


class InvalidTransition(ControlPlaneError):
    pass


class LeaseConflict(ControlPlaneError):
    pass


class StaleFence(ControlPlaneError):
    pass


class ExecutionCancelled(ControlPlaneError):
    pass


class IdempotencyConflict(ControlPlaneError):
    pass


@dataclass(frozen=True)
class ExecutionLease:
    workflow_id: str
    step_id: str
    owner: str
    token: str
    fencing_token: int
    cancellation_epoch: int
    expires_at: str
    idempotency_key: str
    replay: bool = False
    response: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "owner": self.owner,
            "token": self.token,
            "fencing_token": self.fencing_token,
            "cancellation_epoch": self.cancellation_epoch,
            "expires_at": self.expires_at,
            "idempotency_key": self.idempotency_key,
            "replay": self.replay,
            "response": self.response,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class SQLiteExecutionControlPlane:
    """Transactional execution control for development and deterministic tests.

    Production uses the equivalent PostgreSQL/Supabase RPC contract. SQLite is
    deliberately retained as an adapter, not as the production architecture.
    """

    backend = "sqlite"

    def __init__(self) -> None:
        self._initialized_database: str | None = None
        self.initialize()

    def initialize(self) -> None:
        database_key = os.path.abspath(os.fspath(storage.DB_PATH))
        if self._initialized_database == database_key and storage.DB_PATH.exists():
            return
        storage.initialize_storage()
        with storage.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS execution_control_states (
                    user_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    parent_step_id TEXT,
                    state TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    risk_score REAL NOT NULL DEFAULT 0,
                    cancellation_epoch INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_token TEXT,
                    lease_expires_at TEXT,
                    fencing_token INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, workflow_id, step_id)
                );

                CREATE TABLE IF NOT EXISTS execution_ledger (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    parent_step_id TEXT,
                    before_state TEXT,
                    after_state TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    risk_score REAL NOT NULL DEFAULT 0,
                    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                    actor TEXT NOT NULL,
                    lease_token TEXT,
                    fencing_token INTEGER,
                    idempotency_key TEXT,
                    cancellation_epoch INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS execution_ledger_no_update
                BEFORE UPDATE ON execution_ledger
                BEGIN
                    SELECT RAISE(ABORT, 'execution ledger is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS execution_ledger_no_delete
                BEFORE DELETE ON execution_ledger
                BEGIN
                    SELECT RAISE(ABORT, 'execution ledger is append-only');
                END;

                CREATE TABLE IF NOT EXISTS execution_outbox (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'leased', 'delivered', 'dead_letter')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 5,
                    available_at TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_token TEXT,
                    lease_expires_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS execution_idempotency_keys (
                    user_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
                    response_json TEXT,
                    fencing_token INTEGER NOT NULL,
                    cancellation_epoch INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS execution_action_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_action_id TEXT,
                    request_fingerprint TEXT NOT NULL,
                    result_fingerprint TEXT NOT NULL,
                    observed_result_json TEXT NOT NULL DEFAULT '{}',
                    fencing_token INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS execution_worker_heartbeats (
                    worker_id TEXT PRIMARY KEY,
                    instance_id TEXT NOT NULL,
                    active_leases INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    heartbeat_at TEXT NOT NULL,
                    started_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_execution_ledger_workflow
                    ON execution_ledger(user_id, workflow_id, step_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_execution_outbox_claim
                    ON execution_outbox(status, available_at, lease_expires_at);
                CREATE INDEX IF NOT EXISTS idx_execution_receipts_workflow
                    ON execution_action_receipts(user_id, workflow_id, step_id, created_at);
                """
            )
        self._initialized_database = database_key

    @staticmethod
    def _row(
        db: sqlite3.Connection, user_id: str, workflow_id: str, step_id: str
    ) -> sqlite3.Row:
        row = db.execute(
            """
            SELECT * FROM execution_control_states
            WHERE user_id = ? AND workflow_id = ? AND step_id = ?
            """,
            (user_id, workflow_id, step_id),
        ).fetchone()
        if row is None:
            raise ControlPlaneError("Execution control state was not found.")
        return row

    @staticmethod
    def _append(
        db: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        before: str | None,
        after: str,
        reason: str,
        actor: str,
        evidence_ids: Iterable[str] | None = None,
        idempotency_key: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        now = _iso()
        event_id = f"led_{uuid.uuid4().hex}"
        safe_payload = payload or {}
        db.execute(
            """
            INSERT INTO execution_ledger (
                event_id, user_id, workflow_id, step_id, parent_step_id,
                before_state, after_state, reason, policy_version, risk_score,
                evidence_ids_json, actor, lease_token, fencing_token,
                idempotency_key, cancellation_epoch, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                row["user_id"],
                row["workflow_id"],
                row["step_id"],
                row["parent_step_id"],
                before,
                after,
                reason,
                row["policy_version"],
                row["risk_score"],
                _json(list(evidence_ids or [])),
                actor,
                row["lease_token"],
                row["fencing_token"],
                idempotency_key,
                row["cancellation_epoch"],
                _json(safe_payload),
                now,
            ),
        )
        outbox_id = f"out_{uuid.uuid4().hex}"
        db.execute(
            """
            INSERT INTO execution_outbox (
                event_id, user_id, workflow_id, step_id, event_type,
                payload_json, available_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outbox_id,
                row["user_id"],
                row["workflow_id"],
                row["step_id"],
                "execution.state_changed",
                _json(
                    {
                        "ledger_event_id": event_id,
                        "before": before,
                        "after": after,
                        "reason": reason,
                        "cancellation_epoch": row["cancellation_epoch"],
                        **safe_payload,
                    }
                ),
                now,
                now,
                now,
            ),
        )
        return event_id

    def _transition(
        self,
        db: sqlite3.Connection,
        *,
        user_id: str,
        workflow_id: str,
        step_id: str,
        after: str,
        reason: str,
        actor: str,
        evidence_ids: Iterable[str] | None = None,
        idempotency_key: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> sqlite3.Row:
        row = self._row(db, user_id, workflow_id, step_id)
        before = row["state"]
        if after not in ALLOWED_TRANSITIONS.get(before, set()):
            raise InvalidTransition(
                f"Execution cannot transition from {before} to {after}."
            )
        now = _iso()
        db.execute(
            """
            UPDATE execution_control_states
            SET state = ?, updated_at = ?
            WHERE user_id = ? AND workflow_id = ? AND step_id = ?
            """,
            (after, now, user_id, workflow_id, step_id),
        )
        updated = self._row(db, user_id, workflow_id, step_id)
        self._append(
            db,
            row=updated,
            before=before,
            after=after,
            reason=reason,
            actor=actor,
            evidence_ids=evidence_ids,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        return updated

    def start(
        self,
        *,
        user_id: str,
        workflow_id: str,
        step_id: str,
        parent_step_id: str | None = None,
        policy_version: str = POLICY_VERSION,
        risk_score: float = 0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        now = _iso()
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                """SELECT * FROM execution_control_states
                   WHERE user_id = ? AND workflow_id = ? AND step_id = ?""",
                (user_id, workflow_id, step_id),
            ).fetchone()
            if existing is not None:
                return dict(existing)
            db.execute(
                """
                INSERT INTO execution_control_states (
                    user_id, workflow_id, step_id, parent_step_id, state,
                    policy_version, risk_score, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'RECEIVED', ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    workflow_id,
                    step_id,
                    parent_step_id,
                    policy_version,
                    max(0.0, min(1.0, float(risk_score))),
                    _json(metadata or {}),
                    now,
                    now,
                ),
            )
            row = self._row(db, user_id, workflow_id, step_id)
            self._append(
                db,
                row=row,
                before=None,
                after="RECEIVED",
                reason="Authenticated execution request received.",
                actor="api",
            )
            row = self._transition(
                db,
                user_id=user_id,
                workflow_id=workflow_id,
                step_id=step_id,
                after="PLANNED",
                reason="Execution plan created.",
                actor="planner",
            )
            return dict(row)

    def record_verification(
        self,
        *,
        user_id: str,
        workflow_id: str,
        step_id: str,
        decision: str,
        reason: str,
        policy_version: str,
        risk_score: float,
        evidence_ids: Iterable[str] | None = None,
        auto_authorize: bool = False,
    ) -> dict[str, Any]:
        normalized = str(decision).upper()
        if normalized not in {"ALLOW", "RETRY", "REVIEW", "BLOCK"}:
            raise ValueError("Unsupported verification decision.")
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, user_id, workflow_id, step_id)
            if row["state"] == "RETRY":
                row = self._transition(
                    db,
                    user_id=user_id,
                    workflow_id=workflow_id,
                    step_id=step_id,
                    after="PLANNED",
                    reason="Verification retry started.",
                    actor="verification-engine",
                )
            if row["state"] != "PLANNED":
                if row["state"] == normalized or (
                    row["state"] == "AUTHORIZED" and normalized == "ALLOW"
                ):
                    return dict(row)
                raise InvalidTransition(
                    f"Verification requires PLANNED state, not {row['state']}."
                )
            db.execute(
                """
                UPDATE execution_control_states
                SET policy_version = ?, risk_score = ?, updated_at = ?
                WHERE user_id = ? AND workflow_id = ? AND step_id = ?
                """,
                (
                    policy_version or POLICY_VERSION,
                    max(0.0, min(1.0, float(risk_score))),
                    _iso(),
                    user_id,
                    workflow_id,
                    step_id,
                ),
            )
            for after, transition_reason in (
                ("EVIDENCE_REQUIRED", "Verification evidence contract selected."),
                ("VERIFYING", "Independent verification started."),
                (normalized, reason),
            ):
                row = self._transition(
                    db,
                    user_id=user_id,
                    workflow_id=workflow_id,
                    step_id=step_id,
                    after=after,
                    reason=transition_reason,
                    actor="verification-engine",
                    evidence_ids=evidence_ids,
                )
            if normalized == "ALLOW" and auto_authorize:
                row = self._transition(
                    db,
                    user_id=user_id,
                    workflow_id=workflow_id,
                    step_id=step_id,
                    after="AUTHORIZED",
                    reason="Verified low-risk action authorized by policy.",
                    actor="policy-engine",
                    evidence_ids=evidence_ids,
                )
            return dict(row)

    def authorize(
        self,
        *,
        user_id: str,
        workflow_id: str,
        step_id: str,
        actor: str = "human-reviewer",
        reason: str = "Explicit approval recorded.",
    ) -> dict[str, Any]:
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, user_id, workflow_id, step_id)
            if row["state"] == "AUTHORIZED":
                return dict(row)
            row = self._transition(
                db,
                user_id=user_id,
                workflow_id=workflow_id,
                step_id=step_id,
                after="AUTHORIZED",
                reason=reason,
                actor=actor,
            )
            return dict(row)

    def cancel(
        self,
        *,
        user_id: str,
        workflow_id: str,
        step_id: str,
        actor: str = "user",
        reason: str = "Execution cancelled.",
    ) -> dict[str, Any]:
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, user_id, workflow_id, step_id)
            if row["state"] == "CANCELLED":
                return dict(row)
            if row["state"] in {"COMPLETED", "BLOCK", "ESCALATED"}:
                raise InvalidTransition(
                    f"A {row['state']} execution cannot be cancelled."
                )
            db.execute(
                """
                UPDATE execution_control_states
                SET cancellation_epoch = cancellation_epoch + 1,
                    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE user_id = ? AND workflow_id = ? AND step_id = ?
                """,
                (_iso(), user_id, workflow_id, step_id),
            )
            row = self._transition(
                db,
                user_id=user_id,
                workflow_id=workflow_id,
                step_id=step_id,
                after="CANCELLED",
                reason=reason,
                actor=actor,
            )
            return dict(row)

    def begin_execution(
        self,
        *,
        user_id: str,
        workflow_id: str,
        step_id: str,
        idempotency_key: str,
        request: dict[str, Any],
        owner: str,
        lease_seconds: int = 120,
    ) -> ExecutionLease:
        request_fingerprint = _fingerprint(request)
        now = _now()
        expires = now + timedelta(seconds=max(5, int(lease_seconds)))
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                """
                SELECT * FROM execution_idempotency_keys
                WHERE user_id = ? AND idempotency_key = ?
                """,
                (user_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["request_fingerprint"] != request_fingerprint:
                    raise IdempotencyConflict(
                        "The idempotency key was already used for a different action."
                    )
                if existing["status"] == "completed":
                    return ExecutionLease(
                        workflow_id=workflow_id,
                        step_id=step_id,
                        owner=owner,
                        token="replay",
                        fencing_token=existing["fencing_token"],
                        cancellation_epoch=existing["cancellation_epoch"],
                        expires_at=_iso(now),
                        idempotency_key=idempotency_key,
                        replay=True,
                        response=_loads(existing["response_json"], {}),
                    )
                raise IdempotencyConflict("The action is already executing.")

            row = self._row(db, user_id, workflow_id, step_id)
            if row["state"] == "CANCELLED" or row["cancellation_epoch"] > 0:
                raise ExecutionCancelled("The execution was cancelled.")
            active_lease = (
                row["lease_token"]
                and row["lease_expires_at"]
                and row["lease_expires_at"] > _iso(now)
            )
            if active_lease:
                raise LeaseConflict("Another worker owns the execution lease.")
            if row["state"] != "AUTHORIZED":
                raise InvalidTransition(
                    f"Execution requires AUTHORIZED state, not {row['state']}."
                )
            fencing_token = int(row["fencing_token"]) + 1
            lease_token = f"lease_{uuid.uuid4().hex}"
            db.execute(
                """
                UPDATE execution_control_states
                SET lease_owner = ?, lease_token = ?, lease_expires_at = ?,
                    fencing_token = ?, updated_at = ?
                WHERE user_id = ? AND workflow_id = ? AND step_id = ?
                """,
                (
                    owner,
                    lease_token,
                    _iso(expires),
                    fencing_token,
                    _iso(now),
                    user_id,
                    workflow_id,
                    step_id,
                ),
            )
            db.execute(
                """
                INSERT INTO execution_idempotency_keys (
                    user_id, idempotency_key, workflow_id, step_id,
                    request_fingerprint, status, fencing_token,
                    cancellation_epoch, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (
                    user_id,
                    idempotency_key,
                    workflow_id,
                    step_id,
                    request_fingerprint,
                    fencing_token,
                    row["cancellation_epoch"],
                    _iso(now),
                    _iso(now),
                ),
            )
            for after, transition_reason in (
                ("EXECUTION_LEASED", "Durable execution lease acquired."),
                ("EXECUTING", "Authorized side effect started."),
            ):
                self._transition(
                    db,
                    user_id=user_id,
                    workflow_id=workflow_id,
                    step_id=step_id,
                    after=after,
                    reason=transition_reason,
                    actor=owner,
                    idempotency_key=idempotency_key,
                    payload={"fencing_token": fencing_token},
                )
            return ExecutionLease(
                workflow_id=workflow_id,
                step_id=step_id,
                owner=owner,
                token=lease_token,
                fencing_token=fencing_token,
                cancellation_epoch=row["cancellation_epoch"],
                expires_at=_iso(expires),
                idempotency_key=idempotency_key,
            )

    def _assert_lease(
        self,
        db: sqlite3.Connection,
        *,
        user_id: str,
        lease: ExecutionLease,
    ) -> sqlite3.Row:
        row = self._row(db, user_id, lease.workflow_id, lease.step_id)
        if (
            row["state"] == "CANCELLED"
            or row["cancellation_epoch"] != lease.cancellation_epoch
        ):
            raise ExecutionCancelled("Cancellation superseded this execution attempt.")
        if row["lease_token"] != lease.token or row["lease_owner"] != lease.owner:
            raise StaleFence("The execution lease is no longer owned by this worker.")
        if int(row["fencing_token"]) != int(lease.fencing_token):
            raise StaleFence("A newer worker fencing token superseded this execution.")
        return row

    def heartbeat_lease(
        self,
        *,
        user_id: str,
        lease: ExecutionLease,
        lease_seconds: int = 120,
    ) -> dict[str, Any]:
        expires = _now() + timedelta(seconds=max(5, int(lease_seconds)))
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._assert_lease(db, user_id=user_id, lease=lease)
            db.execute(
                """
                UPDATE execution_control_states SET lease_expires_at = ?, updated_at = ?
                WHERE user_id = ? AND workflow_id = ? AND step_id = ?
                """,
                (_iso(expires), _iso(), user_id, lease.workflow_id, lease.step_id),
            )
            return {"ok": True, "expires_at": _iso(expires)}

    def finalize_execution(
        self,
        *,
        user_id: str,
        lease: ExecutionLease,
        result: dict[str, Any],
        verified: bool,
        provider: str,
        provider_action_id: str | None = None,
        evidence_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._assert_lease(db, user_id=user_id, lease=lease)
            row = self._transition(
                db,
                user_id=user_id,
                workflow_id=lease.workflow_id,
                step_id=lease.step_id,
                after="POST_VERIFYING",
                reason="External action finished; post-condition verification started.",
                actor=lease.owner,
                evidence_ids=evidence_ids,
                idempotency_key=lease.idempotency_key,
            )
            after = "VERIFIED" if verified else "ESCALATED"
            row = self._transition(
                db,
                user_id=user_id,
                workflow_id=lease.workflow_id,
                step_id=lease.step_id,
                after=after,
                reason=(
                    "Observed result satisfied the post-condition contract."
                    if verified
                    else "Observed result did not satisfy the post-condition contract."
                ),
                actor="post-condition-verifier",
                evidence_ids=evidence_ids,
                idempotency_key=lease.idempotency_key,
            )
            if verified:
                row = self._transition(
                    db,
                    user_id=user_id,
                    workflow_id=lease.workflow_id,
                    step_id=lease.step_id,
                    after="COMPLETED",
                    reason="Execution and post-condition verification completed.",
                    actor="execution-control-plane",
                    evidence_ids=evidence_ids,
                    idempotency_key=lease.idempotency_key,
                )
            receipt_id = f"rcpt_{uuid.uuid4().hex}"
            request_row = db.execute(
                """SELECT request_fingerprint FROM execution_idempotency_keys
                   WHERE user_id = ? AND idempotency_key = ?""",
                (user_id, lease.idempotency_key),
            ).fetchone()
            db.execute(
                """
                INSERT INTO execution_action_receipts (
                    receipt_id, user_id, workflow_id, step_id, idempotency_key,
                    provider, provider_action_id, request_fingerprint,
                    result_fingerprint, observed_result_json, fencing_token, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    user_id,
                    lease.workflow_id,
                    lease.step_id,
                    lease.idempotency_key,
                    provider or "internal",
                    provider_action_id,
                    request_row["request_fingerprint"],
                    _fingerprint(result),
                    _json(result),
                    lease.fencing_token,
                    _iso(),
                ),
            )
            db.execute(
                """
                UPDATE execution_idempotency_keys
                SET status = ?, response_json = ?, updated_at = ?
                WHERE user_id = ? AND idempotency_key = ?
                """,
                (
                    "completed" if verified else "failed",
                    _json(result),
                    _iso(),
                    user_id,
                    lease.idempotency_key,
                ),
            )
            db.execute(
                """
                UPDATE execution_control_states
                SET lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE user_id = ? AND workflow_id = ? AND step_id = ?
                """,
                (_iso(), user_id, lease.workflow_id, lease.step_id),
            )
            return {"state": row["state"], "receipt_id": receipt_id}

    def fail_execution(
        self,
        *,
        user_id: str,
        lease: ExecutionLease,
        error: str,
    ) -> dict[str, Any]:
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._assert_lease(db, user_id=user_id, lease=lease)
            if row["state"] in {"EXECUTION_LEASED", "EXECUTING", "POST_VERIFYING"}:
                row = self._transition(
                    db,
                    user_id=user_id,
                    workflow_id=lease.workflow_id,
                    step_id=lease.step_id,
                    after="ESCALATED",
                    reason="Execution failed and requires operator review.",
                    actor=lease.owner,
                    idempotency_key=lease.idempotency_key,
                    payload={"error": str(error)[:1000]},
                )
            db.execute(
                """
                UPDATE execution_idempotency_keys
                SET status = 'failed', response_json = ?, updated_at = ?
                WHERE user_id = ? AND idempotency_key = ?
                """,
                (
                    _json({"ok": False, "error": str(error)[:1000]}),
                    _iso(),
                    user_id,
                    lease.idempotency_key,
                ),
            )
            db.execute(
                """
                UPDATE execution_control_states
                SET lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE user_id = ? AND workflow_id = ? AND step_id = ?
                """,
                (_iso(), user_id, lease.workflow_id, lease.step_id),
            )
            return {"state": row["state"]}

    def heartbeat_worker(
        self,
        *,
        worker_id: str,
        instance_id: str,
        active_leases: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _iso()
        with storage.connect() as db:
            db.execute(
                """
                INSERT INTO execution_worker_heartbeats (
                    worker_id, instance_id, active_leases, metadata_json,
                    heartbeat_at, started_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    instance_id = excluded.instance_id,
                    active_leases = excluded.active_leases,
                    metadata_json = excluded.metadata_json,
                    heartbeat_at = excluded.heartbeat_at
                """,
                (
                    worker_id,
                    instance_id,
                    max(0, active_leases),
                    _json(metadata or {}),
                    now,
                    now,
                ),
            )
        return {"ok": True, "worker_id": worker_id, "heartbeat_at": now}

    def stale_workers(self, *, stale_after_seconds: int = 90) -> list[dict[str, Any]]:
        cutoff = _iso(_now() - timedelta(seconds=max(1, stale_after_seconds)))
        with storage.connect() as db:
            rows = db.execute(
                """SELECT * FROM execution_worker_heartbeats
                   WHERE heartbeat_at < ? ORDER BY heartbeat_at""",
                (cutoff,),
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_outbox(
        self,
        *,
        worker_id: str,
        limit: int = 20,
        lease_seconds: int = 60,
    ) -> list[dict[str, Any]]:
        now = _now()
        token = f"joblease_{uuid.uuid4().hex}"
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """
                SELECT * FROM execution_outbox
                WHERE (status = 'pending' AND available_at <= ?)
                   OR (status = 'leased' AND lease_expires_at < ?)
                ORDER BY created_at
                LIMIT ?
                """,
                (_iso(now), _iso(now), max(1, min(200, int(limit)))),
            ).fetchall()
            claimed = []
            for row in rows:
                db.execute(
                    """
                    UPDATE execution_outbox
                    SET status = 'leased', attempts = attempts + 1,
                        lease_owner = ?, lease_token = ?, lease_expires_at = ?,
                        updated_at = ? WHERE event_id = ?
                    """,
                    (
                        worker_id,
                        token,
                        _iso(now + timedelta(seconds=max(5, lease_seconds))),
                        _iso(now),
                        row["event_id"],
                    ),
                )
                item = dict(row)
                item.update(
                    {
                        "lease_owner": worker_id,
                        "lease_token": token,
                        "attempts": row["attempts"] + 1,
                    }
                )
                item["payload"] = _loads(item.pop("payload_json"), {})
                claimed.append(item)
            return claimed

    def acknowledge_outbox(
        self, *, event_id: str, worker_id: str, lease_token: str
    ) -> bool:
        with storage.connect() as db:
            cursor = db.execute(
                """
                UPDATE execution_outbox
                SET status = 'delivered', lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE event_id = ? AND status = 'leased'
                  AND lease_owner = ? AND lease_token = ?
                """,
                (_iso(), event_id, worker_id, lease_token),
            )
            return cursor.rowcount == 1

    def reject_outbox(
        self,
        *,
        event_id: str,
        worker_id: str,
        lease_token: str,
        error: str,
        retry_delay_seconds: int = 5,
    ) -> str:
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT * FROM execution_outbox
                   WHERE event_id = ? AND status = 'leased'
                     AND lease_owner = ? AND lease_token = ?""",
                (event_id, worker_id, lease_token),
            ).fetchone()
            if row is None:
                raise LeaseConflict("The outbox job lease is no longer valid.")
            status = (
                "dead_letter" if row["attempts"] >= row["max_attempts"] else "pending"
            )
            db.execute(
                """
                UPDATE execution_outbox
                SET status = ?, available_at = ?, lease_owner = NULL,
                    lease_token = NULL, lease_expires_at = NULL,
                    last_error = ?, updated_at = ? WHERE event_id = ?
                """,
                (
                    status,
                    _iso(_now() + timedelta(seconds=max(0, retry_delay_seconds))),
                    str(error)[:1000],
                    _iso(),
                    event_id,
                ),
            )
            return status

    def snapshot(
        self, *, user_id: str, workflow_id: str, step_id: str
    ) -> dict[str, Any]:
        with storage.connect() as db:
            state = dict(self._row(db, user_id, workflow_id, step_id))
            state["metadata"] = _loads(state.pop("metadata_json"), {})
            ledger_rows = db.execute(
                """
                SELECT * FROM execution_ledger
                WHERE user_id = ? AND workflow_id = ? AND step_id = ?
                ORDER BY sequence
                """,
                (user_id, workflow_id, step_id),
            ).fetchall()
            receipt_rows = db.execute(
                """
                SELECT * FROM execution_action_receipts
                WHERE user_id = ? AND workflow_id = ? AND step_id = ?
                ORDER BY created_at
                """,
                (user_id, workflow_id, step_id),
            ).fetchall()
        ledger = []
        for item in ledger_rows:
            record = dict(item)
            record["evidence_ids"] = _loads(record.pop("evidence_ids_json"), [])
            record["payload"] = _loads(record.pop("payload_json"), {})
            ledger.append(record)
        receipts = []
        for item in receipt_rows:
            record = dict(item)
            record["observed_result"] = _loads(record.pop("observed_result_json"), {})
            receipts.append(record)
        return {
            "backend": self.backend,
            "state": state,
            "ledger": ledger,
            "receipts": receipts,
        }


class SupabaseExecutionControlPlane:
    """Supabase RPC adapter; every state mutation is one PostgreSQL transaction."""

    backend = "supabase"

    def __init__(self, client: Any) -> None:
        if client is None:
            raise ControlPlaneError("Supabase execution control is not configured.")
        self.client = client

    def _rpc(self, name: str, params: dict[str, Any]) -> Any:
        try:
            response = self.client.rpc(name, params).execute()
        except Exception as error:
            message = str(error)
            lowered = message.lower()
            if "idempotency" in lowered or "already executing" in lowered:
                raise IdempotencyConflict(message) from error
            if "cancel" in lowered:
                raise ExecutionCancelled(message) from error
            if "lease" in lowered or "fencing" in lowered:
                raise StaleFence(message) from error
            if "transition" in lowered or "requires" in lowered:
                raise InvalidTransition(message) from error
            raise ControlPlaneError(
                f"Supabase execution control failed: {message}"
            ) from error
        data = response.data
        if isinstance(data, list) and len(data) == 1:
            return data[0]
        return data

    def start(
        self,
        *,
        user_id: str,
        workflow_id: str,
        step_id: str,
        parent_step_id: str | None = None,
        policy_version: str = POLICY_VERSION,
        risk_score: float = 0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._rpc(
            "software_execution_start",
            {
                "p_user_id": user_id,
                "p_workflow_id": workflow_id,
                "p_step_id": step_id,
                "p_parent_step_id": parent_step_id,
                "p_policy_version": policy_version,
                "p_risk_score": max(0.0, min(1.0, float(risk_score))),
                "p_metadata": metadata or {},
            },
        )

    def record_verification(
        self,
        *,
        user_id: str,
        workflow_id: str,
        step_id: str,
        decision: str,
        reason: str,
        policy_version: str,
        risk_score: float,
        evidence_ids: Iterable[str] | None = None,
        auto_authorize: bool = False,
    ) -> dict[str, Any]:
        return self._rpc(
            "software_execution_verify",
            {
                "p_user_id": user_id,
                "p_workflow_id": workflow_id,
                "p_step_id": step_id,
                "p_decision": str(decision).upper(),
                "p_reason": reason,
                "p_policy_version": policy_version,
                "p_risk_score": max(0.0, min(1.0, float(risk_score))),
                "p_evidence_ids": list(evidence_ids or []),
                "p_auto_authorize": bool(auto_authorize),
            },
        )

    def authorize(
        self,
        *,
        user_id: str,
        workflow_id: str,
        step_id: str,
        actor: str = "human-reviewer",
        reason: str = "Explicit approval recorded.",
    ) -> dict[str, Any]:
        return self._rpc(
            "software_execution_authorize",
            {
                "p_user_id": user_id,
                "p_workflow_id": workflow_id,
                "p_step_id": step_id,
                "p_actor": actor,
                "p_reason": reason,
            },
        )

    def cancel(
        self,
        *,
        user_id: str,
        workflow_id: str,
        step_id: str,
        actor: str = "user",
        reason: str = "Execution cancelled.",
    ) -> dict[str, Any]:
        return self._rpc(
            "software_execution_cancel",
            {
                "p_user_id": user_id,
                "p_workflow_id": workflow_id,
                "p_step_id": step_id,
                "p_actor": actor,
                "p_reason": reason,
            },
        )

    def begin_execution(
        self,
        *,
        user_id: str,
        workflow_id: str,
        step_id: str,
        idempotency_key: str,
        request: dict[str, Any],
        owner: str,
        lease_seconds: int = 120,
    ) -> ExecutionLease:
        result = self._rpc(
            "software_execution_begin",
            {
                "p_user_id": user_id,
                "p_workflow_id": workflow_id,
                "p_step_id": step_id,
                "p_idempotency_key": idempotency_key,
                "p_request_fingerprint": _fingerprint(request),
                "p_owner": owner,
                "p_lease_seconds": max(5, int(lease_seconds)),
            },
        )
        return ExecutionLease(
            workflow_id=result["workflow_id"],
            step_id=result["step_id"],
            owner=result["owner"],
            token=result["token"],
            fencing_token=int(result["fencing_token"]),
            cancellation_epoch=int(result["cancellation_epoch"]),
            expires_at=str(result["expires_at"]),
            idempotency_key=result["idempotency_key"],
            replay=bool(result.get("replay")),
            response=result.get("response"),
        )

    def finalize_execution(
        self,
        *,
        user_id: str,
        lease: ExecutionLease,
        result: dict[str, Any],
        verified: bool,
        provider: str,
        provider_action_id: str | None = None,
        evidence_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        return self._rpc(
            "software_execution_finalize",
            {
                "p_user_id": user_id,
                "p_workflow_id": lease.workflow_id,
                "p_step_id": lease.step_id,
                "p_owner": lease.owner,
                "p_lease_token": lease.token,
                "p_fencing_token": lease.fencing_token,
                "p_cancellation_epoch": lease.cancellation_epoch,
                "p_idempotency_key": lease.idempotency_key,
                "p_result": result,
                "p_result_fingerprint": _fingerprint(result),
                "p_verified": bool(verified),
                "p_provider": provider or "internal",
                "p_provider_action_id": provider_action_id,
                "p_evidence_ids": list(evidence_ids or []),
            },
        )

    def fail_execution(
        self,
        *,
        user_id: str,
        lease: ExecutionLease,
        error: str,
    ) -> dict[str, Any]:
        return self._rpc(
            "software_execution_fail",
            {
                "p_user_id": user_id,
                "p_workflow_id": lease.workflow_id,
                "p_step_id": lease.step_id,
                "p_owner": lease.owner,
                "p_lease_token": lease.token,
                "p_fencing_token": lease.fencing_token,
                "p_cancellation_epoch": lease.cancellation_epoch,
                "p_idempotency_key": lease.idempotency_key,
                "p_error": str(error)[:1000],
            },
        )

    def heartbeat_worker(
        self,
        *,
        worker_id: str,
        instance_id: str,
        active_leases: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._rpc(
            "software_execution_worker_heartbeat",
            {
                "p_worker_id": worker_id,
                "p_instance_id": instance_id,
                "p_active_leases": max(0, int(active_leases)),
                "p_metadata": metadata or {},
            },
        )

    def stale_workers(self, *, stale_after_seconds: int = 90) -> list[dict[str, Any]]:
        result = self._rpc(
            "software_execution_stale_workers",
            {"p_stale_after_seconds": max(1, int(stale_after_seconds))},
        )
        return list(result or [])

    def claim_outbox(
        self,
        *,
        worker_id: str,
        limit: int = 20,
        lease_seconds: int = 60,
    ) -> list[dict[str, Any]]:
        result = self._rpc(
            "software_execution_claim_outbox",
            {
                "p_worker_id": worker_id,
                "p_limit": max(1, min(200, int(limit))),
                "p_lease_seconds": max(5, int(lease_seconds)),
            },
        )
        return list(result or [])

    def acknowledge_outbox(
        self, *, event_id: str, worker_id: str, lease_token: str
    ) -> bool:
        return bool(
            self._rpc(
                "software_execution_ack_outbox",
                {
                    "p_event_id": event_id,
                    "p_worker_id": worker_id,
                    "p_lease_token": lease_token,
                },
            )
        )

    def reject_outbox(
        self,
        *,
        event_id: str,
        worker_id: str,
        lease_token: str,
        error: str,
        retry_delay_seconds: int = 5,
    ) -> str:
        return str(
            self._rpc(
                "software_execution_reject_outbox",
                {
                    "p_event_id": event_id,
                    "p_worker_id": worker_id,
                    "p_lease_token": lease_token,
                    "p_error": str(error)[:1000],
                    "p_retry_delay_seconds": max(0, int(retry_delay_seconds)),
                },
            )
        )

    def snapshot(
        self, *, user_id: str, workflow_id: str, step_id: str
    ) -> dict[str, Any]:
        return self._rpc(
            "software_execution_snapshot",
            {
                "p_user_id": user_id,
                "p_workflow_id": workflow_id,
                "p_step_id": step_id,
            },
        )


def create_execution_control_plane() -> Any:
    backend = os.getenv("SOFTWARE_EXECUTION_CONTROL_BACKEND", "auto").strip().lower()
    supabase_ready = os.getenv(
        "SOFTWARE_EXECUTION_CONTROL_SUPABASE_READY", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    if backend == "supabase" or (backend == "auto" and supabase_ready):
        try:
            from supabase_client import get_supabase_client
        except ImportError:
            try:
                from ..supabase_client import get_supabase_client
            except ImportError as error:
                raise ControlPlaneError(
                    "Supabase client module is unavailable."
                ) from error
        return SupabaseExecutionControlPlane(get_supabase_client())
    if backend not in {"auto", "sqlite"}:
        raise ControlPlaneError(
            "SOFTWARE_EXECUTION_CONTROL_BACKEND must be auto, sqlite, or supabase."
        )
    return SQLiteExecutionControlPlane()


__all__ = [
    "ALLOWED_TRANSITIONS",
    "POLICY_VERSION",
    "ControlPlaneError",
    "ExecutionCancelled",
    "ExecutionLease",
    "IdempotencyConflict",
    "InvalidTransition",
    "LeaseConflict",
    "SQLiteExecutionControlPlane",
    "StaleFence",
    "SupabaseExecutionControlPlane",
    "create_execution_control_plane",
]
