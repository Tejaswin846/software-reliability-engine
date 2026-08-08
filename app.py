from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
import hashlib
import hmac
import random
import secrets
from collections import Counter, defaultdict
from datetime import datetime, timezone
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import bcrypt
import jwt
import requests
from jwt import PyJWKClient
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field
import sentry_sdk

try:
    from .reliability_scoring import build_metrics_from_summary
except ImportError:
    from reliability_scoring import build_metrics_from_summary

try:
    from .reliability_database import (
        connect as reliability_connect,
        get_guardrail_stats as get_reliability_guardrail_stats,
        init_db as init_reliability_db,
    )
except ImportError:
    from reliability_database import (
        connect as reliability_connect,
        get_guardrail_stats as get_reliability_guardrail_stats,
        init_db as init_reliability_db,
    )

try:
    from .supabase_client import (
        create_chat as supabase_create_chat,
        get_chat_history as supabase_get_chat_history,
        save_benchmark_run as supabase_save_benchmark_run,
        save_message as supabase_save_message,
        supabase_health_check,
        upsert_user_profile as supabase_upsert_user_profile,
    )
except ImportError:
    from supabase_client import (
        create_chat as supabase_create_chat,
        get_chat_history as supabase_get_chat_history,
        save_benchmark_run as supabase_save_benchmark_run,
        save_message as supabase_save_message,
        supabase_health_check,
        upsert_user_profile as supabase_upsert_user_profile,
    )

try:
    from .memory import (
        get_recent_memories as qdrant_get_recent_memories,
        memory_health_check,
        save_memory as qdrant_save_memory,
        search_memory as qdrant_search_memory,
    )
except ImportError:
    from memory import (
        get_recent_memories as qdrant_get_recent_memories,
        memory_health_check,
        save_memory as qdrant_save_memory,
        search_memory as qdrant_search_memory,
    )

try:
    from .sentry_monitoring import (
        capture_operational_error,
        initialize_sentry,
        redact_text,
        sentry_health_check,
        set_monitoring_context,
        scrub_sensitive_data,
    )
except ImportError:
    from sentry_monitoring import (
        capture_operational_error,
        initialize_sentry,
        redact_text,
        sentry_health_check,
        set_monitoring_context,
        scrub_sensitive_data,
    )

try:
    from .integrations.composio_service import (
        composio_health_check,
        execute_tool as execute_composio_tool,
        get_user_tool_context as get_composio_tool_context,
        initialize_composio,
        list_integrations as list_composio_integrations,
        refresh_tools as refresh_composio_tools,
        tool_descriptors as composio_tool_descriptors,
    )
except ImportError:
    from integrations.composio_service import (
        composio_health_check,
        execute_tool as execute_composio_tool,
        get_user_tool_context as get_composio_tool_context,
        initialize_composio,
        list_integrations as list_composio_integrations,
        refresh_tools as refresh_composio_tools,
        tool_descriptors as composio_tool_descriptors,
    )

try:
    from .integrations.routes import create_integrations_router
except ImportError:
    from integrations.routes import create_integrations_router

try:
    from .redis_client import (
        cache_ai_response as redis_cache_ai_response,
        check_rate_limit as redis_check_rate_limit,
        delete_session_cache as redis_delete_session_cache,
        distributed_lock as redis_distributed_lock,
        enqueue_background_job as redis_enqueue_background_job,
        get_execution_state as redis_get_execution_state,
        get_cached_ai_response as redis_get_cached_ai_response,
        get_conversation_state as redis_get_conversation_state,
        get_session_cache as redis_get_session_cache,
        initialize_redis,
        redis_health_check,
        set_execution_state as redis_set_execution_state,
        set_conversation_state as redis_set_conversation_state,
        set_session_cache as redis_set_session_cache,
    )
except ImportError:
    from redis_client import (
        cache_ai_response as redis_cache_ai_response,
        check_rate_limit as redis_check_rate_limit,
        delete_session_cache as redis_delete_session_cache,
        distributed_lock as redis_distributed_lock,
        enqueue_background_job as redis_enqueue_background_job,
        get_execution_state as redis_get_execution_state,
        get_cached_ai_response as redis_get_cached_ai_response,
        get_conversation_state as redis_get_conversation_state,
        get_session_cache as redis_get_session_cache,
        initialize_redis,
        redis_health_check,
        set_execution_state as redis_set_execution_state,
        set_conversation_state as redis_set_conversation_state,
        set_session_cache as redis_set_session_cache,
    )

try:
    from .ai_execution import AIExecutionService, create_ai_execution_router
except ImportError:
    from ai_execution import AIExecutionService, create_ai_execution_router


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
APP_NAME = os.getenv("SOFTWARE_APP_NAME", "Software Reliability Engine")
APP_VERSION = os.getenv("SOFTWARE_VERSION", "0.2.0")
ENVIRONMENT = os.getenv("SOFTWARE_ENV", "development").lower()
ROOT_PATH = os.getenv("SOFTWARE_ROOT_PATH", "")
JWT_SECRET = os.getenv("SOFTWARE_JWT_SECRET") or os.getenv("JWT_SECRET") or "software-local-development-secret-change-me"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("SOFTWARE_JWT_EXPIRE_MINUTES", "1440"))
SESSION_COOKIE_NAME = os.getenv("SOFTWARE_SESSION_COOKIE", "software_session")
SESSION_COOKIE_SECURE = ENVIRONMENT == "production"
CLERK_PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY", "").strip()
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "").strip()
CLERK_JWT_ISSUER = os.getenv("CLERK_JWT_ISSUER", "").strip().rstrip("/")
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "").strip() or (
    f"{CLERK_JWT_ISSUER}/.well-known/jwks.json" if CLERK_JWT_ISSUER else ""
)
CLERK_AUTH_REQUIRED = os.getenv("SOFTWARE_CLERK_AUTH_REQUIRED", os.getenv("NEXORA_CLERK_AUTH_REQUIRED", "true")).lower() not in {"0", "false", "no", "off"}
CLERK_AUTH_TIMEOUT = float(os.getenv("CLERK_AUTH_TIMEOUT", "10"))
CLERK_JWK_CLIENT = PyJWKClient(CLERK_JWKS_URL) if CLERK_JWKS_URL else None
STATIC_SDK_API_KEYS = [
    key.strip()
    for key in os.getenv("SOFTWARE_SDK_API_KEYS", "").split(",")
    if key.strip()
]
BOOTSTRAP_DEV_KEY = os.getenv("SOFTWARE_BOOTSTRAP_SDK_KEY") or (STATIC_SDK_API_KEYS[0] if STATIC_SDK_API_KEYS else "dev-key")
DEFAULT_BOOTSTRAP_ENABLED = "true" if ENVIRONMENT != "production" or STATIC_SDK_API_KEYS else "false"
ENABLE_BOOTSTRAP_DEV_KEY = os.getenv("SOFTWARE_ENABLE_BOOTSTRAP_DEV_KEY", DEFAULT_BOOTSTRAP_ENABLED).lower() == "true"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("SOFTWARE_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
PUBLIC_BASE_URL = (
    os.getenv("SOFTWARE_PUBLIC_URL")
    or os.getenv("PUBLIC_BASE_URL")
    or os.getenv("RENDER_EXTERNAL_URL")
    or ""
).strip().rstrip("/")
CLARITY_PROJECT_ID = os.getenv("CLARITY_PROJECT_ID", "xc0zbrjy3z").strip()
PRODUCTION_PRIMARY_HOST = os.getenv("SOFTWARE_PRIMARY_HOST", "").strip().lower()
PRODUCTION_HOSTS = {
    host.strip().lower()
    for host in os.getenv("SOFTWARE_PRODUCTION_HOSTS", "").split(",")
    if host.strip()
}
PRODUCTION_REDIRECT_HOSTS = {
    host.strip().lower()
    for host in os.getenv("SOFTWARE_REDIRECT_HOSTS", "").split(",")
    if host.strip()
}
FORCE_HTTPS = os.getenv("SOFTWARE_FORCE_HTTPS", "false").lower() == "true"
REDIRECT_WWW = os.getenv("SOFTWARE_REDIRECT_WWW", "true").lower() == "true"
API_RATE_LIMIT_REQUESTS = int(os.getenv("SOFTWARE_API_RATE_LIMIT_REQUESTS", "300"))
API_RATE_LIMIT_WINDOW_SECONDS = int(
    os.getenv("SOFTWARE_API_RATE_LIMIT_WINDOW_SECONDS", "60")
)
DB_PATH = Path(os.getenv("SOFTWARE_API_DB_PATH", DATA_DIR / "software_reliability.db")).expanduser()
SERVICE_STARTED_AT = datetime.now(timezone.utc)
STARTUP_CHECKS: Dict[str, Any] = {}
LOGGER = logging.getLogger("software.app")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRO_PRICE_ID = os.getenv("STRIPE_PRO_PRICE_ID", "")
STRIPE_ENTERPRISE_PRICE_ID = os.getenv("STRIPE_ENTERPRISE_PRICE_ID", "")
STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "")
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "")
STRIPE_PORTAL_RETURN_URL = os.getenv("STRIPE_PORTAL_RETURN_URL", "")
ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.getenv("SOFTWARE_ADMIN_EMAILS", "dev@software.local").split(",")
    if email.strip()
}
ORG_ROLES = {"owner", "admin", "developer", "viewer"}
ORG_ROLE_RANK = {
    "viewer": 1,
    "developer": 2,
    "admin": 3,
    "owner": 4,
}
PLAN_DEFINITIONS = [
    {
        "id": "free",
        "name": "Free",
        "max_projects": 1,
        "max_api_keys": 1,
        "monthly_workflow_limit": 1000,
        "metadata": {"price": "$0", "audience": "Individual developers", "stripe_price_id": None},
    },
    {
        "id": "pro",
        "name": "Pro",
        "max_projects": 20,
        "max_api_keys": 50,
        "monthly_workflow_limit": 100000,
        "metadata": {"price": "Stripe", "audience": "Teams", "stripe_price_id": STRIPE_PRO_PRICE_ID or None},
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "max_projects": None,
        "max_api_keys": None,
        "monthly_workflow_limit": None,
        "metadata": {"price": "Custom", "audience": "Large organizations", "stripe_price_id": STRIPE_ENTERPRISE_PRICE_ID or None},
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def verify_api_key_hash(api_key: str, key_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(api_key), key_hash)


def generate_api_key() -> Dict[str, str]:
    raw_key = f"sw_{secrets.token_urlsafe(32)}"
    return {
        "api_key": raw_key,
        "key_hash": hash_api_key(raw_key),
        "key_prefix": raw_key[:14],
    }


def ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def bootstrap_dev_identity(db: sqlite3.Connection) -> None:
    if not ENABLE_BOOTSTRAP_DEV_KEY or not BOOTSTRAP_DEV_KEY:
        return
    user_id = "usr_dev_local"
    project_id = "prj_dev_local"
    api_key_id = "key_dev_local"
    created_at = now_iso()
    email = os.getenv("SOFTWARE_DEV_EMAIL", "dev@software.local").lower()
    password = os.getenv("SOFTWARE_DEV_PASSWORD", "development-password")
    project_name = os.getenv("SOFTWARE_DEV_PROJECT_NAME", "Default Development Project")
    if not db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
        db.execute(
            """
            INSERT INTO users (id, email, password_hash, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, email, hash_password(password), created_at),
        )
    if not db.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
        db.execute(
            """
            INSERT INTO projects (id, user_id, name, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, user_id, project_name, created_at),
        )
    bootstrap_keys: List[str] = []
    for key in [BOOTSTRAP_DEV_KEY, *STATIC_SDK_API_KEYS]:
        if key and key not in bootstrap_keys:
            bootstrap_keys.append(key)

    for index, api_key in enumerate(bootstrap_keys):
        key_hash = hash_api_key(api_key)
        if db.execute("SELECT 1 FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone():
            continue
        current_api_key_id = api_key_id if index == 0 and not db.execute("SELECT 1 FROM api_keys WHERE id = ?", (api_key_id,)).fetchone() else f"key_static_{key_hash[:16]}"
        db.execute(
            """
            INSERT INTO api_keys (
                id, user_id, project_id, key_hash, key_prefix,
                created_at, last_used_at, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, 1)
            """,
            (
                current_api_key_id,
                user_id,
                project_id,
                key_hash,
                api_key[:14],
                created_at,
            ),
        )
        record_analytics_event(
            db,
            "api_key_generated",
            user_id=user_id,
            project_id=project_id,
            email=email,
            metadata={"key_id": current_api_key_id, "key_prefix": api_key[:14], "source": "bootstrap"},
        )


def month_period(now: Optional[datetime] = None) -> tuple[str, str]:
    current = now or datetime.now(timezone.utc)
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.isoformat(), end.isoformat()


def seed_plans(db: sqlite3.Connection) -> None:
    created_at = now_iso()
    for plan in PLAN_DEFINITIONS:
        db.execute(
            """
            INSERT INTO plans (
                id, name, max_projects, max_api_keys, monthly_workflow_limit,
                created_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                max_projects = excluded.max_projects,
                max_api_keys = excluded.max_api_keys,
                monthly_workflow_limit = excluded.monthly_workflow_limit,
                metadata_json = excluded.metadata_json
            """,
            (
                plan["id"],
                plan["name"],
                plan["max_projects"],
                plan["max_api_keys"],
                plan["monthly_workflow_limit"],
                created_at,
                json.dumps(plan["metadata"], sort_keys=True),
            ),
        )


def ensure_default_subscriptions(db: sqlite3.Connection) -> None:
    period_start, period_end = month_period()
    rows = db.execute("SELECT id FROM users").fetchall()
    for row in rows:
        existing = db.execute(
            "SELECT 1 FROM subscriptions WHERE user_id = ? AND status = 'active'",
            (row["id"],),
        ).fetchone()
        if existing:
            continue
        created_at = now_iso()
        db.execute(
            """
            INSERT INTO subscriptions (
                id, user_id, plan_id, status, current_period_start,
                current_period_end, created_at, updated_at, metadata_json
            )
            VALUES (?, ?, 'free', 'active', ?, ?, ?, ?, '{}')
            """,
            (f"sub_{uuid.uuid4().hex}", row["id"], period_start, period_end, created_at, created_at),
        )


def get_active_subscription(db: sqlite3.Connection, user_id: str) -> sqlite3.Row:
    row = db.execute(
        """
        SELECT subscriptions.*, plans.name AS plan_name,
               plans.max_projects, plans.max_api_keys, plans.monthly_workflow_limit,
               plans.metadata_json AS plan_metadata_json
        FROM subscriptions
        JOIN plans ON plans.id = subscriptions.plan_id
        WHERE subscriptions.user_id = ? AND subscriptions.status = 'active'
        ORDER BY subscriptions.created_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if row:
        try:
            period_end = datetime.fromisoformat(row["current_period_end"])
        except ValueError:
            period_end = datetime.now(timezone.utc)
        if datetime.now(timezone.utc) >= period_end:
            period_start, new_period_end = month_period()
            updated_at = now_iso()
            db.execute(
                """
                UPDATE subscriptions
                SET current_period_start = ?, current_period_end = ?, updated_at = ?
                WHERE id = ?
                """,
                (period_start, new_period_end, updated_at, row["id"]),
            )
            row = db.execute(
                """
                SELECT subscriptions.*, plans.name AS plan_name,
                       plans.max_projects, plans.max_api_keys, plans.monthly_workflow_limit,
                       plans.metadata_json AS plan_metadata_json
                FROM subscriptions
                JOIN plans ON plans.id = subscriptions.plan_id
                WHERE subscriptions.id = ?
                """,
                (row["id"],),
            ).fetchone()
        return row
    ensure_default_subscriptions(db)
    row = db.execute(
        """
        SELECT subscriptions.*, plans.name AS plan_name,
               plans.max_projects, plans.max_api_keys, plans.monthly_workflow_limit,
               plans.metadata_json AS plan_metadata_json
        FROM subscriptions
        JOIN plans ON plans.id = subscriptions.plan_id
        WHERE subscriptions.user_id = ? AND subscriptions.status = 'active'
        ORDER BY subscriptions.created_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="Unable to create default subscription.")
    return row


def record_usage(
    db: sqlite3.Connection,
    user_id: str,
    metric_type: str,
    *,
    project_id: Optional[str] = None,
    api_key_id: Optional[str] = None,
    quantity: int = 1,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    db.execute(
        """
        INSERT INTO usage_records (
            id, user_id, project_id, api_key_id, metric_type,
            quantity, created_at, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"use_{uuid.uuid4().hex}",
            user_id,
            project_id,
            api_key_id,
            metric_type,
            quantity,
            now_iso(),
            json.dumps(metadata or {}, sort_keys=True),
        ),
    )


def record_analytics_event(
    db: sqlite3.Connection,
    event_type: str,
    *,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    email: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    db.execute(
        """
        INSERT INTO analytics_events (
            id, event_type, user_id, project_id, email, created_at, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"evt_analytics_{uuid.uuid4().hex}",
            event_type,
            user_id,
            project_id,
            email,
            now_iso(),
            json.dumps(metadata or {}, sort_keys=True),
        ),
    )


def customer_validation_summary(db: sqlite3.Connection) -> Dict[str, Any]:
    event_rows = db.execute(
        """
        SELECT event_type, COUNT(*) AS count
        FROM analytics_events
        GROUP BY event_type
        ORDER BY count DESC, event_type ASC
        """
    ).fetchall()
    request_rows = db.execute(
        """
        SELECT id, name, email, company, role, use_case,
               expected_workflows_per_month, timeline, status, created_at
        FROM request_access_requests
        ORDER BY created_at DESC
        LIMIT 25
        """
    ).fetchall()
    totals = {
        "signups": int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0]),
        "project_creations": int(db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]),
        "api_key_generations": int(db.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]),
        "sdk_installations": int(
            db.execute(
                "SELECT COUNT(*) FROM analytics_events WHERE event_type = 'sdk_installation'"
            ).fetchone()[0]
        ),
        "request_access_submissions": int(
            db.execute("SELECT COUNT(*) FROM request_access_requests").fetchone()[0]
        ),
    }
    conversion = {
        "signup_to_project_rate": round(totals["project_creations"] / totals["signups"] * 100, 2)
        if totals["signups"]
        else 0.0,
        "project_to_api_key_rate": round(
            totals["api_key_generations"] / totals["project_creations"] * 100, 2
        )
        if totals["project_creations"]
        else 0.0,
    }
    return {
        "totals": totals,
        "conversion": conversion,
        "events": [row_to_dict(row) for row in event_rows],
        "recent_request_access": [row_to_dict(row) for row in request_rows],
    }


def usage_totals(db: sqlite3.Connection, user_id: str, period_start: str, period_end: str) -> Dict[str, int]:
    rows = db.execute(
        """
        SELECT metric_type, COALESCE(SUM(quantity), 0) AS total
        FROM usage_records
        WHERE user_id = ? AND created_at >= ? AND created_at < ?
        GROUP BY metric_type
        """,
        (user_id, period_start, period_end),
    ).fetchall()
    totals = {row["metric_type"]: int(row["total"] or 0) for row in rows}
    return {
        "workflows": totals.get("workflow", 0),
        "model_calls": totals.get("model_call", 0),
        "tool_calls": totals.get("tool_call", 0),
        "api_requests": totals.get("api_request", 0),
    }


def billing_summary(db: sqlite3.Connection, user_id: str) -> Dict[str, Any]:
    subscription = get_active_subscription(db, user_id)
    user_row = db.execute("SELECT stripe_customer_id FROM users WHERE id = ?", (user_id,)).fetchone()
    period_start = subscription["current_period_start"]
    period_end = subscription["current_period_end"]
    totals = usage_totals(db, user_id, period_start, period_end)
    project_count = int(db.execute("SELECT COUNT(*) FROM projects WHERE user_id = ?", (user_id,)).fetchone()[0])
    active_api_key_count = int(
        db.execute(
            "SELECT COUNT(*) FROM api_keys WHERE user_id = ? AND is_active = 1",
            (user_id,),
        ).fetchone()[0]
    )
    workflow_limit = subscription["monthly_workflow_limit"]
    max_projects = subscription["max_projects"]
    max_api_keys = subscription["max_api_keys"]

    def remaining(limit: Optional[int], used: int) -> Optional[int]:
        if limit is None:
            return None
        return max(0, int(limit) - used)

    return {
        "plan": {
            "id": subscription["plan_id"],
            "name": subscription["plan_name"],
            "max_projects": max_projects,
            "max_api_keys": max_api_keys,
            "monthly_workflow_limit": workflow_limit,
            "metadata": json.loads(subscription["plan_metadata_json"] or "{}"),
        },
        "subscription": {
            "id": subscription["id"],
            "status": subscription["status"],
            "stripe_subscription_id": subscription["stripe_subscription_id"],
            "stripe_price_id": subscription["stripe_price_id"],
            "stripe_status": subscription["stripe_status"],
            "current_period_start": period_start,
            "current_period_end": period_end,
        },
        "stripe": {
            "configured": bool(STRIPE_SECRET_KEY),
            "customer_id": user_row["stripe_customer_id"] if user_row else None,
            "subscription_id": subscription["stripe_subscription_id"],
            "price_id": subscription["stripe_price_id"],
            "status": subscription["stripe_status"],
        },
        "invoices": billing_invoice_rows(db, user_id),
        "usage": {
            **totals,
            "projects": project_count,
            "api_keys": active_api_key_count,
        },
        "remaining": {
            "projects": remaining(max_projects, project_count),
            "api_keys": remaining(max_api_keys, active_api_key_count),
            "workflows": remaining(workflow_limit, totals["workflows"]),
        },
    }


def enforce_limit(
    db: sqlite3.Connection,
    user_id: str,
    resource: str,
    requested_increment: int = 1,
) -> None:
    summary = billing_summary(db, user_id)
    plan = summary["plan"]
    usage = summary["usage"]
    if resource == "projects":
        limit = plan["max_projects"]
        used = usage["projects"]
    elif resource == "api_keys":
        limit = plan["max_api_keys"]
        used = usage["api_keys"]
    elif resource == "workflows":
        limit = plan["monthly_workflow_limit"]
        used = usage["workflows"]
    else:
        raise ValueError(f"Unknown limited resource: {resource}")
    if limit is not None and used + requested_increment > int(limit):
        raise HTTPException(
            status_code=402,
            detail=(
                f"{plan['name']} plan limit exceeded for {resource}. "
                "Upgrade your plan or wait for the next billing period."
            ),
        )


def stripe_module():
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe is not configured.")
    try:
        import stripe  # type: ignore
    except ImportError as error:
        raise HTTPException(status_code=503, detail="Stripe package is not installed.") from error
    stripe.api_key = STRIPE_SECRET_KEY
    return stripe


def stripe_price_id_for_plan(plan_id: str) -> Optional[str]:
    normalized = plan_id.strip().lower()
    if normalized == "pro":
        return STRIPE_PRO_PRICE_ID or None
    if normalized == "enterprise":
        return STRIPE_ENTERPRISE_PRICE_ID or None
    return None


def plan_id_from_stripe_price(price_id: Optional[str]) -> str:
    if price_id and STRIPE_PRO_PRICE_ID and price_id == STRIPE_PRO_PRICE_ID:
        return "pro"
    if price_id and STRIPE_ENTERPRISE_PRICE_ID and price_id == STRIPE_ENTERPRISE_PRICE_ID:
        return "enterprise"
    return "free"


def stripe_get(payload: Any, key: str, default: Any = None) -> Any:
    if payload is None:
        return default
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def stripe_nested(payload: Any, *keys: str, default: Any = None) -> Any:
    current = payload
    for key in keys:
        current = stripe_get(current, key, None)
        if current is None:
            return default
    return current


def stripe_epoch_to_iso(value: Any, fallback: Optional[str] = None) -> str:
    if value is None:
        return fallback or now_iso()
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return fallback or now_iso()


def public_base_url(request: Request) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    return str(request.base_url).rstrip("/")


def normalized_host(host_header: str) -> str:
    host = (host_header or "").split(",")[0].strip().lower()
    if host.startswith("["):
        closing = host.find("]")
        return host[: closing + 1] if closing >= 0 else host
    return host.split(":", 1)[0]


def forwarded_scheme(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip().lower() or request.url.scheme


def domain_redirect_target(request: Request) -> Optional[str]:
    if ENVIRONMENT != "production":
        return None
    host = normalized_host(request.headers.get("host", ""))
    if not host:
        return None

    target_host: Optional[str] = None
    if host in PRODUCTION_REDIRECT_HOSTS and PRODUCTION_PRIMARY_HOST:
        target_host = PRODUCTION_PRIMARY_HOST
    elif REDIRECT_WWW and host.startswith("www."):
        stripped_host = host[4:]
        if stripped_host == PRODUCTION_PRIMARY_HOST or stripped_host in PRODUCTION_HOSTS:
            target_host = stripped_host
        elif PRODUCTION_PRIMARY_HOST:
            target_host = PRODUCTION_PRIMARY_HOST

    scheme = forwarded_scheme(request)
    target_scheme = "https" if FORCE_HTTPS else scheme
    needs_https = FORCE_HTTPS and scheme != "https"
    if not target_host and not needs_https:
        return None

    final_host = target_host or host
    path = request.url.path
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{target_scheme}://{final_host}{path}{query}"


def domain_config_payload() -> Dict[str, Any]:
    return {
        "public_url": PUBLIC_BASE_URL,
        "primary_host": PRODUCTION_PRIMARY_HOST,
        "production_hosts": sorted(PRODUCTION_HOSTS),
        "redirect_hosts": sorted(PRODUCTION_REDIRECT_HOSTS),
        "force_https": FORCE_HTTPS,
        "redirect_www": REDIRECT_WWW,
    }


def ensure_stripe_customer(db: sqlite3.Connection, user: Dict[str, Any]) -> str:
    row = db.execute("SELECT stripe_customer_id FROM users WHERE id = ?", (user["id"],)).fetchone()
    if row and row["stripe_customer_id"]:
        return row["stripe_customer_id"]
    stripe = stripe_module()
    customer = stripe.Customer.create(
        email=user["email"],
        metadata={"software_user_id": user["id"]},
    )
    customer_id = stripe_get(customer, "id")
    if not customer_id:
        raise HTTPException(status_code=502, detail="Stripe did not return a customer id.")
    db.execute("UPDATE users SET stripe_customer_id = ? WHERE id = ?", (customer_id, user["id"]))
    return customer_id


def create_local_subscription(
    db: sqlite3.Connection,
    user_id: str,
    plan_id: str,
    *,
    status: str = "active",
    stripe_subscription_id: Optional[str] = None,
    stripe_price_id: Optional[str] = None,
    stripe_status: Optional[str] = None,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    plan = db.execute("SELECT id FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if not plan:
        plan_id = "free"
    now = now_iso()
    start, end = month_period()
    period_start = period_start or start
    period_end = period_end or end
    db.execute(
        """
        UPDATE subscriptions
        SET status = 'cancelled', updated_at = ?
        WHERE user_id = ? AND status = 'active'
        """,
        (now, user_id),
    )
    subscription_id = f"sub_{uuid.uuid4().hex}"
    db.execute(
        """
        INSERT INTO subscriptions (
            id, user_id, plan_id, status, stripe_subscription_id,
            stripe_price_id, stripe_status, current_period_start,
            current_period_end, created_at, updated_at, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            subscription_id,
            user_id,
            plan_id,
            status,
            stripe_subscription_id,
            stripe_price_id,
            stripe_status,
            period_start,
            period_end,
            now,
            now,
            json.dumps(metadata or {}, sort_keys=True),
        ),
    )
    return subscription_id


def user_id_for_stripe_customer(db: sqlite3.Connection, customer_id: str) -> Optional[str]:
    row = db.execute("SELECT id FROM users WHERE stripe_customer_id = ?", (customer_id,)).fetchone()
    return row["id"] if row else None


def subscription_price_id(subscription: Any) -> Optional[str]:
    items = stripe_nested(subscription, "items", "data", default=[])
    if not items:
        return None
    first = items[0]
    price = stripe_get(first, "price", {})
    return stripe_get(price, "id")


def sync_stripe_subscription(db: sqlite3.Connection, subscription: Any, event_type: str) -> Dict[str, Any]:
    stripe_subscription_id = stripe_get(subscription, "id")
    stripe_customer_id = stripe_get(subscription, "customer")
    if not stripe_customer_id:
        return {"synced": False, "reason": "Missing Stripe customer id."}
    user_id = user_id_for_stripe_customer(db, stripe_customer_id)
    if not user_id:
        metadata_user_id = stripe_nested(subscription, "metadata", "software_user_id")
        if metadata_user_id:
            user = db.execute("SELECT id FROM users WHERE id = ?", (metadata_user_id,)).fetchone()
            user_id = user["id"] if user else None
    if not user_id:
        return {"synced": False, "reason": "No local user found for Stripe customer."}

    stripe_status = stripe_get(subscription, "status", "unknown")
    stripe_price_id = subscription_price_id(subscription)
    plan_id = plan_id_from_stripe_price(stripe_price_id)
    period_start = stripe_epoch_to_iso(stripe_get(subscription, "current_period_start"))
    period_end = stripe_epoch_to_iso(stripe_get(subscription, "current_period_end"))
    if event_type == "customer.subscription.deleted" or stripe_status in {"canceled", "cancelled", "unpaid"}:
        db.execute(
            """
            UPDATE subscriptions
            SET status = 'cancelled', stripe_status = ?, updated_at = ?
            WHERE user_id = ? AND stripe_subscription_id = ?
            """,
            (stripe_status, now_iso(), user_id, stripe_subscription_id),
        )
        create_local_subscription(
            db,
            user_id,
            "free",
            status="active",
            stripe_status="cancelled",
            metadata={"stripe_event_type": event_type, "fallback_to_free": True},
        )
        return {"synced": True, "user_id": user_id, "plan_id": "free", "status": "cancelled"}

    local_status = "active" if stripe_status in {"active", "trialing", "past_due"} else stripe_status
    create_local_subscription(
        db,
        user_id,
        plan_id,
        status=local_status,
        stripe_subscription_id=stripe_subscription_id,
        stripe_price_id=stripe_price_id,
        stripe_status=stripe_status,
        period_start=period_start,
        period_end=period_end,
        metadata={"stripe_event_type": event_type},
    )
    return {"synced": True, "user_id": user_id, "plan_id": plan_id, "status": stripe_status}


def upsert_stripe_invoice(db: sqlite3.Connection, invoice: Any, event_type: str) -> Dict[str, Any]:
    invoice_id = stripe_get(invoice, "id")
    if not invoice_id:
        return {"synced": False, "reason": "Missing Stripe invoice id."}
    customer_id = stripe_get(invoice, "customer")
    user_id = user_id_for_stripe_customer(db, customer_id) if customer_id else None
    created_at = stripe_epoch_to_iso(stripe_get(invoice, "created"))
    db.execute(
        """
        INSERT INTO stripe_invoices (
            id, user_id, stripe_invoice_id, stripe_customer_id,
            stripe_subscription_id, status, amount_paid, amount_due,
            currency, hosted_invoice_url, invoice_pdf, created_at, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(stripe_invoice_id) DO UPDATE SET
            user_id = excluded.user_id,
            stripe_customer_id = excluded.stripe_customer_id,
            stripe_subscription_id = excluded.stripe_subscription_id,
            status = excluded.status,
            amount_paid = excluded.amount_paid,
            amount_due = excluded.amount_due,
            currency = excluded.currency,
            hosted_invoice_url = excluded.hosted_invoice_url,
            invoice_pdf = excluded.invoice_pdf,
            metadata_json = excluded.metadata_json
        """,
        (
            f"inv_{uuid.uuid4().hex}",
            user_id,
            invoice_id,
            customer_id,
            stripe_get(invoice, "subscription"),
            stripe_get(invoice, "status"),
            int(stripe_get(invoice, "amount_paid", 0) or 0),
            int(stripe_get(invoice, "amount_due", 0) or 0),
            stripe_get(invoice, "currency"),
            stripe_get(invoice, "hosted_invoice_url"),
            stripe_get(invoice, "invoice_pdf"),
            created_at,
            json.dumps({"stripe_event_type": event_type}, sort_keys=True),
        ),
    )
    return {"synced": True, "user_id": user_id, "invoice_id": invoice_id}


def billing_invoice_rows(db: sqlite3.Connection, user_id: str) -> List[Dict[str, Any]]:
    rows = db.execute(
        """
        SELECT stripe_invoice_id, status, amount_paid, amount_due, currency,
               hosted_invoice_url, invoice_pdf, created_at
        FROM stripe_invoices
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (user_id,),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
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

            CREATE TABLE IF NOT EXISTS benchmark_runs (
                run_id TEXT PRIMARY KEY,
                user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                model TEXT NOT NULL,
                provider_url TEXT NOT NULL,
                environment TEXT NOT NULL DEFAULT 'real_world',
                total_workflows INTEGER NOT NULL,
                successful INTEGER NOT NULL,
                failed INTEGER NOT NULL,
                success_rate REAL NOT NULL,
                failure_rate REAL NOT NULL,
                reliability_score_v2 REAL NOT NULL,
                reliability_band_v2 TEXT NOT NULL,
                average_execution_time REAL NOT NULL,
                average_confidence REAL NOT NULL,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS workflow_results (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES benchmark_runs(run_id) ON DELETE CASCADE,
                workflow_id TEXT NOT NULL,
                status TEXT NOT NULL,
                successful INTEGER NOT NULL DEFAULT 0,
                failed_agent TEXT,
                failure_reason TEXT,
                execution_time REAL NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 0,
                retry_count INTEGER NOT NULL DEFAULT 0,
                rollback_count INTEGER NOT NULL DEFAULT 0,
                escalation_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS failure_records (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                run_id TEXT,
                workflow_id TEXT NOT NULL,
                workflow_name TEXT,
                failure_reason TEXT NOT NULL,
                failure_category TEXT NOT NULL,
                execution_duration REAL NOT NULL DEFAULT 0,
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS model_results (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES benchmark_runs(run_id) ON DELETE CASCADE,
                user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                model TEXT NOT NULL,
                provider_url TEXT NOT NULL,
                success_rate REAL NOT NULL,
                failure_rate REAL NOT NULL,
                retry_rate REAL NOT NULL,
                recovery_rate REAL NOT NULL,
                tool_reliability REAL NOT NULL,
                timeout_rate REAL NOT NULL,
                average_execution_time REAL NOT NULL,
                confidence_accuracy REAL NOT NULL,
                reliability_score_v2 REAL NOT NULL,
                reliability_band_v2 TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reliability_scores (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES benchmark_runs(run_id) ON DELETE CASCADE,
                user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                model TEXT NOT NULL,
                reliability_score_v1 REAL NOT NULL,
                reliability_score_v2 REAL NOT NULL,
                reliability_band_v1 TEXT NOT NULL,
                reliability_band_v2 TEXT NOT NULL,
                success_rate REAL NOT NULL,
                failure_rate REAL NOT NULL,
                retry_rate REAL NOT NULL,
                recovery_rate REAL NOT NULL,
                retry_success_rate REAL NOT NULL,
                tool_reliability REAL NOT NULL,
                timeout_rate REAL NOT NULL,
                confidence_accuracy REAL NOT NULL,
                average_execution_time_ms REAL NOT NULL,
                execution_time_score REAL NOT NULL,
                escalation_rate REAL NOT NULL,
                workflow_completion_rate REAL NOT NULL,
                simulation_success_rate REAL NOT NULL,
                simulation_gap REAL NOT NULL,
                data_completeness REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_benchmark_runs_created_at
                ON benchmark_runs(created_at);

            CREATE INDEX IF NOT EXISTS idx_model_results_model_score
                ON model_results(model, reliability_score_v2);

            CREATE INDEX IF NOT EXISTS idx_reliability_scores_model_created_at
                ON reliability_scores(model, created_at);

            CREATE INDEX IF NOT EXISTS idx_failure_records_created
                ON failure_records(created_at);

            CREATE INDEX IF NOT EXISTS idx_failure_records_category_created
                ON failure_records(failure_category, created_at);

            CREATE INDEX IF NOT EXISTS idx_failure_records_workflow
                ON failure_records(workflow_id, created_at);

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

            CREATE INDEX IF NOT EXISTS idx_stripe_invoices_user_created
                ON stripe_invoices(user_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_stripe_invoices_subscription
                ON stripe_invoices(stripe_subscription_id);

            CREATE INDEX IF NOT EXISTS idx_stripe_events_type
                ON stripe_events(event_type);

            CREATE INDEX IF NOT EXISTS idx_usage_records_user_period
                ON usage_records(user_id, metric_type, created_at);

            CREATE INDEX IF NOT EXISTS idx_usage_records_project_period
                ON usage_records(project_id, metric_type, created_at);

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

            CREATE TABLE IF NOT EXISTS sdk_workflows (
                workflow_id TEXT PRIMARY KEY,
                user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                api_key_id TEXT REFERENCES api_keys(id) ON DELETE SET NULL,
                project_name TEXT NOT NULL,
                workflow_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                success INTEGER,
                confidence REAL,
                predicted_failure_probability REAL,
                guardrail_action TEXT,
                total_latency_ms INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS sdk_events (
                event_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL REFERENCES sdk_workflows(workflow_id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                stage_name TEXT,
                name TEXT,
                model TEXT,
                tool_name TEXT,
                success INTEGER,
                latency_ms INTEGER,
                confidence REAL,
                error_type TEXT,
                error_message TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sdk_workflows_project_started
                ON sdk_workflows(project_name, started_at);

            CREATE INDEX IF NOT EXISTS idx_sdk_events_workflow_created
                ON sdk_events(workflow_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_sdk_events_type_created
                ON sdk_events(event_type, created_at);
            """
        )
        ensure_column(db, "sdk_workflows", "user_id", "TEXT REFERENCES users(id) ON DELETE SET NULL")
        ensure_column(db, "sdk_workflows", "project_id", "TEXT REFERENCES projects(id) ON DELETE SET NULL")
        ensure_column(db, "sdk_workflows", "api_key_id", "TEXT REFERENCES api_keys(id) ON DELETE SET NULL")
        ensure_column(db, "benchmark_runs", "user_id", "TEXT REFERENCES users(id) ON DELETE SET NULL")
        ensure_column(db, "model_results", "user_id", "TEXT REFERENCES users(id) ON DELETE SET NULL")
        ensure_column(db, "reliability_scores", "user_id", "TEXT REFERENCES users(id) ON DELETE SET NULL")
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_benchmark_runs_user_created
                ON benchmark_runs(user_id, created_at)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_model_results_user_score
                ON model_results(user_id, reliability_score_v2)
            """
        )
        ensure_column(db, "projects", "organization_id", "TEXT REFERENCES organizations(id) ON DELETE SET NULL")
        ensure_column(db, "users", "stripe_customer_id", "TEXT")
        ensure_column(db, "subscriptions", "stripe_subscription_id", "TEXT")
        ensure_column(db, "subscriptions", "stripe_price_id", "TEXT")
        ensure_column(db, "subscriptions", "stripe_status", "TEXT")
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_subscription
                ON subscriptions(stripe_subscription_id)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_users_stripe_customer
                ON users(stripe_customer_id)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_projects_org_created
                ON projects(organization_id, created_at)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sdk_workflows_owner_started
                ON sdk_workflows(user_id, project_id, started_at)
            """
        )
        seed_plans(db)
        bootstrap_dev_identity(db)
        ensure_default_subscriptions(db)


class WorkflowResultCreate(BaseModel):
    workflow_id: str = Field(..., min_length=1, max_length=160)
    status: str = Field("completed", max_length=40)
    successful: bool = False
    failed_agent: Optional[str] = Field(None, max_length=160)
    failure_reason: Optional[str] = Field(None, max_length=500)
    execution_time: float = 0.0
    confidence: float = 0.0
    retry_count: int = 0
    rollback_count: int = 0
    escalation_count: int = 0


class BenchmarkRunCreate(BaseModel):
    run_id: Optional[str] = Field(None, max_length=120)
    model: str = Field(..., min_length=1, max_length=160)
    provider_url: str = Field(..., min_length=1, max_length=500)
    environment: str = Field("real_world", max_length=40)
    total_workflows: int = Field(..., ge=0)
    successful: int = Field(..., ge=0)
    failed: int = Field(..., ge=0)
    average_execution_time: float = Field(..., ge=0)
    average_confidence: float = Field(..., ge=0, le=1)
    retries: int = Field(0, ge=0)
    rollbacks: int = Field(0, ge=0)
    escalations: int = Field(0, ge=0)
    stops: int = Field(0, ge=0)
    tool_reliability: float = Field(100.0, ge=0, le=100)
    timeout_rate: float = Field(0.0, ge=0, le=100)
    simulation_success_rate: float = Field(0.0, ge=0, le=100)
    data_completeness: float = Field(75.0, ge=0, le=100)
    workflows: List[WorkflowResultCreate] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BenchmarkRunnerRequest(BaseModel):
    model: str = Field("software-simulated-agent", min_length=1, max_length=160)
    provider_url: str = Field("local-simulator", min_length=1, max_length=500)
    workflow_count: int = Field(50, ge=1, le=500)
    scenario: str = Field("mixed", pattern="^(mixed|success|failure)$")
    target_success_rate: Optional[float] = Field(None, ge=0, le=100)
    seed: Optional[int] = None


class BenchmarkSampleRequest(BaseModel):
    runs: int = Field(6, ge=1, le=25)
    workflow_count: int = Field(40, ge=1, le=500)
    seed: Optional[int] = None


class SDKWorkflowStart(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=160)
    workflow_name: str = Field(..., min_length=1, max_length=220)
    workflow_id: Optional[str] = Field(None, max_length=180)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SDKStageEvent(BaseModel):
    workflow_id: str = Field(..., min_length=1, max_length=180)
    stage_name: str = Field(..., min_length=1, max_length=160)
    status: str = Field("started", max_length=40)
    success: Optional[bool] = None
    latency_ms: Optional[int] = Field(None, ge=0)
    confidence: Optional[float] = Field(None, ge=0, le=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SDKModelCall(BaseModel):
    workflow_id: str = Field(..., min_length=1, max_length=180)
    model: str = Field(..., min_length=1, max_length=160)
    success: bool
    latency_ms: int = Field(..., ge=0)
    stage_name: Optional[str] = Field(None, max_length=160)
    confidence: Optional[float] = Field(None, ge=0, le=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SDKToolCall(BaseModel):
    workflow_id: str = Field(..., min_length=1, max_length=180)
    tool_name: str = Field(..., min_length=1, max_length=160)
    success: bool
    latency_ms: int = Field(..., ge=0)
    stage_name: Optional[str] = Field(None, max_length=160)
    result_count: Optional[int] = Field(None, ge=0)
    confidence: Optional[float] = Field(None, ge=0, le=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SDKErrorEvent(BaseModel):
    workflow_id: str = Field(..., min_length=1, max_length=180)
    error_type: str = Field("error", max_length=120)
    error_message: str = Field(..., min_length=1, max_length=1200)
    stage_name: Optional[str] = Field(None, max_length=160)
    fatal: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SDKWorkflowComplete(BaseModel):
    workflow_id: str = Field(..., min_length=1, max_length=180)
    success: bool
    confidence: float = Field(..., ge=0, le=1)
    total_latency_ms: Optional[int] = Field(None, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SDKPredictRequest(BaseModel):
    workflow_id: str = Field(..., min_length=1, max_length=180)


class SDKRecoveryRequest(BaseModel):
    workflow_id: str = Field(..., min_length=1, max_length=180)
    auto_apply: bool = True


class ComposioToolExecuteRequest(BaseModel):
    workflow_id: str = Field(..., min_length=1, max_length=180)
    tool_slug: str = Field(..., min_length=1, max_length=240)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    account: Optional[str] = Field(None, max_length=240)
    agent_name: Optional[str] = Field(None, max_length=160)
    chat_id: Optional[str] = Field(None, max_length=180)
    return_to: str = Field("/apps", min_length=1, max_length=1000)


class SDKTestWorkflowRequest(BaseModel):
    project_name: Optional[str] = Field(None, max_length=160)
    workflow_name: str = Field("install-page-test", min_length=1, max_length=220)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OptimizerRunRequest(BaseModel):
    dry_run: bool = True
    min_confidence: float = Field(90.0, ge=0, le=100)
    limit: int = Field(5, ge=1, le=25)


class OptimizerRollbackRequest(BaseModel):
    event_id: str = Field(..., min_length=1, max_length=180)
    dry_run: bool = False


class DecisionValidateRequest(BaseModel):
    recommendation_id: Optional[str] = Field(None, max_length=180)
    source: str = Field("reliability_copilot", min_length=1, max_length=120)
    action_type: str = Field(..., min_length=1, max_length=120)
    target: str = Field(..., min_length=1, max_length=240)
    confidence: float = Field(..., ge=0, le=100)
    risk_level: Optional[str] = Field(None, max_length=20)
    reason: str = Field(..., min_length=1, max_length=1200)
    action: Dict[str, Any] = Field(default_factory=dict)
    rollback_plan: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DecisionApprovalRequest(BaseModel):
    decision_id: str = Field(..., min_length=1, max_length=180)
    reason: Optional[str] = Field(None, max_length=1200)


class AuthRegister(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=200)


class AuthLogin(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=200)


class PasswordResetRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)


class PasswordUpdateRequest(BaseModel):
    access_token: str = Field(..., min_length=10)
    refresh_token: str = Field(..., min_length=10)
    password: str = Field(..., min_length=8, max_length=200)


class ChatCreate(BaseModel):
    title: str = Field("New chat", min_length=1, max_length=240)
    project_id: Optional[str] = Field(None, max_length=180)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChatMessageCreate(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system|tool)$")
    content: str = Field(..., min_length=1, max_length=50000)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    organization_id: Optional[str] = Field(None, max_length=180)


class InstallApiKeyCreate(BaseModel):
    project_name: str = Field("my-agent", min_length=1, max_length=160)


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)


class OrganizationInvite(BaseModel):
    organization_id: str = Field(..., min_length=1, max_length=180)
    email: str = Field(..., min_length=3, max_length=320)
    role: str = Field("developer", min_length=1, max_length=40)


class OrganizationRemoveMember(BaseModel):
    organization_id: str = Field(..., min_length=1, max_length=180)
    user_id: str = Field(..., min_length=1, max_length=180)


class OrganizationTransferOwnership(BaseModel):
    organization_id: str = Field(..., min_length=1, max_length=180)
    new_owner_user_id: str = Field(..., min_length=1, max_length=180)


class APIKeyCreate(BaseModel):
    pass


class SubscriptionChange(BaseModel):
    plan_id: str = Field(..., min_length=1, max_length=80)


class BillingCheckoutCreate(BaseModel):
    plan_id: str = Field(..., min_length=1, max_length=80)
    success_url: Optional[str] = Field(None, max_length=800)
    cancel_url: Optional[str] = Field(None, max_length=800)


class BillingPortalCreate(BaseModel):
    return_url: Optional[str] = Field(None, max_length=800)


class RequestAccessCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    email: str = Field(..., min_length=3, max_length=320)
    company: Optional[str] = Field(None, max_length=160)
    role: Optional[str] = Field(None, max_length=160)
    use_case: str = Field(..., min_length=10, max_length=1200)
    expected_workflows_per_month: Optional[int] = Field(None, ge=0)
    timeline: Optional[str] = Field(None, max_length=160)


class SDKInstallationCreate(BaseModel):
    source: str = Field("sdk_cli", max_length=120)
    sdk_version: Optional[str] = Field(None, max_length=80)
    python_version: Optional[str] = Field(None, max_length=80)
    platform: Optional[str] = Field(None, max_length=200)
    project_name: Optional[str] = Field(None, max_length=160)
    metadata: Dict[str, Any] = Field(default_factory=dict)


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or "." not in normalized.split("@")[-1]:
        raise HTTPException(status_code=400, detail="A valid email address is required.")
    return normalized


def create_access_token(user_id: str) -> Dict[str, Any]:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return {
        "access_token": jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM),
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
    }


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise HTTPException(status_code=401, detail="Token expired.") from error
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=401, detail="Invalid token.") from error
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token subject.")
    return str(user_id)


def bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    prefix = "Bearer "
    if authorization.startswith(prefix):
        return authorization[len(prefix):].strip()
    return authorization.strip()


def session_cache_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def set_session_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=access_token,
        max_age=JWT_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clerk_is_configured() -> bool:
    return bool(CLERK_PUBLISHABLE_KEY and CLERK_JWT_ISSUER and CLERK_JWKS_URL and CLERK_JWK_CLIENT)


def clerk_public_config() -> Dict[str, Any]:
    return {
        "provider": "clerk",
        "configured": clerk_is_configured(),
        "clerk_publishable_key": CLERK_PUBLISHABLE_KEY,
        "clerk_jwt_issuer": CLERK_JWT_ISSUER,
        "oauth_providers": ["google", "github"],
    }


def verify_clerk_token(token: str) -> Dict[str, Any]:
    if not token:
        raise HTTPException(status_code=401, detail="Missing Clerk session token.")
    if not clerk_is_configured() or CLERK_JWK_CLIENT is None:
        raise HTTPException(status_code=503, detail="Clerk authentication is not configured.")
    try:
        signing_key = CLERK_JWK_CLIENT.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=CLERK_JWT_ISSUER,
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError as error:
        raise HTTPException(status_code=401, detail="Clerk session expired.") from error
    except Exception as error:
        raise HTTPException(status_code=401, detail="Invalid Clerk session.") from error


def fetch_clerk_user_profile(user_id: str) -> Dict[str, Any]:
    if not CLERK_SECRET_KEY:
        return {}
    try:
        response = requests.get(
            f"https://api.clerk.com/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}", "Accept": "application/json"},
            timeout=CLERK_AUTH_TIMEOUT,
        )
        if response.status_code >= 400:
            return {}
        return response.json() if response.content else {}
    except requests.RequestException:
        return {}


def clerk_email_from_profile(profile: Dict[str, Any]) -> str:
    addresses = profile.get("email_addresses")
    primary_id = profile.get("primary_email_address_id")
    if isinstance(addresses, list):
        for address in addresses:
            if isinstance(address, dict) and address.get("id") == primary_id and address.get("email_address"):
                return str(address["email_address"])
        for address in addresses:
            if isinstance(address, dict) and address.get("email_address"):
                return str(address["email_address"])
    return ""


def ensure_clerk_user(claims: Dict[str, Any]) -> Dict[str, Any]:
    user_id = str(claims.get("sub") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Clerk session did not include a user id.")
    email = str(
        claims.get("email")
        or claims.get("email_address")
        or claims.get("primary_email_address")
        or ""
    ).strip()
    profile: Dict[str, Any] = {}
    if not email:
        profile = fetch_clerk_user_profile(user_id)
        email = clerk_email_from_profile(profile)
    if not email:
        email = f"{user_id}@clerk.local"
    user = ensure_external_user(user_id, email, now_iso())
    try:
        profile_sync = supabase_upsert_user_profile(
            user_id=user_id,
            email=email,
            metadata={
                "provider": "clerk",
                "email_verified": bool(claims.get("email_verified")),
                "first_name": claims.get("first_name") or profile.get("first_name"),
                "last_name": claims.get("last_name") or profile.get("last_name"),
            },
        )
    except Exception as error:
        profile_sync = {"ok": False, "error": redact_text(str(error))}
        capture_operational_error(
            error,
            category="external_http_or_provider_failure",
            level="warning",
            user_id=user_id,
            provider="supabase",
            operation="upsert_user_profile",
        )
    if not profile_sync.get("ok"):
        LOGGER.warning(
            "Supabase profile sync failed for Clerk user %s: %s",
            user_id,
            profile_sync.get("error") or "unknown error",
        )
    redis_set_session_cache(
        session_cache_id(user_id),
        {"user": user, "provider": "clerk"},
    )
    return user


def ensure_external_user(user_id: str, email: str, created_at: Optional[str] = None) -> Dict[str, Any]:
    init_db()
    normalized_email = normalize_email(email)
    timestamp = created_at or now_iso()
    with connect() as db:
        row = db.execute("SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            email_row = db.execute(
                "SELECT id, email, created_at FROM users WHERE email = ?",
                (normalized_email,),
            ).fetchone()
            if email_row:
                row = email_row
            else:
                db.execute(
                    """
                    INSERT INTO users (id, email, password_hash, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        normalized_email,
                        hash_password(secrets.token_urlsafe(32)),
                        timestamp,
                    ),
                )
            ensure_default_subscriptions(db)
            if row is None:
                row = db.execute(
                    "SELECT id, email, created_at FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
    return row_to_dict(row)


def authenticated_user_from_token(token: str) -> Dict[str, Any]:
    try:
        user_id = decode_access_token(token)
    except HTTPException as local_error:
        if clerk_is_configured():
            claims = verify_clerk_token(token)
            clerk_user_id = str(claims.get("sub") or "").strip()
            cached_clerk = redis_get_session_cache(session_cache_id(clerk_user_id))
            cached_user = cached_clerk.get("user") if isinstance(cached_clerk, dict) else None
            if isinstance(cached_user, dict):
                cached_email = str(
                    cached_user.get("email")
                    or claims.get("email")
                    or claims.get("email_address")
                    or claims.get("primary_email_address")
                    or ""
                ).strip()
                if clerk_user_id and cached_email:
                    user = ensure_external_user(clerk_user_id, cached_email)
                    redis_set_session_cache(
                        session_cache_id(clerk_user_id),
                        {"user": user, "provider": "clerk"},
                    )
                    return user
            return ensure_clerk_user(claims)
        raise local_error

    cached_local = redis_get_session_cache(session_cache_id(token))
    if cached_local and cached_local.get("user"):
        cached_user = dict(cached_local["user"])
        if str(cached_user.get("id")) == user_id:
            init_db()
            with connect() as db:
                row = db.execute("SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
            if row:
                return row_to_dict(row)
            redis_delete_session_cache(session_cache_id(token))
    init_db()
    with connect() as db:
        row = db.execute("SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="User no longer exists.")
    user = row_to_dict(row)
    redis_set_session_cache(
        session_cache_id(token),
        {"user": user, "provider": "local"},
    )
    return user


def current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    token = bearer_token(authorization) or request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Missing session.")
    user = authenticated_user_from_token(token)
    with connect() as db:
        record_usage(db, user["id"], "api_request", metadata={"source": "user_api"})
    set_monitoring_context(user_id=user["id"])
    return user


def optional_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Optional[Dict[str, Any]]:
    try:
        return current_user(request, authorization)
    except HTTPException:
        return None


def protected_page(request: Request, filename: str) -> Response:
    if clerk_is_configured() and CLERK_AUTH_REQUIRED:
        return FileResponse(BASE_DIR / filename)
    if optional_current_user(request, None) is None:
        target = request.url.path
        return RedirectResponse(f"/login?next={target}", status_code=303)
    return FileResponse(BASE_DIR / filename)


def require_admin_user(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    if user["email"].lower() not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


def normalize_org_role(role: str, *, allow_owner: bool = False) -> str:
    normalized = role.strip().lower()
    allowed = ORG_ROLES if allow_owner else ORG_ROLES - {"owner"}
    if normalized not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid organization role: {role}.")
    return normalized


def role_at_least(role: str, minimum: str) -> bool:
    return ORG_ROLE_RANK.get(role, 0) >= ORG_ROLE_RANK[minimum]


def organization_or_404(db: sqlite3.Connection, organization_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM organizations WHERE id = ?", (organization_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Organization not found.")
    return row


def organization_membership(
    db: sqlite3.Connection,
    organization_id: str,
    user_id: str,
) -> Optional[sqlite3.Row]:
    return db.execute(
        """
        SELECT organization_members.*, users.email
        FROM organization_members
        JOIN users ON users.id = organization_members.user_id
        WHERE organization_members.organization_id = ?
          AND organization_members.user_id = ?
        """,
        (organization_id, user_id),
    ).fetchone()


def require_org_role(
    db: sqlite3.Connection,
    organization_id: str,
    user_id: str,
    minimum_role: str = "viewer",
) -> sqlite3.Row:
    organization_or_404(db, organization_id)
    membership = organization_membership(db, organization_id, user_id)
    if not membership:
        raise HTTPException(status_code=404, detail="Organization not found.")
    if not role_at_least(membership["role"], minimum_role):
        raise HTTPException(status_code=403, detail="Insufficient organization permissions.")
    return membership


def owner_count(db: sqlite3.Connection, organization_id: str) -> int:
    return int(
        db.execute(
            """
            SELECT COUNT(*) AS count
            FROM organization_members
            WHERE organization_id = ? AND role = 'owner'
            """,
            (organization_id,),
        ).fetchone()["count"]
        or 0
    )


def user_project_or_404(db: sqlite3.Connection, user_id: str, project_id: str) -> sqlite3.Row:
    row = db.execute(
        """
        SELECT projects.*,
               organizations.name AS organization_name,
               organization_members.role AS organization_role
        FROM projects
        LEFT JOIN organizations ON organizations.id = projects.organization_id
        LEFT JOIN organization_members
               ON organization_members.organization_id = projects.organization_id
              AND organization_members.user_id = ?
        WHERE projects.id = ?
          AND (projects.user_id = ? OR organization_members.user_id = ?)
        """,
        (user_id, project_id, user_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    return row


def project_permission_or_404(
    db: sqlite3.Connection,
    user_id: str,
    project_id: str,
    minimum_org_role: str = "viewer",
) -> sqlite3.Row:
    project = user_project_or_404(db, user_id, project_id)
    if project["organization_id"] and not role_at_least(project["organization_role"], minimum_org_role):
        raise HTTPException(status_code=403, detail="Insufficient project permissions.")
    return project


def team_workspaces_payload(user_id: str) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        org_rows = db.execute(
            """
            SELECT organizations.id, organizations.name, organizations.owner_user_id,
                   organizations.created_at, organization_members.role,
                   COUNT(DISTINCT member_counts.user_id) AS member_count,
                   COUNT(DISTINCT invitations.id) AS invitation_count
            FROM organizations
            JOIN organization_members
              ON organization_members.organization_id = organizations.id
             AND organization_members.user_id = ?
            LEFT JOIN organization_members AS member_counts
              ON member_counts.organization_id = organizations.id
            LEFT JOIN invitations
              ON invitations.organization_id = organizations.id
             AND invitations.status = 'pending'
            GROUP BY organizations.id, organization_members.role
            ORDER BY organizations.created_at DESC
            """,
            (user_id,),
        ).fetchall()
        org_ids = [row["id"] for row in org_rows]
        members: List[Dict[str, Any]] = []
        invitations_list: List[Dict[str, Any]] = []
        if org_ids:
            placeholders = ", ".join("?" for _ in org_ids)
            member_rows = db.execute(
                f"""
                SELECT organization_members.id, organization_members.organization_id,
                       organizations.name AS organization_name,
                       organization_members.user_id, users.email,
                       organization_members.role, organization_members.created_at,
                       organization_members.updated_at
                FROM organization_members
                JOIN users ON users.id = organization_members.user_id
                JOIN organizations ON organizations.id = organization_members.organization_id
                WHERE organization_members.organization_id IN ({placeholders})
                ORDER BY organizations.name ASC,
                         CASE organization_members.role
                           WHEN 'owner' THEN 1
                           WHEN 'admin' THEN 2
                           WHEN 'developer' THEN 3
                           ELSE 4
                         END,
                         users.email ASC
                """,
                org_ids,
            ).fetchall()
            invitation_rows = db.execute(
                f"""
                SELECT invitations.id, invitations.organization_id,
                       organizations.name AS organization_name,
                       invitations.email, invitations.role, invitations.status,
                       invitations.invited_by_user_id, users.email AS invited_by_email,
                       invitations.created_at, invitations.accepted_at
                FROM invitations
                JOIN organizations ON organizations.id = invitations.organization_id
                JOIN users ON users.id = invitations.invited_by_user_id
                WHERE invitations.organization_id IN ({placeholders})
                ORDER BY invitations.created_at DESC
                """,
                org_ids,
            ).fetchall()
            members = [row_to_dict(row) for row in member_rows]
            invitations_list = [row_to_dict(row) for row in invitation_rows]
    organizations = [row_to_dict(row) for row in org_rows]
    return {
        "organizations": organizations,
        "members": members,
        "invitations": invitations_list,
        "organization_count": len(organizations),
        "member_count": len(members),
        "pending_invitation_count": len([item for item in invitations_list if item["status"] == "pending"]),
    }


def validate_counts(payload: BenchmarkRunCreate) -> None:
    if payload.successful + payload.failed != payload.total_workflows:
        raise HTTPException(
            status_code=400,
            detail="successful + failed must equal total_workflows.",
        )


def make_run_id(model: str) -> str:
    clean_model = "".join(ch.lower() if ch.isalnum() else "_" for ch in model).strip("_")[:40]
    return f"run_{clean_model}_{uuid.uuid4().hex[:10]}"


def clamp_float(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def scenario_success_rate(scenario: str, target_success_rate: Optional[float], rng: random.Random) -> float:
    if target_success_rate is not None:
        return target_success_rate
    if scenario == "success":
        return clamp_float(rng.gauss(93.0, 3.0), 85.0, 99.0)
    if scenario == "failure":
        return clamp_float(rng.gauss(42.0, 9.0), 15.0, 62.0)
    return clamp_float(rng.gauss(76.0, 8.0), 58.0, 91.0)


def build_simulated_benchmark_payload(
    request: BenchmarkRunnerRequest,
    run_index: int = 0,
    sample_mode: bool = False,
) -> BenchmarkRunCreate:
    rng = random.Random(request.seed + run_index if request.seed is not None else None)
    target = scenario_success_rate(request.scenario, request.target_success_rate, rng)
    model_suffix = f"-sample-{run_index + 1}" if sample_mode else ""
    model = f"{request.model}{model_suffix}"
    failure_agents = [
        "ResearchAgent",
        "PlanningAgent",
        "SearchAgent",
        "ExtractionAgent",
        "CodeAgent",
        "TestAgent",
        "ResponseAgent",
    ]
    failure_reasons = [
        "tool_timeout",
        "low_confidence",
        "model_timeout",
        "extraction_failure",
        "planning_error",
        "context_loss",
        "schema_mismatch",
    ]
    workflows: List[WorkflowResultCreate] = []
    retry_total = 0
    rollback_total = 0
    escalation_total = 0
    stop_total = 0
    confidence_total = 0.0
    execution_total = 0.0

    for index in range(request.workflow_count):
        successful = rng.random() < (target / 100.0)
        retry_count = rng.randint(0, 1 if successful else 4)
        rollback_count = 0 if successful else rng.randint(0, 2)
        escalation_count = 0 if successful or rng.random() > 0.35 else 1
        stopped = 0 if successful or rng.random() > 0.2 else 1
        confidence = clamp_float(
            rng.gauss(0.92 if successful else 0.66, 0.06 if successful else 0.12),
            0.35,
            0.99,
        )
        execution_time = clamp_float(
            rng.gauss(1.5 if successful else 3.2, 0.6 if successful else 1.4),
            0.2,
            12.0,
        )
        retry_total += retry_count
        rollback_total += rollback_count
        escalation_total += escalation_count
        stop_total += stopped
        confidence_total += confidence
        execution_total += execution_time
        workflows.append(
            WorkflowResultCreate(
                workflow_id=f"wf_benchmark_{uuid.uuid4().hex[:12]}",
                status="completed" if successful else ("stopped" if stopped else "failed"),
                successful=successful,
                failed_agent=None if successful else rng.choice(failure_agents),
                failure_reason=None if successful else rng.choice(failure_reasons),
                execution_time=round(execution_time, 3),
                confidence=round(confidence, 4),
                retry_count=retry_count,
                rollback_count=rollback_count,
                escalation_count=escalation_count,
            )
        )

    successful_count = sum(1 for workflow in workflows if workflow.successful)
    failed_count = request.workflow_count - successful_count
    tool_reliability = clamp_float(100.0 - (failed_count / request.workflow_count * 35.0) - rng.uniform(0, 8), 40.0, 99.5)
    timeout_rate = clamp_float((failed_count / request.workflow_count * 18.0) + rng.uniform(0, 5), 0.0, 45.0)
    simulation_success = clamp_float(target + rng.uniform(2.0, 10.0), 0.0, 99.0)
    return BenchmarkRunCreate(
        model=model,
        provider_url=request.provider_url,
        environment="benchmark_runner",
        total_workflows=request.workflow_count,
        successful=successful_count,
        failed=failed_count,
        average_execution_time=round(execution_total / request.workflow_count, 3),
        average_confidence=round(confidence_total / request.workflow_count, 4),
        retries=retry_total,
        rollbacks=rollback_total,
        escalations=escalation_total,
        stops=stop_total,
        tool_reliability=round(tool_reliability, 2),
        timeout_rate=round(timeout_rate, 2),
        simulation_success_rate=round(simulation_success, 2),
        data_completeness=95.0,
        workflows=workflows,
        metadata={
            "source": "benchmark_runner",
            "scenario": request.scenario,
            "target_success_rate": round(target, 2),
            "sample_mode": sample_mode,
        },
    )


def sync_benchmark_to_dashboard_db(
    run_id: str,
    payload: BenchmarkRunCreate,
    metrics: Any,
    created_at: str,
) -> None:
    init_reliability_db()
    metadata = {
        **payload.metadata,
        "provider_url": payload.provider_url,
        "environment": payload.environment,
        "reliability_band_v2": metrics.reliability_band_v2,
    }
    with reliability_connect() as db:
        db.execute(
            """
            INSERT OR REPLACE INTO benchmark_runs (
                run_id, run_type, source_file, generated_at, total_workflows, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                payload.environment or "benchmark_runner",
                "api://benchmark-runner",
                created_at,
                payload.total_workflows,
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
        db.execute("DELETE FROM model_results WHERE run_id = ?", (run_id,))
        db.execute("DELETE FROM workflow_runs WHERE run_id = ?", (run_id,))
        db.execute(
            """
            INSERT INTO model_results (
                run_id, model, total_workflows, successful_workflows, failed_workflows,
                success_rate, failure_rate, average_execution_time_ms, average_confidence,
                retries, rollbacks, escalations, timeout_rate, tool_reliability,
                reliability_score_v2, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                payload.model,
                payload.total_workflows,
                payload.successful,
                payload.failed,
                metrics.success_rate,
                metrics.failure_rate,
                metrics.average_execution_time_ms,
                payload.average_confidence,
                payload.retries,
                payload.rollbacks,
                payload.escalations,
                metrics.timeout_rate,
                metrics.tool_reliability,
                metrics.reliability_score_v2,
                created_at,
            ),
        )
        for workflow in payload.workflows:
            db.execute(
                """
                INSERT OR REPLACE INTO workflow_runs (
                    run_id, workflow_id, model, confidence, latency_ms,
                    prediction_result_json, guardrail_action_json, baseline_success,
                    final_outcome, failed_stage, retries, rollbacks, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    workflow.workflow_id,
                    payload.model,
                    workflow.confidence,
                    workflow.execution_time * 1000.0,
                    None,
                    None,
                    1 if workflow.successful else 0,
                    "success" if workflow.successful else "failed",
                    workflow.failed_agent,
                    workflow.retry_count,
                    workflow.rollback_count,
                    created_at,
                ),
            )


def normalize_failure_category(reason: Optional[str]) -> str:
    value = (reason or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    if not value:
        return "unknown"
    if "database" in value and "timeout" in value:
        return "database_timeout"
    if "timeout" in value:
        return "timeout"
    if any(token in value for token in ["tool", "search", "extract", "schema", "api", "endpoint", "provider"]):
        return "tool_failure"
    if any(token in value for token in ["confidence", "uncertain"]):
        return "low_confidence"
    if any(token in value for token in ["context", "memory"]):
        return "context_loss"
    if "planning" in value or "plan" in value:
        return "planning_error"
    if any(token in value for token in ["model", "llm", "generation"]):
        return "model_failure"
    if any(token in value for token in ["policy", "approval", "unauthorized", "permission"]):
        return "governance_failure"
    return value[:64]


def record_failure(
    db: sqlite3.Connection,
    *,
    source: str,
    workflow_id: str,
    failure_reason: Optional[str],
    run_id: Optional[str] = None,
    workflow_name: Optional[str] = None,
    execution_duration: float = 0.0,
    retry_count: int = 0,
    created_at: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    reason = (failure_reason or "unknown").strip() or "unknown"
    stable_key = f"{source}|{run_id or ''}|{workflow_id}"
    failure_id = f"failure_{hashlib.sha1(stable_key.encode('utf-8')).hexdigest()[:16]}"
    db.execute(
        """
        INSERT OR REPLACE INTO failure_records (
            id, source, run_id, workflow_id, workflow_name, failure_reason,
            failure_category, execution_duration, retry_count, created_at, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            failure_id,
            source,
            run_id,
            workflow_id,
            workflow_name,
            reason,
            normalize_failure_category(reason),
            round(float(execution_duration or 0.0), 4),
            int(retry_count or 0),
            created_at or now_iso(),
            json_dumps(metadata or {}),
        ),
    )


def require_sdk_api_key(
    x_software_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    supplied = x_software_api_key
    if not supplied and authorization:
        prefix = "Bearer "
        supplied = authorization[len(prefix):].strip() if authorization.startswith(prefix) else authorization.strip()
    if not supplied:
        raise HTTPException(
            status_code=401,
            detail="Authentication required for this cloud feature. You can still install and use the SDK locally without signing in.",
        )
    supplied_hash = hash_api_key(supplied)
    init_db()
    with connect() as db:
        row = db.execute(
            """
            SELECT api_keys.id AS api_key_id,
                   api_keys.user_id,
                   api_keys.project_id,
                   api_keys.key_hash,
                   api_keys.key_prefix,
                   api_keys.is_active,
                   projects.name AS project_name
            FROM api_keys
            JOIN projects ON projects.id = api_keys.project_id
            WHERE api_keys.key_hash = ? AND api_keys.is_active = 1
            """,
            (supplied_hash,),
        ).fetchone()
        if not row or not verify_api_key_hash(supplied, row["key_hash"]):
            raise HTTPException(status_code=403, detail="Invalid SDK API key.")
        used_at = now_iso()
        db.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (used_at, row["api_key_id"]))
        record_usage(
            db,
            row["user_id"],
            "api_request",
            project_id=row["project_id"],
            api_key_id=row["api_key_id"],
            metadata={"source": "sdk"},
        )
        context = row_to_dict(row)
        context["last_used_at"] = used_at
    set_monitoring_context(
        user_id=context["user_id"],
        project_id=context["project_id"],
    )
    return context


def json_dumps(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def bool_to_int(value: Optional[bool]) -> Optional[int]:
    if value is None:
        return None
    return 1 if value else 0


def sdk_insert_event(
    db: sqlite3.Connection,
    workflow_id: str,
    event_type: str,
    *,
    stage_name: Optional[str] = None,
    name: Optional[str] = None,
    model: Optional[str] = None,
    tool_name: Optional[str] = None,
    success: Optional[bool] = None,
    latency_ms: Optional[int] = None,
    confidence: Optional[float] = None,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> str:
    event_id = f"evt_{uuid.uuid4().hex}"
    db.execute(
        """
        INSERT INTO sdk_events (
            event_id, workflow_id, event_type, stage_name, name, model, tool_name,
            success, latency_ms, confidence, error_type, error_message, payload_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            workflow_id,
            event_type,
            stage_name,
            name,
            model,
            tool_name,
            bool_to_int(success),
            latency_ms,
            confidence,
            error_type,
            error_message,
            json_dumps(payload or {}),
            now_iso(),
        ),
    )
    return event_id


def sdk_fetch_workflow(db: sqlite3.Connection, workflow_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM sdk_workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="SDK workflow not found.")
    return row


def sdk_fetch_owned_workflow(
    db: sqlite3.Connection,
    workflow_id: str,
    api_key_context: Dict[str, Any],
) -> sqlite3.Row:
    row = sdk_fetch_workflow(db, workflow_id)
    if row["project_id"] != api_key_context["project_id"]:
        raise HTTPException(status_code=404, detail="SDK workflow not found for this API key.")
    return row


def sdk_fetch_events(db: sqlite3.Connection, workflow_id: str) -> List[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM sdk_events WHERE workflow_id = ? ORDER BY created_at ASC",
        (workflow_id,),
    ).fetchall()


def sdk_retry_count(events: List[sqlite3.Row]) -> int:
    return sum(
        1
        for event in events
        if event["event_type"] == "recovery"
        or "retry" in str(event["name"] or "").lower()
        or "retry" in str(event["payload_json"] or "").lower()
    )


def sdk_failure_reason_from_events(events: List[sqlite3.Row]) -> str:
    for event in reversed(events):
        if event["event_type"] == "error":
            return event["error_type"] or event["error_message"] or "sdk_error"
        if event["success"] == 0 and event["error_message"]:
            return event["error_message"]
    for event in reversed(events):
        if event["success"] == 0:
            return event["name"] or event["event_type"] or "workflow_failed"
    return "workflow_failed"


def sdk_failure_probability_from_events(events: List[sqlite3.Row]) -> float:
    probability = 0.05
    failed_tool_calls = 0
    failed_model_calls = 0
    error_events = 0
    total_latency = 0
    low_confidence_seen = False
    for event in events:
        event_type = event["event_type"]
        success = event["success"]
        latency_ms = int(event["latency_ms"] or 0)
        confidence = event["confidence"]
        total_latency += latency_ms
        if confidence is not None and float(confidence) < 0.75:
            low_confidence_seen = True
        if event_type == "tool_call" and success == 0:
            failed_tool_calls += 1
        if event_type == "model_call" and success == 0:
            failed_model_calls += 1
        if event_type == "error":
            error_events += 1
    probability += min(0.35, failed_tool_calls * 0.16)
    probability += min(0.30, failed_model_calls * 0.18)
    probability += min(0.35, error_events * 0.20)
    if total_latency > 15000:
        probability += 0.12
    if total_latency > 30000:
        probability += 0.10
    if low_confidence_seen:
        probability += 0.18
    return round(max(0.0, min(0.98, probability)), 4)


def sdk_guardrail_action(probability_of_failure: float) -> Dict[str, Any]:
    if probability_of_failure >= 0.80:
        return {
            "action": "escalate",
            "reason": "High predicted failure risk.",
            "should_continue": False,
        }
    if probability_of_failure >= 0.60:
        return {
            "action": "retry_failed_stage",
            "reason": "Elevated risk; retry the failing stage before continuing.",
            "should_continue": True,
        }
    if probability_of_failure >= 0.40:
        return {
            "action": "increase_observation",
            "reason": "Moderate risk; continue with tighter telemetry.",
            "should_continue": True,
        }
    return {
        "action": "continue",
        "reason": "Risk is currently acceptable.",
        "should_continue": True,
    }


def classify_failure(events: List[sqlite3.Row]) -> Dict[str, Any]:
    low_confidence = False
    timeout_seen = False
    failed_search = False
    failed_extraction = False
    failed_model = False
    failed_tool = False
    reasons: List[str] = []
    max_latency = 0

    for event in events:
        event_type = event["event_type"]
        success = event["success"]
        latency_ms = int(event["latency_ms"] or 0)
        confidence = event["confidence"]
        stage = (event["stage_name"] or "").lower()
        name = (event["name"] or "").lower()
        tool_name = (event["tool_name"] or "").lower()
        error_type = (event["error_type"] or "").lower()
        error_message = (event["error_message"] or "").lower()
        text = " ".join([stage, name, tool_name, error_type, error_message])
        max_latency = max(max_latency, latency_ms)

        if confidence is not None and float(confidence) < 0.75:
            low_confidence = True
            reasons.append("confidence below 0.75")
        if "timeout" in text or latency_ms >= 10000:
            timeout_seen = True
            reasons.append("timeout or high latency signal")
        if event_type == "tool_call" and success == 0:
            failed_tool = True
            if "search" in text:
                failed_search = True
                reasons.append("failed search tool call")
            if "extract" in text or "parse" in text:
                failed_extraction = True
                reasons.append("failed extraction tool call")
        if event_type == "model_call" and success == 0:
            failed_model = True
            reasons.append("failed model call")
        if event_type == "error":
            if "search" in text:
                failed_search = True
                reasons.append("search error")
            if "extract" in text or "parse" in text:
                failed_extraction = True
                reasons.append("extraction error")
            if "model" in text:
                failed_model = True
                reasons.append("model error")
            if "tool" in text:
                failed_tool = True
                reasons.append("tool error")

    if failed_search:
        category = "search_failure"
    elif failed_extraction:
        category = "extraction_failure"
    elif failed_model and timeout_seen:
        category = "model_timeout"
    elif failed_tool and timeout_seen:
        category = "tool_timeout"
    elif failed_model:
        category = "model_failure"
    elif timeout_seen:
        category = "tool_timeout"
    elif low_confidence:
        category = "low_confidence"
    else:
        category = "none"

    return {
        "failure_category": category,
        "reasons": sorted(set(reasons)),
        "max_latency_ms": max_latency,
        "signals": {
            "low_confidence": low_confidence,
            "timeout_seen": timeout_seen,
            "failed_search": failed_search,
            "failed_extraction": failed_extraction,
            "failed_model": failed_model,
            "failed_tool": failed_tool,
        },
    }


def recovery_action_for_category(category: str, attempt_number: int) -> Dict[str, Any]:
    action_matrix = {
        "search_failure": ["switch_provider", "retry_search"],
        "extraction_failure": ["retry_extraction", "switch_extraction_strategy"],
        "model_timeout": ["retry_model", "switch_backup_model"],
        "model_failure": ["retry_model", "switch_backup_model"],
        "tool_timeout": ["retry_tool", "switch_provider"],
        "low_confidence": ["retry_model", "switch_backup_model"],
    }
    actions = action_matrix.get(category, [])
    if not actions:
        return {
            "recovery_action": "none",
            "success": True,
            "reason": "No recoverable failure signal detected.",
            "latency_ms": 0,
        }
    action = actions[min(max(attempt_number - 1, 0), len(actions) - 1)]
    success_probability = {
        "switch_provider": 0.82,
        "retry_search": 0.74,
        "retry_extraction": 0.76,
        "switch_extraction_strategy": 0.84,
        "retry_model": 0.70,
        "switch_backup_model": 0.86,
        "retry_tool": 0.68,
    }.get(action, 0.60)
    success = success_probability >= 0.74 or attempt_number >= 2
    latency_ms = {
        "switch_provider": 900,
        "retry_search": 700,
        "retry_extraction": 950,
        "switch_extraction_strategy": 1300,
        "retry_model": 1800,
        "switch_backup_model": 2300,
        "retry_tool": 900,
    }.get(action, 500)
    return {
        "recovery_action": action,
        "success": success,
        "reason": f"Auto-selected {action} for {category}.",
        "latency_ms": latency_ms,
    }


def insert_recovery_event(
    db: sqlite3.Connection,
    workflow: sqlite3.Row,
    category: str,
    action: Dict[str, Any],
    classifier: Dict[str, Any],
) -> Dict[str, Any]:
    existing_count = int(
        db.execute(
            "SELECT COUNT(*) FROM recovery_events WHERE workflow_id = ?",
            (workflow["workflow_id"],),
        ).fetchone()[0]
    )
    attempt_number = existing_count + 1
    event_id = f"rec_{uuid.uuid4().hex}"
    created_at = now_iso()
    db.execute(
        """
        INSERT INTO recovery_events (
            id, workflow_id, user_id, project_id, api_key_id,
            failure_category, recovery_action, attempt_number, success,
            recovery_latency_ms, reason, created_at, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            workflow["workflow_id"],
            workflow["user_id"],
            workflow["project_id"],
            workflow["api_key_id"],
            category,
            action["recovery_action"],
            attempt_number,
            1 if action["success"] else 0,
            action["latency_ms"],
            action["reason"],
            created_at,
            json.dumps({"classifier": classifier}, sort_keys=True),
        ),
    )
    return {
        "event_id": event_id,
        "workflow_id": workflow["workflow_id"],
        "failure_category": category,
        "recovery_action": action["recovery_action"],
        "attempt_number": attempt_number,
        "success": action["success"],
        "recovery_latency_ms": action["latency_ms"],
        "reason": action["reason"],
        "created_at": created_at,
    }


def recovery_summary(project_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    init_db()
    params: List[Any] = []
    where = ""
    if project_ids is not None:
        if project_ids:
            placeholders = ", ".join("?" for _ in project_ids)
            where = f"WHERE project_id IN ({placeholders})"
            params = list(project_ids)
        else:
            where = "WHERE 1 = 0"
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    today_where = f"{where} {'AND' if where else 'WHERE'} created_at >= ?"
    with connect() as db:
        summary = db.execute(
            f"""
            SELECT COUNT(*) AS recovery_attempts,
                   SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_recoveries,
                   AVG(recovery_latency_ms) AS average_recovery_latency_ms
            FROM recovery_events
            {where}
            """,
            params,
        ).fetchone()
        today = db.execute(
            f"SELECT COUNT(*) AS count FROM recovery_events {today_where}",
            [*params, today_start],
        ).fetchone()
        categories = db.execute(
            f"""
            SELECT failure_category, COUNT(*) AS count
            FROM recovery_events
            {where}
            GROUP BY failure_category
            ORDER BY count DESC, failure_category ASC
            LIMIT 5
            """,
            params,
        ).fetchall()
    attempts = int(summary["recovery_attempts"] or 0)
    successes = int(summary["successful_recoveries"] or 0)
    return {
        "recovery_attempts": attempts,
        "successful_recoveries": successes,
        "recovery_success_rate": round(successes / attempts * 100.0, 2) if attempts else 0.0,
        "average_recovery_latency_ms": round(float(summary["average_recovery_latency_ms"] or 0.0), 2),
        "recoveries_today": int(today["count"] or 0),
        "top_failure_categories": [row_to_dict(row) for row in categories],
    }


def copilot_scope(user_id: Optional[str] = None) -> str:
    return f"user:{user_id}" if user_id else "global"


def scoped_workflow_where(project_ids: Optional[List[str]]) -> tuple[str, List[Any]]:
    if project_ids is None:
        return "", []
    if not project_ids:
        return "WHERE 1 = 0", []
    placeholders = ", ".join("?" for _ in project_ids)
    return f"WHERE project_id IN ({placeholders})", list(project_ids)


def scoped_event_where(project_ids: Optional[List[str]]) -> tuple[str, List[Any]]:
    if project_ids is None:
        return "", []
    if not project_ids:
        return "WHERE 1 = 0", []
    placeholders = ", ".join("?" for _ in project_ids)
    return (
        "WHERE workflow_id IN ("
        "SELECT workflow_id FROM sdk_workflows "
        f"WHERE project_id IN ({placeholders})"
        ")"
    ), list(project_ids)


def bounded_percent(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return round(max(minimum, min(maximum, value)), 2)


def add_copilot_recommendation(
    recommendations: List[Dict[str, Any]],
    *,
    category: str,
    issue: str,
    recommendation: str,
    confidence: float,
    estimated_success_improvement: float,
    evidence: List[str],
) -> None:
    recommendations.append(
        {
            "category": category,
            "issue": issue,
            "recommendation": recommendation,
            "confidence": bounded_percent(confidence),
            "estimated_success_improvement": bounded_percent(estimated_success_improvement),
            "supporting_evidence": evidence,
        }
    )


def copilot_sdk_failure_stats(project_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    init_db()
    workflow_where, workflow_params = scoped_workflow_where(project_ids)
    event_where, event_params = scoped_event_where(project_ids)
    event_prefix = f"{event_where} AND" if event_where else "WHERE"
    timeout_expression = (
        "LOWER(COALESCE(error_type, '') || ' ' || COALESCE(error_message, '') || ' ' || "
        "COALESCE(name, '') || ' ' || COALESCE(tool_name, '') || ' ' || COALESCE(stage_name, ''))"
    )
    with connect() as db:
        workflow_summary = db.execute(
            f"""
            SELECT COUNT(*) AS total_workflows,
                   SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_workflows,
                   SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_workflows,
                   AVG(confidence) AS average_confidence,
                   AVG(total_latency_ms) AS average_latency_ms
            FROM sdk_workflows
            {workflow_where}
            """,
            workflow_params,
        ).fetchone()
        error_rows = db.execute(
            f"""
            SELECT COALESCE(NULLIF(error_type, ''), 'unknown') AS error_type,
                   COUNT(*) AS count
            FROM sdk_events
            {event_prefix} event_type = 'error'
            GROUP BY COALESCE(NULLIF(error_type, ''), 'unknown')
            ORDER BY count DESC
            LIMIT 8
            """,
            event_params,
        ).fetchall()
        failed_stage_rows = db.execute(
            f"""
            SELECT COALESCE(NULLIF(stage_name, ''), 'unknown') AS stage_name,
                   COUNT(*) AS count
            FROM sdk_events
            {event_prefix} success = 0
            GROUP BY COALESCE(NULLIF(stage_name, ''), 'unknown')
            ORDER BY count DESC
            LIMIT 8
            """,
            event_params,
        ).fetchall()
        low_confidence = db.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM sdk_events
            {event_prefix} confidence IS NOT NULL AND confidence < 0.75
            """,
            event_params,
        ).fetchone()
        timeout_count = db.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM sdk_events
            {event_prefix} (latency_ms >= 10000 OR {timeout_expression} LIKE '%timeout%')
            """,
            event_params,
        ).fetchone()
    total = int(workflow_summary["total_workflows"] or 0)
    failed = int(workflow_summary["failed_workflows"] or 0)
    return {
        "total_workflows": total,
        "successful_workflows": int(workflow_summary["successful_workflows"] or 0),
        "failed_workflows": failed,
        "failure_rate": round(failed / total * 100.0, 2) if total else 0.0,
        "average_confidence": round(float(workflow_summary["average_confidence"] or 0.0), 4),
        "average_latency_ms": round(float(workflow_summary["average_latency_ms"] or 0.0), 2),
        "errors": [row_to_dict(row) for row in error_rows],
        "failed_stages": [row_to_dict(row) for row in failed_stage_rows],
        "low_confidence_events": int(low_confidence["count"] or 0),
        "timeout_events": int(timeout_count["count"] or 0),
    }


def generate_copilot_candidates(project_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    recommendations: List[Dict[str, Any]] = []
    sdk_stats = copilot_sdk_failure_stats(project_ids)
    recovery = recovery_summary(project_ids)
    guardrails = dashboard_guardrail_payload()
    models = dashboard_model_leaderboard_payload()
    tools = dashboard_tool_reliability_payload()

    failure_rate = float(sdk_stats["failure_rate"])
    total_workflows = int(sdk_stats["total_workflows"])
    if total_workflows and failure_rate >= 15:
        top_stage = sdk_stats["failed_stages"][0] if sdk_stats["failed_stages"] else {"stage_name": "unknown", "count": 0}
        add_copilot_recommendation(
            recommendations,
            category="workflow",
            issue=f"SDK workflows are failing at {failure_rate:.2f}%.",
            recommendation=f"Add retry and guardrail checks around the {top_stage['stage_name']} stage.",
            confidence=55 + min(35, failure_rate * 0.6),
            estimated_success_improvement=min(25, failure_rate * 0.35),
            evidence=[
                f"{sdk_stats['failed_workflows']} of {total_workflows} SDK workflows failed.",
                f"Highest failed stage: {top_stage['stage_name']} ({top_stage['count']} failed events).",
            ],
        )

    total_errors = sum(int(item["count"] or 0) for item in sdk_stats["errors"])
    for error in sdk_stats["errors"][:3]:
        error_type = str(error["error_type"]).lower()
        count = int(error["count"] or 0)
        share = count / max(1, total_errors) * 100.0
        if "search" in error_type:
            add_copilot_recommendation(
                recommendations,
                category="search",
                issue=f"Search failures are a repeated workflow error ({count} events).",
                recommendation="Use a backup search provider and retry search before failing the workflow.",
                confidence=65 + min(25, share * 0.4),
                estimated_success_improvement=min(18, share * 0.25 + 4),
                evidence=[f"Error category {error['error_type']} accounts for {share:.2f}% of logged SDK errors."],
            )
        elif "extract" in error_type or "parsing" in error_type:
            add_copilot_recommendation(
                recommendations,
                category="extraction",
                issue=f"Extraction failures are a repeated workflow error ({count} events).",
                recommendation="Use a backup extractor and switch extraction strategy after the first failed attempt.",
                confidence=65 + min(25, share * 0.4),
                estimated_success_improvement=min(18, share * 0.25 + 4),
                evidence=[f"Error category {error['error_type']} accounts for {share:.2f}% of logged SDK errors."],
            )
        elif "timeout" in error_type:
            add_copilot_recommendation(
                recommendations,
                category="timeout",
                issue=f"Timeouts are a repeated workflow error ({count} events).",
                recommendation="Increase timeout for slow stages and retry once before escalating.",
                confidence=62 + min(25, share * 0.4),
                estimated_success_improvement=min(16, share * 0.2 + 3),
                evidence=[f"Timeout-like SDK errors account for {share:.2f}% of logged SDK errors."],
            )

    recovery_attempts = int(recovery["recovery_attempts"])
    for category_row in recovery["top_failure_categories"][:4]:
        category = str(category_row["failure_category"])
        count = int(category_row["count"] or 0)
        share = count / max(1, recovery_attempts) * 100.0
        if category == "search_failure":
            issue = f"Search recovery is being triggered in {share:.2f}% of recovery attempts."
            recommendation = "Configure a backup search provider and prefer provider switching on first failure."
            rec_category = "search"
        elif category == "extraction_failure":
            issue = f"Extraction recovery is being triggered in {share:.2f}% of recovery attempts."
            recommendation = "Use a backup extractor and switch extraction strategy after one failed extraction."
            rec_category = "extraction"
        elif category in {"model_timeout", "model_failure"}:
            issue = f"Model recovery is being triggered for {category}."
            recommendation = "Retry the model once, then switch to the highest-ranked backup model."
            rec_category = "model"
        elif category == "tool_timeout":
            issue = "Tool timeouts are causing automatic recovery attempts."
            recommendation = "Increase tool timeout and add one provider-level retry before escalation."
            rec_category = "tool"
        elif category == "low_confidence":
            issue = "Low-confidence outputs are reaching the recovery layer."
            recommendation = "Add confidence gating and retry low-confidence model calls with a backup model."
            rec_category = "confidence"
        else:
            issue = f"{category} is appearing in recovery attempts."
            recommendation = "Add a targeted recovery path for this failure category."
            rec_category = "workflow"
        add_copilot_recommendation(
            recommendations,
            category=rec_category,
            issue=issue,
            recommendation=recommendation,
            confidence=60 + min(30, share * 0.4),
            estimated_success_improvement=min(20, share * max(0.1, recovery["recovery_success_rate"] / 500.0) + 3),
            evidence=[
                f"{count} of {recovery_attempts} recovery attempts were {category}.",
                f"Current recovery success rate: {recovery['recovery_success_rate']:.2f}%.",
            ],
        )

    if recovery_attempts and float(recovery["recovery_success_rate"]) < 70:
        add_copilot_recommendation(
            recommendations,
            category="recovery",
            issue=f"Auto-recovery success is only {recovery['recovery_success_rate']:.2f}%.",
            recommendation="Add a second recovery action for each top failure category before escalation.",
            confidence=76,
            estimated_success_improvement=12,
            evidence=[
                f"{recovery['successful_recoveries']} of {recovery_attempts} recovery attempts succeeded.",
                "Failed recoveries mean the first recovery action is not enough.",
            ],
        )

    intervention_rate = float(guardrails.get("intervention_rate", 0) or 0)
    if intervention_rate >= 20:
        add_copilot_recommendation(
            recommendations,
            category="guardrail",
            issue=f"Guardrails intervene in {intervention_rate:.2f}% of evaluated workflows.",
            recommendation="Move validation earlier in the workflow and add preflight checks before expensive stages.",
            confidence=72,
            estimated_success_improvement=min(14, intervention_rate * 0.2),
            evidence=[
                f"{guardrails.get('interventions', 0)} guardrail interventions recorded.",
                f"{guardrails.get('prevented_failures', 0)} failures were prevented.",
            ],
        )

    if len(models) >= 2:
        best = models[0]
        worst_candidates = [
            model for model in models[1:]
            if float(best["success_rate"] or 0) - float(model["success_rate"] or 0) >= 5
            or float(best["reliability_score_v2"] or 0) - float(model["reliability_score_v2"] or 0) >= 5
        ]
        if worst_candidates:
            worst = worst_candidates[-1]
            success_gap = float(best["success_rate"] or 0) - float(worst["success_rate"] or 0)
            score_gap = float(best["reliability_score_v2"] or 0) - float(worst["reliability_score_v2"] or 0)
            add_copilot_recommendation(
                recommendations,
                category="model",
                issue=f"Model {worst['model']} trails {best['model']} by {success_gap:.2f} success points.",
                recommendation=f"Switch production traffic from {worst['model']} to {best['model']} for similar workflows.",
                confidence=68 + min(22, max(success_gap, score_gap) * 0.8),
                estimated_success_improvement=max(0.0, min(30, success_gap)),
                evidence=[
                    f"{best['model']} reliability score: {float(best['reliability_score_v2'] or 0):.2f}.",
                    f"{worst['model']} reliability score: {float(worst['reliability_score_v2'] or 0):.2f}.",
                    f"Success-rate gap: {success_gap:.2f} percentage points.",
                ],
            )
    elif len(models) == 1 and float(models[0]["reliability_score_v2"] or 0) < 80:
        add_copilot_recommendation(
            recommendations,
            category="model",
            issue=f"Only one model is benchmarked and its reliability score is {float(models[0]['reliability_score_v2'] or 0):.2f}.",
            recommendation="Benchmark a backup model so model switching is available during failures.",
            confidence=70,
            estimated_success_improvement=8,
            evidence=["Single-model systems have no fallback path when the model times out or underperforms."],
        )

    for model in models[:5]:
        timeout_rate = float(model.get("timeout_rate", 0) or 0)
        if timeout_rate >= 8:
            add_copilot_recommendation(
                recommendations,
                category="model",
                issue=f"Model {model['model']} has a {timeout_rate:.2f}% timeout rate.",
                recommendation=f"Increase timeout for {model['model']} or route slow workflows to a backup model.",
                confidence=70 + min(20, timeout_rate),
                estimated_success_improvement=min(15, timeout_rate * 0.5),
                evidence=[
                    f"{model['model']} timeout rate: {timeout_rate:.2f}%.",
                    f"Average execution time: {float(model['average_execution_time_ms'] or 0):.2f} ms.",
                ],
            )

    for tool in tools[:6]:
        success_rate = float(tool.get("success_rate", 0) or 0)
        failure_rate_tool = float(tool.get("failure_rate", 0) or 0)
        timeout_rate = float(tool.get("timeout_rate", 0) or 0)
        if success_rate < 95 or timeout_rate >= 5:
            name = str(tool["tool_name"])
            lowered = name.lower()
            if "search" in lowered:
                recommendation = "Use a backup search provider and retry failed search requests once."
                category = "search"
            elif "extract" in lowered:
                recommendation = "Use a backup extractor and switch parsing strategy on invalid extraction output."
                category = "extraction"
            else:
                recommendation = "Add retry with backoff and provider fallback for this tool."
                category = "tool"
            add_copilot_recommendation(
                recommendations,
                category=category,
                issue=f"Tool {name} reliability is {float(tool['reliability_score'] or 0):.2f}.",
                recommendation=recommendation,
                confidence=66 + min(22, failure_rate_tool + timeout_rate),
                estimated_success_improvement=min(18, failure_rate_tool * 0.35 + timeout_rate * 0.25),
                evidence=[
                    f"Tool success rate: {success_rate:.2f}%.",
                    f"Tool failure rate: {failure_rate_tool:.2f}%.",
                    f"Tool timeout rate: {timeout_rate:.2f}%.",
                ],
            )

    if not recommendations:
        add_copilot_recommendation(
            recommendations,
            category="monitoring",
            issue="No urgent reliability weakness is currently visible.",
            recommendation="Continue monitoring and collect more workflow data before changing routing or recovery rules.",
            confidence=82,
            estimated_success_improvement=0,
            evidence=[
                "No high failure-rate, timeout, recovery, guardrail, model, or tool reliability threshold was crossed.",
            ],
        )

    deduped: Dict[str, Dict[str, Any]] = {}
    for recommendation in recommendations:
        key = f"{recommendation['category']}|{recommendation['issue']}|{recommendation['recommendation']}"
        existing = deduped.get(key)
        if existing is None or recommendation["confidence"] > existing["confidence"]:
            deduped[key] = recommendation
    return sorted(
        deduped.values(),
        key=lambda item: (item["confidence"], item["estimated_success_improvement"]),
        reverse=True,
    )


def copilot_recommendations_from_db(scope: str = "global", limit: int = 10) -> List[Dict[str, Any]]:
    init_db()
    with connect() as db:
        rows = db.execute(
            """
            SELECT id, scope, user_id, project_id, category, issue, recommendation,
                   confidence, estimated_success_improvement,
                   supporting_evidence_json, status, source, created_at, updated_at
            FROM recommendations
            WHERE scope = ?
            ORDER BY confidence DESC, estimated_success_improvement DESC, updated_at DESC
            LIMIT ?
            """,
            (scope, limit),
        ).fetchall()
    recommendations = []
    for row in rows:
        item = row_to_dict(row)
        try:
            item["supporting_evidence"] = json.loads(item.pop("supporting_evidence_json") or "[]")
        except json.JSONDecodeError:
            item["supporting_evidence"] = []
        recommendations.append(item)
    return recommendations


def refresh_copilot_recommendations(
    project_ids: Optional[List[str]] = None,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    scope = copilot_scope(user_id)
    now = now_iso()
    candidates = generate_copilot_candidates(project_ids)
    init_db()
    with connect() as db:
        db.execute("DELETE FROM recommendations WHERE scope = ?", (scope,))
        for item in candidates:
            fingerprint = hashlib.sha1(
                f"{scope}|{item['category']}|{item['issue']}|{item['recommendation']}".encode("utf-8")
            ).hexdigest()[:24]
            db.execute(
                """
                INSERT INTO recommendations (
                    id, scope, user_id, project_id, category, issue, recommendation,
                    confidence, estimated_success_improvement, supporting_evidence_json,
                    status, source, created_at, updated_at
                )
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, 'open', 'reliability_copilot', ?, ?)
                """,
                (
                    f"rec_{fingerprint}",
                    scope,
                    user_id,
                    item["category"],
                    item["issue"],
                    item["recommendation"],
                    item["confidence"],
                    item["estimated_success_improvement"],
                    json.dumps(item["supporting_evidence"], ensure_ascii=False),
                    now,
                    now,
                ),
            )
    return copilot_recommendations_from_db(scope)


def copilot_recommendations_payload(
    project_ids: Optional[List[str]] = None,
    user_id: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    scope = copilot_scope(user_id)
    refreshed = refresh_copilot_recommendations(project_ids, user_id)
    if len(refreshed) >= limit:
        return refreshed[:limit]
    return copilot_recommendations_from_db(scope, limit)


def copilot_summary_payload(
    project_ids: Optional[List[str]] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    recommendations = copilot_recommendations_payload(project_ids, user_id, limit=10)
    if not recommendations:
        return {
            "recommendation_count": 0,
            "average_confidence": 0.0,
            "total_estimated_success_improvement": 0.0,
            "top_category": None,
            "top_recommendation": None,
        }
    category_counts: Dict[str, int] = {}
    for item in recommendations:
        category_counts[item["category"]] = category_counts.get(item["category"], 0) + 1
    top_category = sorted(category_counts.items(), key=lambda pair: pair[1], reverse=True)[0][0]
    return {
        "recommendation_count": len(recommendations),
        "average_confidence": round(
            sum(float(item["confidence"] or 0) for item in recommendations) / len(recommendations),
            2,
        ),
        "total_estimated_success_improvement": round(
            sum(float(item["estimated_success_improvement"] or 0) for item in recommendations[:5]),
            2,
        ),
        "top_category": top_category,
        "top_recommendation": recommendations[0],
    }


def copilot_dashboard_payload(
    project_ids: Optional[List[str]] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    recommendations = copilot_recommendations_payload(project_ids, user_id, limit=8)
    summary = copilot_summary_payload(project_ids, user_id)
    return {
        "summary": summary,
        "recommendations": recommendations,
    }


def optimizer_evidence_snapshot(project_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "failures": copilot_sdk_failure_stats(project_ids),
        "recoveries": recovery_summary(project_ids),
        "guardrails": dashboard_guardrail_payload(),
        "models": dashboard_model_leaderboard_payload()[:5],
        "tools": dashboard_tool_reliability_payload()[:5],
    }


def optimizer_target_from_recommendation(
    recommendation: Dict[str, Any],
    action_type: str,
    evidence: Dict[str, Any],
) -> str:
    category = str(recommendation.get("category") or "workflow")
    models = evidence.get("models", [])
    if action_type == "switch_model" and models:
        return f"model:{models[0].get('model', 'best_available')}"
    if action_type == "switch_provider":
        if category == "search":
            return "provider:search"
        if category == "extraction":
            return "provider:extraction"
        return "provider:tool"
    if action_type == "increase_timeout":
        return f"timeout:{category}"
    if action_type == "add_retry":
        return f"retry:{category}"
    if action_type == "enable_backup_strategy":
        return f"backup:{category}"
    return f"workflow:{category}"


def optimizer_action_from_recommendation(
    recommendation: Dict[str, Any],
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    category = str(recommendation.get("category") or "workflow").lower()
    issue = str(recommendation.get("issue") or "")
    text = f"{issue} {recommendation.get('recommendation') or ''}".lower()

    if "increase timeout" in text or "timeout" in text:
        action_type = "increase_timeout"
    elif "switch production traffic" in text or "switch model" in text:
        action_type = "switch_model"
    elif "provider" in text:
        action_type = "switch_provider"
    elif "retry" in text:
        action_type = "add_retry"
    elif "backup" in text or "fallback" in text:
        action_type = "enable_backup_strategy"
    elif category == "model":
        action_type = "switch_model"
    elif category in {"search", "extraction", "tool"}:
        action_type = "switch_provider"
    else:
        action_type = "add_retry"

    target = optimizer_target_from_recommendation(recommendation, action_type, evidence)
    previous_state = {
        "action_type": action_type,
        "target": target,
        "mode": "baseline",
        "source_issue": issue,
    }
    if action_type == "switch_model":
        models = evidence.get("models", [])
        previous_state["model"] = "current_or_underperforming"
        new_state = {
            "model": models[0].get("model", "best_available") if models else "best_available",
            "routing": "prefer_highest_reliability_model",
        }
    elif action_type == "switch_provider":
        new_state = {
            "provider_strategy": "fallback_provider_enabled",
            "target": target,
        }
    elif action_type == "increase_timeout":
        new_state = {
            "timeout_multiplier": 1.5,
            "target": target,
        }
    elif action_type == "add_retry":
        new_state = {
            "max_retries": 2,
            "retry_backoff": "exponential",
            "target": target,
        }
    else:
        new_state = {
            "backup_strategy": "enabled",
            "target": target,
        }

    return {
        "action_type": action_type,
        "target": target,
        "previous_state": previous_state,
        "new_state": new_state,
        "reason": f"Selected {action_type} from recommendation {recommendation.get('id')}.",
    }


def normalize_risk_level(value: Optional[str]) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"low", "medium", "high"}:
        return normalized
    return "medium"


def infer_decision_risk(action: Dict[str, Any], recommendation: Optional[Dict[str, Any]] = None) -> str:
    action_type = str(action.get("action_type") or "").lower()
    target = str(action.get("target") or "").lower()
    category = str((recommendation or {}).get("category") or "").lower()
    improvement = float((recommendation or {}).get("estimated_success_improvement") or 0.0)
    high_terms = {"production", "billing", "payment", "legal", "security", "compliance", "database"}
    if action_type in {"switch_model", "switch_provider"}:
        return "high"
    if category in {"security", "compliance", "legal"}:
        return "high"
    if any(term in target for term in high_terms):
        return "high"
    if improvement >= 50.0:
        return "high"
    if action_type in {"increase_timeout", "enable_backup_strategy"}:
        return "medium"
    return "low"


def rollback_plan_is_reversible(action: Dict[str, Any], rollback_plan: Dict[str, Any]) -> bool:
    if not rollback_plan:
        return False
    return bool(
        rollback_plan.get("previous_state")
        or rollback_plan.get("new_state")
        or action.get("previous_state")
        or action.get("new_state")
    )


def rule_based_decision_checks(
    *,
    action: Dict[str, Any],
    confidence: float,
    rollback_plan: Dict[str, Any],
    risk_level: str,
    confidence_threshold: float = 90.0,
) -> List[Dict[str, Any]]:
    action_type = str(action.get("action_type") or "")
    target = str(action.get("target") or "")
    rollback_supported = rollback_plan_is_reversible(action, rollback_plan)
    allowed_actions = {
        "add_retry",
        "increase_timeout",
        "switch_model",
        "switch_provider",
        "enable_backup_strategy",
        "rollback",
    }
    restricted_targets = {"payment", "credential", "secret", "private_key", "delete_database"}
    checks = [
        {
            "name": "allowed_action",
            "passed": action_type in allowed_actions,
            "detail": f"Action type '{action_type}' is allowed." if action_type in allowed_actions else f"Action type '{action_type}' is not allowed.",
        },
        {
            "name": "target_present",
            "passed": bool(target),
            "detail": "Target is present." if target else "Target is missing.",
        },
        {
            "name": "confidence_threshold",
            "passed": confidence >= confidence_threshold,
            "detail": f"Confidence {confidence:.2f} must be at least {confidence_threshold:.2f}.",
        },
        {
            "name": "rollback_supported",
            "passed": rollback_supported,
            "detail": "Rollback plan includes reversible state." if rollback_supported else "Rollback plan is missing reversible state.",
        },
        {
            "name": "restricted_target",
            "passed": not any(term in target.lower() for term in restricted_targets),
            "detail": "Target does not match restricted action surfaces.",
        },
        {
            "name": "risk_level_valid",
            "passed": risk_level in {"low", "medium", "high"},
            "detail": f"Risk level is {risk_level}.",
        },
    ]
    return checks


def second_model_verify_decision(
    *,
    action: Dict[str, Any],
    confidence: float,
    rule_checks: List[Dict[str, Any]],
    risk_level: str,
) -> Dict[str, Any]:
    failed_rules = [check for check in rule_checks if not check["passed"]]
    action_type = str(action.get("action_type") or "")
    verifier_confidence = max(0.0, min(100.0, confidence - (len(failed_rules) * 20.0)))
    if failed_rules:
        status = "rejected"
        reason = "Verifier rejected because one or more safety rules failed."
    elif risk_level == "high":
        status = "approved_with_human_required"
        reason = "Verifier agrees, but high-risk actions require human approval."
    else:
        status = "approved"
        reason = "Verifier agrees with the proposed reliability action."
    return {
        "verifier_type": "second_model",
        "verifier_name": "meta-verifier-v1",
        "status": status,
        "confidence": round(verifier_confidence, 2),
        "details": {
            "reason": reason,
            "risk_level": risk_level,
            "action_type": action_type,
            "failed_rules": [check["name"] for check in failed_rules],
        },
    }


def decision_status_from_validation(
    *,
    risk_level: str,
    rule_checks: List[Dict[str, Any]],
    second_verification: Dict[str, Any],
) -> str:
    if any(not check["passed"] for check in rule_checks):
        return "rejected"
    if second_verification["status"] == "rejected":
        return "rejected"
    if risk_level == "high":
        return "pending_human"
    if risk_level == "medium":
        return "approved_second_model"
    return "approved_auto"


def insert_decision_verification(
    db: sqlite3.Connection,
    *,
    decision_id: str,
    verifier_type: str,
    verifier_name: str,
    status: str,
    confidence: float,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    verification_id = f"ver_{uuid.uuid4().hex}"
    created_at = now_iso()
    db.execute(
        """
        INSERT INTO decision_verifications (
            id, decision_id, verifier_type, verifier_name,
            status, confidence, details_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            verification_id,
            decision_id,
            verifier_type,
            verifier_name,
            status,
            confidence,
            json_dumps(details),
            created_at,
        ),
    )
    return {
        "id": verification_id,
        "decision_id": decision_id,
        "verifier_type": verifier_type,
        "verifier_name": verifier_name,
        "status": status,
        "confidence": confidence,
        "details": details,
        "created_at": created_at,
    }


def validate_ai_decision(
    db: sqlite3.Connection,
    *,
    recommendation: Optional[Dict[str, Any]],
    action: Dict[str, Any],
    source: str = "reliability_copilot",
    risk_level: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    confidence = float((recommendation or {}).get("confidence") or action.get("confidence") or 0.0)
    inferred_risk = infer_decision_risk(action, recommendation)
    final_risk = normalize_risk_level(risk_level or inferred_risk)
    rollback_plan = action.get("rollback_plan") or {
        "action_type": "rollback",
        "target": action.get("target"),
        "previous_state": action.get("new_state", {}),
        "new_state": action.get("previous_state", {}),
        "reason": f"Reverse {action.get('action_type')} on {action.get('target')}.",
    }
    rule_checks = rule_based_decision_checks(
        action=action,
        confidence=confidence,
        rollback_plan=rollback_plan,
        risk_level=final_risk,
    )
    rule_status = "approved" if all(check["passed"] for check in rule_checks) else "rejected"
    second_verification = second_model_verify_decision(
        action=action,
        confidence=confidence,
        rule_checks=rule_checks,
        risk_level=final_risk,
    )
    status = decision_status_from_validation(
        risk_level=final_risk,
        rule_checks=rule_checks,
        second_verification=second_verification,
    )
    decision_id = f"dec_{uuid.uuid4().hex}"
    created_at = now_iso()
    rollback_supported = rollback_plan_is_reversible(action, rollback_plan)
    autonomous_allowed = status in {"approved_auto", "approved_second_model"}
    db.execute(
        """
        INSERT INTO ai_decisions (
            id, recommendation_id, optimization_event_id, source,
            action_type, target, risk_level, confidence, status,
            rollback_supported, autonomous_allowed, human_approval_required,
            second_model_required, reason, rule_checks_json, action_json,
            rollback_plan_json, created_at, updated_at, metadata_json
        )
        VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision_id,
            (recommendation or {}).get("id"),
            source,
            str(action.get("action_type") or ""),
            str(action.get("target") or ""),
            final_risk,
            confidence,
            status,
            1 if rollback_supported else 0,
            1 if autonomous_allowed else 0,
            1 if status == "pending_human" else 0,
            str(action.get("reason") or (recommendation or {}).get("recommendation") or "AI reliability decision."),
            json_dumps(rule_checks),
            json_dumps(action),
            json_dumps(rollback_plan),
            created_at,
            created_at,
            json_dumps(metadata or {}),
        ),
    )
    verifications = [
        insert_decision_verification(
            db,
            decision_id=decision_id,
            verifier_type="rule_based",
            verifier_name="meta_safety_rules_v1",
            status=rule_status,
            confidence=100.0 if rule_status == "approved" else 0.0,
            details={"checks": rule_checks},
        ),
        insert_decision_verification(
            db,
            decision_id=decision_id,
            verifier_type=second_verification["verifier_type"],
            verifier_name=second_verification["verifier_name"],
            status=second_verification["status"],
            confidence=second_verification["confidence"],
            details=second_verification["details"],
        ),
        insert_decision_verification(
            db,
            decision_id=decision_id,
            verifier_type="confidence_threshold",
            verifier_name="confidence_gate_v1",
            status="approved" if confidence >= 90.0 else "rejected",
            confidence=confidence,
            details={"threshold": 90.0, "actual": confidence},
        ),
    ]
    return {
        "id": decision_id,
        "recommendation_id": (recommendation or {}).get("id"),
        "source": source,
        "action_type": str(action.get("action_type") or ""),
        "target": str(action.get("target") or ""),
        "risk_level": final_risk,
        "confidence": confidence,
        "status": status,
        "rollback_supported": rollback_supported,
        "autonomous_allowed": autonomous_allowed,
        "human_approval_required": status == "pending_human",
        "reason": str(action.get("reason") or (recommendation or {}).get("recommendation") or "AI reliability decision."),
        "rule_checks": rule_checks,
        "action": action,
        "rollback_plan": rollback_plan,
        "verifications": verifications,
        "created_at": created_at,
        "updated_at": created_at,
        "metadata": metadata or {},
    }


def decision_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    item = row_to_dict(row)
    item["rollback_supported"] = bool(item["rollback_supported"])
    item["autonomous_allowed"] = bool(item["autonomous_allowed"])
    item["human_approval_required"] = bool(item["human_approval_required"])
    item["second_model_required"] = bool(item["second_model_required"])
    item["rule_checks"] = row_json_list(row, "rule_checks_json")
    item["action"] = row_json_object(row, "action_json")
    item["rollback_plan"] = row_json_object(row, "rollback_plan_json")
    item["metadata"] = row_json_object(row, "metadata_json")
    for key in ["rule_checks_json", "action_json", "rollback_plan_json", "metadata_json"]:
        item.pop(key, None)
    return item


def decision_verifications(db: sqlite3.Connection, decision_id: str) -> List[Dict[str, Any]]:
    rows = db.execute(
        """
        SELECT *
        FROM decision_verifications
        WHERE decision_id = ?
        ORDER BY created_at ASC
        """,
        (decision_id,),
    ).fetchall()
    verifications = []
    for row in rows:
        item = row_to_dict(row)
        item["details"] = row_json_object(row, "details_json")
        item.pop("details_json", None)
        verifications.append(item)
    return verifications


def decision_with_verifications(db: sqlite3.Connection, decision_id: str) -> Dict[str, Any]:
    row = db.execute("SELECT * FROM ai_decisions WHERE id = ?", (decision_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="AI decision not found.")
    decision = decision_row_to_dict(row)
    decision["verifications"] = decision_verifications(db, decision_id)
    return decision


def pending_decisions_payload(limit: int = 50) -> List[Dict[str, Any]]:
    init_db()
    with connect() as db:
        rows = db.execute(
            """
            SELECT *
            FROM ai_decisions
            WHERE status = 'pending_human'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        decisions = [decision_row_to_dict(row) for row in rows]
        for decision in decisions:
            decision["verifications"] = decision_verifications(db, decision["id"])
    return decisions


def record_human_decision(
    *,
    decision_id: str,
    approver_user_id: str,
    approved: bool,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        existing = db.execute("SELECT * FROM ai_decisions WHERE id = ?", (decision_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="AI decision not found.")
        decision = decision_row_to_dict(existing)
        if decision["status"] != "pending_human":
            raise HTTPException(status_code=400, detail="Only pending human decisions can be approved or rejected.")
        approval_id = f"app_{uuid.uuid4().hex}"
        created_at = now_iso()
        final_status = "approved_human" if approved else "rejected_human"
        db.execute(
            """
            INSERT INTO human_approvals (
                id, decision_id, approver_user_id, decision, reason, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                decision_id,
                approver_user_id,
                "approved" if approved else "rejected",
                reason,
                created_at,
            ),
        )
        db.execute(
            """
            UPDATE ai_decisions
            SET status = ?, autonomous_allowed = ?, human_approval_required = 0, updated_at = ?
            WHERE id = ?
            """,
            (final_status, 1 if approved else 0, created_at, decision_id),
        )
        updated = decision_with_verifications(db, decision_id)
        approvals = db.execute(
            """
            SELECT *
            FROM human_approvals
            WHERE decision_id = ?
            ORDER BY created_at DESC
            """,
            (decision_id,),
        ).fetchall()
    updated["human_approvals"] = [row_to_dict(row) for row in approvals]
    return updated


def meta_reliability_dashboard_payload(limit: int = 8) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        summary = db.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'pending_human' THEN 1 ELSE 0 END) AS pending_human,
                   SUM(CASE WHEN status IN ('rejected', 'rejected_human') THEN 1 ELSE 0 END) AS rejected,
                   SUM(CASE WHEN status IN ('approved_auto', 'approved_second_model', 'approved_human') THEN 1 ELSE 0 END) AS approved,
                   SUM(CASE WHEN risk_level = 'high' THEN 1 ELSE 0 END) AS high_risk
            FROM ai_decisions
            """
        ).fetchone()
        rows = db.execute(
            """
            SELECT *
            FROM ai_decisions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        rejected_rows = db.execute(
            """
            SELECT *
            FROM ai_decisions
            WHERE status IN ('rejected', 'rejected_human')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    decisions = [decision_row_to_dict(row) for row in rows]
    rejected = [decision_row_to_dict(row) for row in rejected_rows]
    return {
        "total_decisions": int(summary["total"] or 0),
        "pending_human": int(summary["pending_human"] or 0),
        "rejected_unsafe": int(summary["rejected"] or 0),
        "approved": int(summary["approved"] or 0),
        "high_risk": int(summary["high_risk"] or 0),
        "recent_decisions": decisions,
        "rejected_actions": rejected,
    }


def recommendation_by_id(db: sqlite3.Connection, recommendation_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not recommendation_id:
        return None
    row = db.execute("SELECT * FROM recommendations WHERE id = ?", (recommendation_id,)).fetchone()
    if not row:
        return None
    item = row_to_dict(row)
    item["supporting_evidence"] = row_json_list(row, "supporting_evidence_json")
    item.pop("supporting_evidence_json", None)
    return item


def row_json_object(row: sqlite3.Row, column: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(row[column] or "{}")
    except json.JSONDecodeError:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def row_json_list(row: sqlite3.Row, column: str) -> List[Any]:
    try:
        parsed = json.loads(row[column] or "[]")
    except json.JSONDecodeError:
        parsed = []
    return parsed if isinstance(parsed, list) else []


def insert_optimization_event(
    db: sqlite3.Connection,
    *,
    recommendation: Optional[Dict[str, Any]],
    action: Dict[str, Any],
    dry_run: bool,
    scope: str = "global",
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    rollback_event_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event_id = f"opt_{uuid.uuid4().hex}"
    created_at = now_iso()
    confidence = float((recommendation or {}).get("confidence") or action.get("confidence") or 0.0)
    improvement = float(
        (recommendation or {}).get("estimated_success_improvement")
        or action.get("estimated_success_improvement")
        or 0.0
    )
    status = "dry_run" if dry_run else "applied"
    recommendation_id = (recommendation or {}).get("id")
    supporting_evidence = (recommendation or {}).get("supporting_evidence") or action.get("supporting_evidence") or []
    db.execute(
        """
        INSERT INTO optimization_events (
            id, recommendation_id, scope, user_id, project_id,
            action_type, target, confidence, estimated_success_improvement,
            dry_run, status, success, rollback_supported, rollback_event_id,
            previous_state_json, new_state_json, supporting_evidence_json,
            reason, created_at, rolled_back_at, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (
            event_id,
            recommendation_id,
            scope,
            user_id,
            project_id,
            action["action_type"],
            action["target"],
            confidence,
            improvement,
            1 if dry_run else 0,
            status,
            rollback_event_id,
            json_dumps(action.get("previous_state", {})),
            json_dumps(action.get("new_state", {})),
            json.dumps(supporting_evidence, ensure_ascii=False),
            action["reason"],
            created_at,
            json_dumps(metadata or {}),
        ),
    )
    return {
        "id": event_id,
        "recommendation_id": recommendation_id,
        "scope": scope,
        "user_id": user_id,
        "project_id": project_id,
        "action_type": action["action_type"],
        "target": action["target"],
        "confidence": confidence,
        "estimated_success_improvement": improvement,
        "dry_run": dry_run,
        "status": status,
        "success": True,
        "rollback_supported": True,
        "rollback_event_id": rollback_event_id,
        "previous_state": action.get("previous_state", {}),
        "new_state": action.get("new_state", {}),
        "supporting_evidence": supporting_evidence,
        "reason": action["reason"],
        "created_at": created_at,
        "metadata": metadata or {},
    }


def run_optimizer(
    *,
    dry_run: bool = True,
    min_confidence: float = 90.0,
    limit: int = 5,
    project_ids: Optional[List[str]] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    scope = copilot_scope(user_id)
    evidence = optimizer_evidence_snapshot(project_ids)
    recommendations = copilot_recommendations_payload(project_ids, user_id, limit=max(limit * 2, 10))
    eligible = [
        recommendation for recommendation in recommendations
        if float(recommendation.get("confidence") or 0.0) >= min_confidence
    ][:limit]
    skipped = [
        {
            "id": recommendation.get("id"),
            "confidence": recommendation.get("confidence"),
            "issue": recommendation.get("issue"),
        }
        for recommendation in recommendations
        if float(recommendation.get("confidence") or 0.0) < min_confidence
    ]
    events: List[Dict[str, Any]] = []
    decisions: List[Dict[str, Any]] = []
    init_db()
    with connect() as db:
        for recommendation in eligible:
            action = optimizer_action_from_recommendation(recommendation, evidence)
            decision = validate_ai_decision(
                db,
                recommendation=recommendation,
                action=action,
                source="autonomous_optimizer",
                metadata={
                    "optimizer": "autonomous_reliability_agent",
                    "min_confidence": min_confidence,
                    "dry_run": dry_run,
                    "evidence_snapshot": evidence,
                },
            )
            decisions.append(
                {
                    "id": decision["id"],
                    "recommendation_id": decision["recommendation_id"],
                    "action_type": decision["action_type"],
                    "target": decision["target"],
                    "risk_level": decision["risk_level"],
                    "status": decision["status"],
                    "autonomous_allowed": decision["autonomous_allowed"],
                    "human_approval_required": decision["human_approval_required"],
                }
            )
            if decision["autonomous_allowed"]:
                event = insert_optimization_event(
                    db,
                    recommendation=recommendation,
                    action=action,
                    dry_run=dry_run,
                    scope=scope,
                    user_id=user_id,
                    metadata={
                        "optimizer": "autonomous_reliability_agent",
                        "min_confidence": min_confidence,
                        "evidence_snapshot": evidence,
                        "meta_decision_id": decision["id"],
                    },
                )
                db.execute(
                    """
                    UPDATE ai_decisions
                    SET optimization_event_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (event["id"], now_iso(), decision["id"]),
                )
                events.append(compact_optimization_event(event))
            else:
                skipped.append(
                    {
                        "id": recommendation.get("id"),
                        "confidence": recommendation.get("confidence"),
                        "issue": recommendation.get("issue"),
                        "decision_id": decision["id"],
                        "decision_status": decision["status"],
                        "risk_level": decision["risk_level"],
                    }
                )
    return {
        "dry_run": dry_run,
        "min_confidence": min_confidence,
        "eligible_recommendations": len(eligible),
        "skipped_recommendations": len(skipped),
        "events": events,
        "decisions": decisions,
        "skipped": skipped[:10],
    }


def optimization_event_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    item = row_to_dict(row)
    item["dry_run"] = bool(item["dry_run"])
    item["success"] = bool(item["success"])
    item["rollback_supported"] = bool(item["rollback_supported"])
    item["previous_state"] = row_json_object(row, "previous_state_json")
    item["new_state"] = row_json_object(row, "new_state_json")
    item["supporting_evidence"] = row_json_list(row, "supporting_evidence_json")
    item["metadata"] = row_json_object(row, "metadata_json")
    for key in ["previous_state_json", "new_state_json", "supporting_evidence_json", "metadata_json"]:
        item.pop(key, None)
    return item


def compact_optimization_event(event: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(event)
    item.pop("metadata", None)
    return item


def optimizer_history_payload(limit: int = 20) -> List[Dict[str, Any]]:
    init_db()
    with connect() as db:
        rows = db.execute(
            """
            SELECT *
            FROM optimization_events
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [compact_optimization_event(optimization_event_to_dict(row)) for row in rows]


def optimizer_stats_payload() -> Dict[str, Any]:
    init_db()
    with connect() as db:
        summary = db.execute(
            """
            SELECT COUNT(*) AS total_events,
                   SUM(CASE WHEN action_type != 'rollback' THEN 1 ELSE 0 END) AS autonomous_actions,
                   SUM(CASE WHEN action_type != 'rollback' AND dry_run = 1 THEN 1 ELSE 0 END) AS dry_runs,
                   SUM(CASE WHEN action_type != 'rollback' AND status = 'applied' THEN 1 ELSE 0 END) AS applied_actions,
                   SUM(CASE WHEN action_type = 'rollback' THEN 1 ELSE 0 END) AS rollbacks,
                   SUM(CASE WHEN action_type != 'rollback' THEN estimated_success_improvement ELSE 0 END) AS estimated_success_improvement,
                   AVG(CASE WHEN action_type != 'rollback' THEN confidence END) AS average_confidence
            FROM optimization_events
            """
        ).fetchone()
        action_rows = db.execute(
            """
            SELECT action_type, COUNT(*) AS count
            FROM optimization_events
            GROUP BY action_type
            ORDER BY count DESC, action_type ASC
            LIMIT 8
            """
        ).fetchall()
        history_rows = db.execute(
            """
            SELECT *
            FROM optimization_events
            ORDER BY created_at DESC
            LIMIT 8
            """
        ).fetchall()
    return {
        "total_events": int(summary["total_events"] or 0),
        "autonomous_actions": int(summary["autonomous_actions"] or 0),
        "dry_runs": int(summary["dry_runs"] or 0),
        "applied_actions": int(summary["applied_actions"] or 0),
        "rollbacks": int(summary["rollbacks"] or 0),
        "estimated_success_improvement": round(float(summary["estimated_success_improvement"] or 0.0), 2),
        "average_confidence": round(float(summary["average_confidence"] or 0.0), 2),
        "action_distribution": [row_to_dict(row) for row in action_rows],
        "history": [compact_optimization_event(optimization_event_to_dict(row)) for row in history_rows],
    }


def optimizer_dashboard_payload() -> Dict[str, Any]:
    return optimizer_stats_payload()


def rollback_optimizer_event(event_id: str, dry_run: bool = False) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        row = db.execute("SELECT * FROM optimization_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Optimization event not found.")
        original = optimization_event_to_dict(row)
        if original["action_type"] == "rollback":
            raise HTTPException(status_code=400, detail="Rollback events cannot be rolled back.")
        if not dry_run and original["status"] != "applied":
            raise HTTPException(status_code=400, detail="Only applied optimization events can be rolled back.")

        action = {
            "action_type": "rollback",
            "target": original["target"],
            "confidence": original["confidence"],
            "estimated_success_improvement": 0.0,
            "previous_state": original["new_state"],
            "new_state": original["previous_state"],
            "supporting_evidence": [
                f"Rollback requested for optimization event {event_id}.",
                f"Original action: {original['action_type']} on {original['target']}.",
            ],
            "reason": f"Rollback optimization event {event_id}.",
        }
        rollback_event = insert_optimization_event(
            db,
            recommendation=None,
            action=action,
            dry_run=dry_run,
            scope=original["scope"],
            user_id=original["user_id"],
            project_id=original["project_id"],
            rollback_event_id=event_id,
            metadata={"rolled_back_event": original},
        )
        if not dry_run:
            rolled_back_at = now_iso()
            db.execute(
                """
                UPDATE optimization_events
                SET status = 'rolled_back', rolled_back_at = ?
                WHERE id = ?
                """,
                (rolled_back_at, event_id),
            )
            original["status"] = "rolled_back"
            original["rolled_back_at"] = rolled_back_at
    return {
        "dry_run": dry_run,
        "rolled_back_event": compact_optimization_event(original),
        "rollback_event": compact_optimization_event(rollback_event),
    }


def build_markdown_report(run: Dict[str, Any], score: Dict[str, Any], workflows: List[Dict[str, Any]]) -> str:
    lines = [
        "# Software Reliability Benchmark Report",
        "",
        f"**Run ID:** `{run['run_id']}`",
        f"**Model:** `{run['model']}`",
        f"**Provider URL:** `{run['provider_url']}`",
        f"**Environment:** `{run['environment']}`",
        f"**Created at:** {run['created_at']}",
        "",
        "## Summary",
        "",
        f"- Reliability Score V2: {run['reliability_score_v2']:.2f}",
        f"- Reliability Band: {run['reliability_band_v2']}",
        f"- Total workflows: {run['total_workflows']}",
        f"- Successful workflows: {run['successful']}",
        f"- Failed workflows: {run['failed']}",
        f"- Success rate: {run['success_rate']:.2f}%",
        f"- Failure rate: {run['failure_rate']:.2f}%",
        f"- Average execution time: {run['average_execution_time']:.3f}s",
        f"- Average confidence: {run['average_confidence']:.3f}",
        "",
        "## Reliability Metrics",
        "",
        f"- Retry rate: {score['retry_rate']:.2f}%",
        f"- Recovery rate: {score['recovery_rate']:.2f}%",
        f"- Retry success rate: {score['retry_success_rate']:.2f}%",
        f"- Tool reliability: {score['tool_reliability']:.2f}%",
        f"- Timeout rate: {score['timeout_rate']:.2f}%",
        f"- Confidence accuracy: {score['confidence_accuracy']:.2f}%",
        f"- Simulation gap: {score['simulation_gap']:.2f} percentage points",
        f"- Workflow completion rate: {score['workflow_completion_rate']:.2f}%",
        "",
    ]
    if workflows:
        lines.extend(["## Workflow Results", ""])
        for workflow in workflows[:50]:
            lines.append(
                f"- `{workflow['workflow_id']}`: {workflow['status']}; "
                f"success={bool(workflow['successful'])}; "
                f"time={workflow['execution_time']:.3f}s; "
                f"confidence={workflow['confidence']:.3f}"
            )
    else:
        lines.extend(["## Workflow Results", "", "- No per-workflow rows were submitted for this run."])
    return "\n".join(lines) + "\n"


def fetch_run(run_id: str) -> Dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM benchmark_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Benchmark run not found.")
    return row_to_dict(row)


def fetch_score(run_id: str) -> Dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM reliability_scores WHERE run_id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Reliability score not found.")
    return row_to_dict(row)


def fetch_workflows(run_id: str) -> List[Dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM workflow_results WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def parse_json_object(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def dashboard_metadata(run_id: str) -> Dict[str, Any]:
    init_reliability_db()
    with reliability_connect() as db:
        row = db.execute(
            "SELECT metadata_json FROM benchmark_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    return parse_json_object(row["metadata_json"]) if row else {}


def dashboard_overview_payload() -> Dict[str, Any]:
    init_reliability_db()
    with reliability_connect() as db:
        run_count = db.execute("SELECT COUNT(*) AS count FROM benchmark_runs").fetchone()["count"]
        model_totals = db.execute(
            """
            SELECT
                COALESCE(SUM(total_workflows), 0) AS total_workflows,
                COALESCE(SUM(successful_workflows), 0) AS successful_workflows,
                COALESCE(SUM(failed_workflows), 0) AS failed_workflows,
                COALESCE(SUM(reliability_score_v2 * total_workflows), 0) AS weighted_score,
                COALESCE(AVG(average_execution_time_ms), 0) AS average_latency_ms,
                COALESCE(AVG(average_confidence), 0) AS average_confidence
            FROM model_results
            """
        ).fetchone()
        latest = db.execute(
            "SELECT generated_at FROM benchmark_runs ORDER BY generated_at DESC LIMIT 1"
        ).fetchone()

    total = int(model_totals["total_workflows"] or 0)
    successful = int(model_totals["successful_workflows"] or 0)
    failed = int(model_totals["failed_workflows"] or 0)
    score = float(model_totals["weighted_score"] or 0.0) / total if total else 0.0
    success_rate = successful / total * 100.0 if total else 0.0
    failure_rate = failed / total * 100.0 if total else 0.0
    return {
        "total_benchmark_runs": int(run_count or 0),
        "total_workflows": total,
        "successful_workflows": successful,
        "failed_workflows": failed,
        "success_rate": round(success_rate, 2),
        "failure_rate": round(failure_rate, 2),
        "reliability_score": round(score, 2),
        "average_latency_ms": round(float(model_totals["average_latency_ms"] or 0.0), 2),
        "average_confidence": round(float(model_totals["average_confidence"] or 0.0), 4),
        "last_updated": latest["generated_at"] if latest else None,
    }


def dashboard_model_leaderboard_payload() -> List[Dict[str, Any]]:
    init_reliability_db()
    with reliability_connect() as db:
        rows = db.execute(
            """
            SELECT model, reliability_score_v2, success_rate, failure_rate,
                   average_execution_time_ms, average_confidence, retries,
                   rollbacks, escalations, timeout_rate, tool_reliability,
                   total_workflows, created_at
            FROM model_results
            ORDER BY reliability_score_v2 DESC, success_rate DESC, average_execution_time_ms ASC
            """
        ).fetchall()
    return [
        {"rank": index + 1, **dict(row)}
        for index, row in enumerate(rows)
    ]


def dashboard_tool_reliability_payload() -> List[Dict[str, Any]]:
    init_reliability_db()
    with reliability_connect() as db:
        rows = db.execute(
            """
            SELECT tool_name, reliability_score, success_rate, failure_rate,
                   average_latency_ms, p95_latency_ms, timeout_rate, recovery_rate,
                   total_workflows, successful_workflows, failed_workflows, created_at
            FROM tool_results
            ORDER BY reliability_score DESC, success_rate DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def dashboard_workflow_analytics_payload() -> Dict[str, Any]:
    metadata = dashboard_metadata("phase6_workflow_reliability")
    overall = metadata.get("overall", {})
    stage_summary = overall.get("stage_summary", {})
    stages = list(stage_summary.values()) if isinstance(stage_summary, dict) else []
    return {
        "total_workflows": overall.get("total_workflows", 0),
        "successful_workflows": overall.get("successful_workflows", 0),
        "failed_workflows": overall.get("failed_workflows", 0),
        "success_rate": overall.get("success_rate", 0),
        "failure_rate": overall.get("failure_rate", 0),
        "stage_summary": stages,
        "highest_failure_stage": overall.get("highest_failure_stage"),
        "lowest_failure_stage": overall.get("lowest_failure_stage"),
        "confidence_drops": overall.get("confidence_drops", []),
    }


def dashboard_prediction_payload() -> Dict[str, Any]:
    metadata = dashboard_metadata("phase7_reliability_prediction")
    evaluation = metadata.get("evaluation", {})
    init_reliability_db()
    with reliability_connect() as db:
        row = db.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN actual_success = predicted_success THEN 1 ELSE 0 END) AS correct,
                SUM(CASE WHEN actual_success = 0 AND predicted_success = 0 THEN 1 ELSE 0 END) AS true_positive_failure,
                SUM(CASE WHEN actual_success = 1 AND predicted_success = 0 THEN 1 ELSE 0 END) AS false_positive_failure,
                SUM(CASE WHEN actual_success = 1 AND predicted_success = 1 THEN 1 ELSE 0 END) AS true_negative_success,
                SUM(CASE WHEN actual_success = 0 AND predicted_success = 1 THEN 1 ELSE 0 END) AS false_negative_failure
            FROM predictions
            """
        ).fetchone()
    total = int(row["total"] or 0)
    correct = int(row["correct"] or 0)
    return {
        "total": evaluation.get("total", total),
        "correct": evaluation.get("correct", correct),
        "accuracy": evaluation.get("accuracy", round(correct / total * 100.0, 2) if total else 0.0),
        "precision": evaluation.get("precision", 0),
        "recall": evaluation.get("recall", 0),
        "false_positives": evaluation.get("false_positive_failure", int(row["false_positive_failure"] or 0)),
        "false_negatives": evaluation.get("false_negative_failure", int(row["false_negative_failure"] or 0)),
        "true_positive_failure": evaluation.get("true_positive_failure", int(row["true_positive_failure"] or 0)),
        "true_negative_success": evaluation.get("true_negative_success", int(row["true_negative_success"] or 0)),
    }


def dashboard_guardrail_payload() -> Dict[str, Any]:
    metadata = dashboard_metadata("phase8_guardrail_effectiveness")
    summary = metadata.get("summary", {})
    stats = get_reliability_guardrail_stats()
    return {
        **stats,
        "baseline_success_rate": summary.get("baseline_success_rate", 0),
        "post_guardrail_success_rate": summary.get("post_guardrail_success_rate", 0),
        "baseline_failure_rate": summary.get("baseline_failure_rate", 0),
        "post_guardrail_failure_rate": summary.get("post_guardrail_failure_rate", 0),
        "recovery_latency_ms": summary.get("average_recovery_latency_ms", stats.get("average_latency_ms", 0)),
        "escalations": summary.get("escalations", 0),
    }


def dashboard_trends_payload() -> List[Dict[str, Any]]:
    init_reliability_db()
    with reliability_connect() as db:
        rows = db.execute(
            """
            SELECT created_at, model AS label, 'model' AS category,
                   reliability_score_v2 AS reliability_score, success_rate,
                   failure_rate, average_execution_time_ms AS latency_ms,
                   average_confidence
            FROM model_results
            ORDER BY created_at ASC, reliability_score_v2 DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def user_benchmark_overview(user_id: str) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        row = db.execute(
            """
            SELECT
                COUNT(*) AS total_benchmark_runs,
                COALESCE(SUM(total_workflows), 0) AS total_workflows,
                COALESCE(SUM(successful), 0) AS successful_workflows,
                COALESCE(SUM(failed), 0) AS failed_workflows,
                COALESCE(SUM(reliability_score_v2 * total_workflows), 0) AS weighted_score,
                MAX(created_at) AS last_updated
            FROM benchmark_runs
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    total = int(row["total_workflows"] or 0)
    successful = int(row["successful_workflows"] or 0)
    failed = int(row["failed_workflows"] or 0)
    return {
        "total_benchmark_runs": int(row["total_benchmark_runs"] or 0),
        "total_workflows": total,
        "successful_workflows": successful,
        "failed_workflows": failed,
        "success_rate": round(successful / total * 100.0, 2) if total else 0.0,
        "failure_rate": round(failed / total * 100.0, 2) if total else 0.0,
        "reliability_score": round(float(row["weighted_score"] or 0.0) / total, 2) if total else 0.0,
        "last_updated": row["last_updated"],
    }


def user_benchmark_trends(user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    init_db()
    with connect() as db:
        rows = db.execute(
            """
            SELECT created_at, model AS label, 'model' AS category,
                   reliability_score_v2 AS reliability_score, success_rate,
                   failure_rate, average_execution_time * 1000.0 AS latency_ms,
                   average_confidence
            FROM benchmark_runs
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def user_benchmark_leaderboard(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    init_db()
    with connect() as db:
        rows = db.execute(
            """
            SELECT model,
                   MAX(reliability_score_v2) AS reliability_score_v2,
                   MAX(success_rate) AS success_rate,
                   MIN(failure_rate) AS failure_rate,
                   AVG(average_execution_time * 1000.0) AS average_execution_time_ms,
                   AVG(average_confidence) AS average_confidence,
                   SUM(total_workflows) AS total_workflows,
                   MAX(created_at) AS created_at
            FROM benchmark_runs
            WHERE user_id = ?
            GROUP BY model
            ORDER BY reliability_score_v2 DESC, success_rate DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [
        {"rank": index, **row_to_dict(row)}
        for index, row in enumerate(rows, start=1)
    ]


def sdk_project_scope(project_ids: Optional[List[str]]) -> tuple[str, List[Any]]:
    if project_ids is None:
        return "", []
    if not project_ids:
        return "WHERE 1 = 0", []
    placeholders = ", ".join("?" for _ in project_ids)
    return f"WHERE project_id IN ({placeholders})", list(project_ids)


def dashboard_sdk_payload(project_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    init_db()
    where_sql, params = sdk_project_scope(project_ids)
    event_where_sql = ""
    event_params: List[Any] = []
    if project_ids is not None:
        if project_ids:
            placeholders = ", ".join("?" for _ in project_ids)
            event_where_sql = (
                "WHERE workflow_id IN (SELECT workflow_id FROM sdk_workflows "
                f"WHERE project_id IN ({placeholders}))"
            )
            event_params = list(project_ids)
        else:
            event_where_sql = "WHERE 1 = 0"
    with connect() as db:
        summary = db.execute(
            f"""
            SELECT
                COUNT(*) AS total_workflows,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_workflows,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_workflows,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_workflows,
                AVG(confidence) AS average_confidence,
                AVG(total_latency_ms) AS average_latency_ms
            FROM sdk_workflows
            {where_sql}
            """,
            params,
        ).fetchone()
        event_rows = db.execute(
            f"""
            SELECT event_type, COUNT(*) AS count
            FROM sdk_events
            {event_where_sql}
            GROUP BY event_type
            ORDER BY count DESC
            """,
            event_params,
        ).fetchall()
        recent_rows = db.execute(
            f"""
            SELECT workflow_id, user_id, project_id, api_key_id, project_name, workflow_name,
                   status, success, confidence,
                   total_latency_ms, predicted_failure_probability, guardrail_action,
                   started_at, completed_at
            FROM sdk_workflows
            {where_sql}
            ORDER BY started_at DESC
            LIMIT 10
            """,
            params,
        ).fetchall()
    total = int(summary["total_workflows"] or 0)
    successful = int(summary["successful_workflows"] or 0)
    failed = int(summary["failed_workflows"] or 0)
    return {
        "total_workflows": total,
        "completed_workflows": int(summary["completed_workflows"] or 0),
        "successful_workflows": successful,
        "failed_workflows": failed,
        "success_rate": round(successful / total * 100.0, 2) if total else 0.0,
        "failure_rate": round(failed / total * 100.0, 2) if total else 0.0,
        "average_confidence": round(float(summary["average_confidence"] or 0.0), 4),
        "average_latency_ms": round(float(summary["average_latency_ms"] or 0.0), 2),
        "event_distribution": [dict(row) for row in event_rows],
        "recent_workflows": [dict(row) for row in recent_rows],
    }


def failure_record_key(record: Dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("source") or ""),
        str(record.get("run_id") or ""),
        str(record.get("workflow_id") or ""),
    )


def collect_failure_records(limit: int = 500) -> tuple[List[Dict[str, Any]], int]:
    init_db()
    records: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    with connect() as db:
        stored_rows = db.execute(
            """
            SELECT source, run_id, workflow_id, workflow_name, failure_reason,
                   failure_category, execution_duration, retry_count, created_at, metadata_json
            FROM failure_records
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        for row in stored_rows:
            record = row_to_dict(row)
            record["metadata"] = parse_json_object(record.pop("metadata_json", "{}"))
            records[failure_record_key(record)] = record

        benchmark_rows = db.execute(
            """
            SELECT workflow_results.run_id,
                   workflow_results.workflow_id,
                   benchmark_runs.model AS workflow_name,
                   COALESCE(workflow_results.failure_reason, workflow_results.failed_agent, workflow_results.status, 'unknown') AS failure_reason,
                   workflow_results.execution_time AS execution_duration,
                   workflow_results.retry_count,
                   workflow_results.created_at
            FROM workflow_results
            JOIN benchmark_runs ON benchmark_runs.run_id = workflow_results.run_id
            WHERE workflow_results.successful = 0
            ORDER BY workflow_results.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        for row in benchmark_rows:
            record = {
                "source": "benchmark",
                "run_id": row["run_id"],
                "workflow_id": row["workflow_id"],
                "workflow_name": row["workflow_name"],
                "failure_reason": row["failure_reason"] or "unknown",
                "failure_category": normalize_failure_category(row["failure_reason"]),
                "execution_duration": round(float(row["execution_duration"] or 0.0), 4),
                "retry_count": int(row["retry_count"] or 0),
                "created_at": row["created_at"],
                "metadata": {"legacy_source": "workflow_results"},
            }
            records.setdefault(failure_record_key(record), record)

        sdk_rows = db.execute(
            """
            SELECT sdk_workflows.workflow_id,
                   sdk_workflows.workflow_name,
                   sdk_workflows.project_name,
                   sdk_workflows.total_latency_ms,
                   sdk_workflows.started_at,
                   sdk_workflows.completed_at,
                   (
                       SELECT COALESCE(error_type, error_message, name, event_type)
                       FROM sdk_events
                       WHERE sdk_events.workflow_id = sdk_workflows.workflow_id
                         AND (event_type = 'error' OR success = 0)
                       ORDER BY created_at DESC
                       LIMIT 1
                   ) AS failure_reason,
                   (
                       SELECT COUNT(*)
                       FROM sdk_events
                       WHERE sdk_events.workflow_id = sdk_workflows.workflow_id
                         AND (event_type = 'recovery' OR LOWER(COALESCE(name, '')) LIKE '%retry%')
                   ) AS retry_count
            FROM sdk_workflows
            WHERE success = 0 OR status = 'failed'
            ORDER BY COALESCE(completed_at, started_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        for row in sdk_rows:
            reason = row["failure_reason"] or "workflow_failed"
            record = {
                "source": "sdk",
                "run_id": None,
                "workflow_id": row["workflow_id"],
                "workflow_name": row["workflow_name"],
                "failure_reason": reason,
                "failure_category": normalize_failure_category(reason),
                "execution_duration": round(float(row["total_latency_ms"] or 0) / 1000.0, 4),
                "retry_count": int(row["retry_count"] or 0),
                "created_at": row["completed_at"] or row["started_at"],
                "metadata": {"project_name": row["project_name"], "legacy_source": "sdk_workflows"},
            }
            records.setdefault(failure_record_key(record), record)

        totals = db.execute(
            """
            SELECT
                (SELECT COALESCE(SUM(total_workflows), 0) FROM benchmark_runs) AS benchmark_total,
                (SELECT COUNT(*) FROM sdk_workflows) AS sdk_total
            """
        ).fetchone()

    failures = sorted(records.values(), key=lambda item: item.get("created_at") or "", reverse=True)
    for record in failures:
        record["timestamp"] = record["created_at"]
    total_workflows = int(totals["benchmark_total"] or 0) + int(totals["sdk_total"] or 0)
    return failures[:limit], total_workflows


def failure_recommendations(
    failures: List[Dict[str, Any]],
    top_causes: List[Dict[str, Any]],
    failure_rate: float,
    average_duration: float,
    average_retries: float,
) -> List[Dict[str, Any]]:
    if not failures:
        return [
            {
                "issue": "No failed workflows recorded yet.",
                "recommendation": "Run benchmark or SDK workflows to build a failure baseline.",
                "expected_improvement": 0.0,
            }
        ]

    recommendations: List[Dict[str, Any]] = []
    if top_causes:
        top = top_causes[0]
        recommendations.append(
            {
                "issue": f"{top['label']} caused {top['percentage']}% of failures.",
                "recommendation": "Prioritize this category first because it has the largest reliability impact.",
                "expected_improvement": round(min(35.0, top["percentage"] * 0.45), 2),
            }
        )

    timeout_pct = next((cause["percentage"] for cause in top_causes if "timeout" in cause["category"]), 0.0)
    tool_pct = next((cause["percentage"] for cause in top_causes if cause["category"] == "tool_failure"), 0.0)
    low_confidence_pct = next((cause["percentage"] for cause in top_causes if cause["category"] == "low_confidence"), 0.0)

    if average_retries < 1.0 and failure_rate > 5.0:
        recommendations.append(
            {
                "issue": "Failed workflows are not retrying often enough.",
                "recommendation": f"Retry policy could improve reliability by {round(min(18.0, failure_rate * 0.25), 2)}%.",
                "expected_improvement": round(min(18.0, failure_rate * 0.25), 2),
            }
        )
    if timeout_pct >= 15.0:
        recommendations.append(
            {
                "issue": f"Timeout failures represent {timeout_pct}% of recorded failures.",
                "recommendation": "Increase timeouts for slow stages and add fallback providers for long-running calls.",
                "expected_improvement": round(min(22.0, timeout_pct * 0.4), 2),
            }
        )
    if tool_pct >= 15.0:
        recommendations.append(
            {
                "issue": f"External tool failures represent {tool_pct}% of recorded failures.",
                "recommendation": "Add provider health checks, schema validation, and backup tool routing.",
                "expected_improvement": round(min(24.0, tool_pct * 0.42), 2),
            }
        )
    if low_confidence_pct >= 10.0:
        recommendations.append(
            {
                "issue": f"Low confidence caused {low_confidence_pct}% of failures.",
                "recommendation": "Use confidence gates earlier and reroute low-confidence tasks before final generation.",
                "expected_improvement": round(min(16.0, low_confidence_pct * 0.35), 2),
            }
        )
    if average_duration > 4.0:
        recommendations.append(
            {
                "issue": f"Failed workflows average {round(average_duration, 2)}s before stopping.",
                "recommendation": "Add earlier stage-level failure checks to reduce wasted execution time.",
                "expected_improvement": round(min(12.0, average_duration * 1.5), 2),
            }
        )
    return recommendations[:5]


def failure_analysis_payload(limit: int = 500) -> Dict[str, Any]:
    failures, total_workflows = collect_failure_records(limit)
    total_failures = len(failures)
    total_retries = sum(int(failure.get("retry_count") or 0) for failure in failures)
    total_duration = sum(float(failure.get("execution_duration") or 0.0) for failure in failures)
    average_duration = round(total_duration / total_failures, 3) if total_failures else 0.0
    average_retries = round(total_retries / total_failures, 3) if total_failures else 0.0
    failure_rate = round(total_failures / total_workflows * 100.0, 2) if total_workflows else 0.0

    category_counts = Counter(str(failure["failure_category"]) for failure in failures)
    top_causes = [
        {
            "category": category,
            "label": category.replace("_", " ").title(),
            "count": count,
            "percentage": round(count / total_failures * 100.0, 2) if total_failures else 0.0,
        }
        for category, count in category_counts.most_common()
    ]

    trend_counts = Counter(str(failure.get("created_at") or "")[:10] or "unknown" for failure in failures)
    failure_trends = [
        {"date": date, "failures": count}
        for date, count in sorted(trend_counts.items())
    ]

    workflow_groups: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"workflow_name": "", "failure_count": 0, "total_duration": 0.0, "total_retries": 0}
    )
    for failure in failures:
        workflow_name = failure.get("workflow_name") or failure.get("workflow_id") or "unknown"
        group = workflow_groups[str(workflow_name)]
        group["workflow_name"] = str(workflow_name)
        group["failure_count"] += 1
        group["total_duration"] += float(failure.get("execution_duration") or 0.0)
        group["total_retries"] += int(failure.get("retry_count") or 0)

    unstable_workflows = []
    for group in workflow_groups.values():
        count = int(group["failure_count"])
        avg_duration = group["total_duration"] / count if count else 0.0
        avg_retries = group["total_retries"] / count if count else 0.0
        unstable_workflows.append(
            {
                "workflow_name": group["workflow_name"],
                "failure_count": count,
                "average_duration": round(avg_duration, 3),
                "average_retries": round(avg_retries, 3),
                "impact": round(count * (1.0 + avg_retries * 0.25) * (1.0 + min(avg_duration, 10.0) / 10.0), 3),
            }
        )
    unstable_workflows.sort(key=lambda item: (item["impact"], item["failure_count"]), reverse=True)

    reliability_impact_score = round(
        min(100.0, failure_rate * 0.72 + min(average_duration * 4.0, 20.0) + min(average_retries * 6.0, 18.0)),
        2,
    )
    recommendations = failure_recommendations(
        failures,
        top_causes,
        failure_rate,
        average_duration,
        average_retries,
    )
    return {
        "summary": {
            "total_workflows": total_workflows,
            "failed_workflows": total_failures,
            "failure_rate": failure_rate,
            "average_execution_duration": average_duration,
            "average_retry_count": average_retries,
            "reliability_impact_score": reliability_impact_score,
        },
        "top_failure_causes": top_causes[:10],
        "failure_trends": failure_trends,
        "unstable_workflows": unstable_workflows[:10],
        "recommendations": recommendations,
        "failed_workflows": failures[:50],
    }


def dashboard_payload() -> Dict[str, Any]:
    return {
        "overview": dashboard_overview_payload(),
        "model_leaderboard": dashboard_model_leaderboard_payload(),
        "tool_reliability": dashboard_tool_reliability_payload(),
        "workflow_analytics": dashboard_workflow_analytics_payload(),
        "prediction_analytics": dashboard_prediction_payload(),
        "guardrail_analytics": dashboard_guardrail_payload(),
        "recovery_analytics": recovery_summary(),
        "copilot": copilot_dashboard_payload(),
        "optimizer": optimizer_dashboard_payload(),
        "meta_reliability": meta_reliability_dashboard_payload(),
        "redis": redis_health_check(),
        "team_workspaces": {
            "organizations": [],
            "members": [],
            "invitations": [],
            "organization_count": 0,
            "member_count": 0,
            "pending_invitation_count": 0,
        },
        "historical_trends": dashboard_trends_payload(),
        "sdk_workflows": dashboard_sdk_payload(),
    }


def user_project_ids(user_id: str) -> List[str]:
    init_db()
    with connect() as db:
        rows = db.execute(
            "SELECT id FROM projects WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,),
        ).fetchall()
    return [row["id"] for row in rows]


def user_dashboard_payload(user: Dict[str, Any]) -> Dict[str, Any]:
    project_ids = user_project_ids(user["id"])
    sdk = dashboard_sdk_payload(project_ids)
    benchmark = user_benchmark_overview(user["id"])
    benchmark_total = int(benchmark["total_workflows"])
    sdk_total = int(sdk["total_workflows"])
    combined_total = benchmark_total + sdk_total
    combined_successful = int(benchmark["successful_workflows"]) + int(sdk["successful_workflows"])
    combined_failed = int(benchmark["failed_workflows"]) + int(sdk["failed_workflows"])
    weighted_reliability = (
        float(benchmark["reliability_score"]) * benchmark_total
        + max(0.0, 100.0 - float(sdk["failure_rate"])) * sdk_total
    )
    with connect() as db:
        billing = billing_summary(db, user["id"])
        recovery = recovery_summary(project_ids)
    copilot = copilot_dashboard_payload(project_ids, user["id"])
    optimizer = optimizer_dashboard_payload()
    meta_reliability = meta_reliability_dashboard_payload()
    team_workspaces = team_workspaces_payload(user["id"])
    return {
        "user": user,
        "projects": project_ids,
        "billing": billing,
        "recovery_analytics": recovery,
        "copilot": copilot,
        "optimizer": optimizer,
        "meta_reliability": meta_reliability,
        "redis": redis_health_check(),
        "team_workspaces": team_workspaces,
        "sdk_workflows": sdk,
        "model_leaderboard": user_benchmark_leaderboard(user["id"]),
        "historical_trends": user_benchmark_trends(user["id"]),
        "overview": {
            "total_benchmark_runs": benchmark["total_benchmark_runs"],
            "total_workflows": combined_total,
            "successful_workflows": combined_successful,
            "failed_workflows": combined_failed,
            "success_rate": round(combined_successful / combined_total * 100.0, 2) if combined_total else 0.0,
            "failure_rate": round(combined_failed / combined_total * 100.0, 2) if combined_total else 0.0,
            "reliability_score": round(weighted_reliability / combined_total, 2) if combined_total else 0.0,
            "average_latency_ms": sdk["average_latency_ms"],
            "average_confidence": sdk["average_confidence"],
            "last_updated": benchmark["last_updated"],
        },
    }


def table_counts(db: sqlite3.Connection, tables: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for table in tables:
        counts[table] = int(db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
    return counts


def api_database_check() -> Dict[str, Any]:
    try:
        init_db()
        with connect() as db:
            db.execute("SELECT 1").fetchone()
            counts = table_counts(
                db,
                [
                    "users",
                    "organizations",
                    "organization_members",
                    "invitations",
                    "projects",
                    "api_keys",
                    "plans",
                    "subscriptions",
                    "usage_records",
                    "stripe_invoices",
                    "stripe_events",
                    "request_access_requests",
                    "analytics_events",
                    "recovery_events",
                    "recommendations",
                    "optimization_events",
                    "ai_decisions",
                    "decision_verifications",
                    "human_approvals",
                    "ai_execution_requests",
                    "ai_execution_audit_events",
                    "benchmark_runs",
                    "workflow_results",
                    "model_results",
                    "reliability_scores",
                    "sdk_workflows",
                    "sdk_events",
                ],
            )
        return {
            "ok": True,
            "path": str(DB_PATH),
            "tables": counts,
        }
    except Exception as error:
        return {
            "ok": False,
            "path": str(DB_PATH),
            "error": str(error),
        }


def reliability_database_check() -> Dict[str, Any]:
    try:
        init_reliability_db()
        with reliability_connect() as db:
            db.execute("SELECT 1").fetchone()
            counts = table_counts(
                db,
                [
                    "benchmark_runs",
                    "workflow_runs",
                    "model_results",
                    "tool_results",
                    "predictions",
                    "guardrail_events",
                ],
            )
        return {
            "ok": True,
            "tables": counts,
        }
    except Exception as error:
        return {
            "ok": False,
            "error": str(error),
        }


def dashboard_asset_check() -> Dict[str, Any]:
    assets = {
        "landing.html": BASE_DIR / "landing.html",
        "landing.css": BASE_DIR / "landing.css",
        "pricing.html": BASE_DIR / "pricing.html",
        "demo.html": BASE_DIR / "demo.html",
        "onboarding.html": BASE_DIR / "onboarding.html",
        "install.html": BASE_DIR / "install.html",
        "install_software_sdk.bat": BASE_DIR / "install_software_sdk.bat",
        "install_software_sdk.ps1": BASE_DIR / "install_software_sdk.ps1",
        "benchmark_runner.html": BASE_DIR / "benchmark_runner.html",
        "benchmark_runner.js": BASE_DIR / "benchmark_runner.js",
        "failure_analysis.html": BASE_DIR / "failure_analysis.html",
        "failure_analysis.js": BASE_DIR / "failure_analysis.js",
        "validation.js": BASE_DIR / "validation.js",
        "dashboard.html": BASE_DIR / "dashboard.html",
        "dashboard.css": BASE_DIR / "dashboard.css",
        "dashboard.js": BASE_DIR / "dashboard.js",
        "ui.css": BASE_DIR / "ui.css",
        "ui.js": BASE_DIR / "ui.js",
        "docs.css": BASE_DIR / "docs.css",
        "docs/index.html": BASE_DIR / "docs" / "index.html",
        "docs/quick-start.html": BASE_DIR / "docs" / "quick-start.html",
        "login.html": BASE_DIR / "login.html",
        "register.html": BASE_DIR / "register.html",
        "forgot_password.html": BASE_DIR / "forgot_password.html",
        "reset_password.html": BASE_DIR / "reset_password.html",
        "projects.html": BASE_DIR / "projects.html",
        "api_keys.html": BASE_DIR / "api_keys.html",
        "saas.css": BASE_DIR / "saas.css",
        "saas.js": BASE_DIR / "saas.js",
        "auth.js": BASE_DIR / "auth.js",
        "integrations/ui/apps.html": BASE_DIR / "integrations" / "ui" / "apps.html",
        "integrations/ui/apps.css": BASE_DIR / "integrations" / "ui" / "apps.css",
        "integrations/ui/apps.js": BASE_DIR / "integrations" / "ui" / "apps.js",
        "integrations/ui/integration_prompt.js": BASE_DIR / "integrations" / "ui" / "integration_prompt.js",
        "ai_execution/ui/confirmation.js": BASE_DIR / "ai_execution" / "ui" / "confirmation.js",
    }
    asset_status = {
        name: {
            "exists": path.exists(),
            "path": str(path),
        }
        for name, path in assets.items()
    }
    return {
        "ok": all(item["exists"] for item in asset_status.values()),
        "assets": asset_status,
    }


def run_startup_checks() -> Dict[str, Any]:
    global STARTUP_CHECKS
    checks = {
        "checked_at": now_iso(),
        "api_database": api_database_check(),
        "reliability_database": reliability_database_check(),
        "dashboard_assets": dashboard_asset_check(),
        "monitoring": sentry_health_check(),
        "composio": composio_health_check(),
        "redis": redis_health_check(),
    }
    checks["ok"] = all(
        check.get("ok") is True
        for key, check in checks.items()
        if isinstance(check, dict)
    )
    STARTUP_CHECKS = checks
    return checks


def service_uptime_seconds() -> float:
    return round((datetime.now(timezone.utc) - SERVICE_STARTED_AT).total_seconds(), 2)


def record_resumed_integration_action(
    user_id: str,
    resume: Dict[str, Any],
) -> None:
    workflow_id = resume.get("workflow_id")
    if not workflow_id:
        return
    result = resume.get("result") or {}
    with connect() as db:
        workflow = db.execute(
            """
            SELECT workflow_id, user_id
            FROM sdk_workflows
            WHERE workflow_id = ?
            """,
            (workflow_id,),
        ).fetchone()
        if not workflow or str(workflow["user_id"]) != str(user_id):
            return
        sdk_insert_event(
            db,
            workflow_id,
            "tool_call",
            stage_name="connected_app_resume",
            tool_name=resume.get("tool_slug"),
            name=resume.get("tool_slug"),
            success=bool(result.get("ok")),
            error_type=None if result.get("ok") else "connected_app_action_failure",
            error_message=result.get("error"),
            payload={
                "provider": "connected_apps",
                "resumed_after_connection": True,
                "agent_name": resume.get("agent_name"),
            },
        )


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    root_path=ROOT_PATH,
    docs_url=None if ENVIRONMENT == "production" else "/docs",
    redoc_url=None if ENVIRONMENT == "production" else "/redoc",
)

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

app.include_router(
    create_integrations_router(
        current_user=current_user,
        protected_page=protected_page,
        public_base_url=PUBLIC_BASE_URL,
        save_memory=qdrant_save_memory,
        record_resumed_action=record_resumed_integration_action,
    )
)

AI_EXECUTION_SERVICE = AIExecutionService(
    get_integrations=list_composio_integrations,
    get_tool_context=get_composio_tool_context,
    execute_tool=execute_composio_tool,
    search_memory=qdrant_search_memory,
    supabase_health=supabase_health_check,
    redis_health=redis_health_check,
    set_temporary_state=redis_set_execution_state,
    get_temporary_state=redis_get_execution_state,
    capture_error=capture_operational_error,
    redact=redact_text,
    scrub=scrub_sensitive_data,
)

app.include_router(
    create_ai_execution_router(
        service=AI_EXECUTION_SERVICE,
        current_user=current_user,
        distributed_lock=redis_distributed_lock,
    )
)


@app.middleware("http")
async def sentry_request_context(request: Request, call_next):
    request_id = (request.headers.get("x-request-id") or uuid.uuid4().hex)[:128]
    with sentry_sdk.isolation_scope() as scope:
        scope.set_tag("request_id", request_id)
        scope.set_tag("deployment_version", sentry_health_check()["deployment_version"])
        scope.set_context(
            "request_metadata",
            {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            },
        )
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


@app.middleware("http")
async def redis_api_rate_limit(request: Request, call_next):
    path = request.url.path
    protected_prefix = path.startswith("/api/") or path.startswith("/v1/") or path.startswith("/auth/")
    excluded = path in {
        "/api/integrations/redis/health",
        "/api/memory/health",
        "/api/supabase/health",
    }
    if not protected_prefix or excluded:
        return await call_next(request)

    authorization = request.headers.get("authorization")
    token = bearer_token(authorization) or request.cookies.get(SESSION_COOKIE_NAME)
    client_host = request.client.host if request.client else "unknown"
    identity = token or client_host
    rate = redis_check_rate_limit(
        identity,
        limit=API_RATE_LIMIT_REQUESTS,
        window_seconds=API_RATE_LIMIT_WINDOW_SECONDS,
        scope="http-api",
    )
    headers = {
        "X-RateLimit-Limit": str(rate["limit"]),
        "X-RateLimit-Remaining": str(rate["remaining"]),
        "X-RateLimit-Reset": str(rate["reset_seconds"]),
    }
    if not rate["allowed"]:
        return JSONResponse(
            status_code=429,
            content={
                "ok": False,
                "detail": "API rate limit exceeded. Retry after the reset window.",
                "retry_after_seconds": rate["reset_seconds"],
            },
            headers={**headers, "Retry-After": str(rate["reset_seconds"])},
        )
    response = await call_next(request)
    response.headers.update(headers)
    if rate.get("degraded"):
        response.headers["X-RateLimit-Status"] = "degraded"
    return response


@app.middleware("http")
async def production_domain_redirects(request: Request, call_next):
    target_url = domain_redirect_target(request)
    if target_url:
        return RedirectResponse(target_url, status_code=308)
    return await call_next(request)


@app.middleware("http")
async def inject_clarity_loader(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if (
        request.method == "HEAD"
        or not content_type.lower().startswith("text/html")
    ):
        return response

    chunks: List[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
    body = b"".join(chunks)
    scripts = [
        b'<script src="/integration_prompt.js"></script>',
        b'<script src="/ai_confirmation.js"></script>',
    ]
    if CLARITY_PROJECT_ID:
        scripts.append(b'<script src="/clarity.js"></script>')
    for marker in scripts:
        if marker not in body:
            body = body.replace(b"</head>", marker + b"</head>", 1)

    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "content-type"}
    }
    return Response(
        content=body,
        status_code=response.status_code,
        headers=headers,
        media_type="text/html",
    )


@app.on_event("startup")
def startup() -> None:
    monitoring = initialize_sentry()
    if monitoring["configured"] and not monitoring["initialized"]:
        LOGGER.error("Sentry is configured but failed to initialize: %s", monitoring["error"])
    initialize_redis()
    initialize_composio()
    run_startup_checks()


@app.get("/health")
def health_check(response: Response) -> Dict[str, Any]:
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "environment": ENVIRONMENT,
        "uptime_seconds": service_uptime_seconds(),
        "auth": {
            "provider": "clerk" if clerk_is_configured() else "local",
            "configured": clerk_is_configured(),
        },
        "checks": {
            "startup": STARTUP_CHECKS.get("ok") if STARTUP_CHECKS else None,
        },
    }


@app.get("/version")
def version() -> Dict[str, Any]:
    return {
        "service": APP_NAME,
        "version": APP_VERSION,
        "environment": ENVIRONMENT,
        "started_at": SERVICE_STARTED_AT.isoformat(),
    }


@app.get("/status")
def status(response: Response) -> Dict[str, Any]:
    checks = run_startup_checks()
    supabase = supabase_health_check()
    memory = memory_health_check()
    monitoring = sentry_health_check()
    composio_status = composio_health_check()
    redis_status = redis_health_check()
    if not checks["ok"]:
        response.status_code = 503
    return {
        "ok": checks["ok"],
        "service": APP_NAME,
        "version": APP_VERSION,
        "environment": ENVIRONMENT,
        "uptime_seconds": service_uptime_seconds(),
        "dashboard_url": "/dashboard",
        "api_docs_enabled": ENVIRONMENT != "production",
        "domain": domain_config_payload(),
        "supabase": supabase,
        "memory": memory,
        "monitoring": monitoring,
        "composio": composio_status,
        "redis": redis_status,
        "startup_checks": checks,
    }


@app.get("/metrics")
def metrics() -> Dict[str, Any]:
    overview = dashboard_overview_payload()
    guardrails = dashboard_guardrail_payload()
    recovery = recovery_summary()
    copilot = copilot_summary_payload()
    optimizer = optimizer_stats_payload()
    prediction = dashboard_prediction_payload()
    sdk = dashboard_sdk_payload()
    redis_status = redis_health_check()
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "uptime_seconds": service_uptime_seconds(),
        "metrics": {
            "total_benchmark_runs": overview["total_benchmark_runs"],
            "total_workflows": overview["total_workflows"],
            "successful_workflows": overview["successful_workflows"],
            "failed_workflows": overview["failed_workflows"],
            "success_rate": overview["success_rate"],
            "failure_rate": overview["failure_rate"],
            "reliability_score": overview["reliability_score"],
            "average_latency_ms": overview["average_latency_ms"],
            "average_confidence": overview["average_confidence"],
            "prediction_accuracy": prediction["accuracy"],
            "prediction_precision": prediction["precision"],
            "prediction_recall": prediction["recall"],
            "guardrail_interventions": guardrails["interventions"],
            "prevented_failures": guardrails["prevented_failures"],
            "guardrail_recovery_success_rate": guardrails["recovery_success_rate"],
            "auto_recovery_attempts": recovery["recovery_attempts"],
            "auto_recovery_success_rate": recovery["recovery_success_rate"],
            "auto_recoveries_today": recovery["recoveries_today"],
            "copilot_recommendations": copilot["recommendation_count"],
            "copilot_average_confidence": copilot["average_confidence"],
            "copilot_estimated_success_improvement": copilot["total_estimated_success_improvement"],
            "optimizer_autonomous_actions": optimizer["autonomous_actions"],
            "optimizer_estimated_success_improvement": optimizer["estimated_success_improvement"],
            "optimizer_rollbacks": optimizer["rollbacks"],
            "sdk_workflows": sdk["total_workflows"],
            "sdk_success_rate": sdk["success_rate"],
            "sdk_failure_rate": sdk["failure_rate"],
            "redis_connected": redis_status["connected"],
            "redis_latency_ms": redis_status["latency_ms"],
            "redis_cache_hits": redis_status["cache_hits"],
            "redis_cache_misses": redis_status["cache_misses"],
            "redis_cache_hit_rate": redis_status["cache_hit_rate"],
            "redis_memory_usage_bytes": redis_status["memory_usage_bytes"],
            "redis_queue_depth": redis_status["queue_depth"],
        },
    }


@app.get("/", include_in_schema=False)
def landing_page() -> FileResponse:
    return FileResponse(BASE_DIR / "landing.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/clarity.js", include_in_schema=False)
def clarity_script() -> Response:
    project_id = json.dumps(CLARITY_PROJECT_ID)
    script = f"""
(function () {{
  var projectId = {project_id};
  if (!projectId) {{
    window.softwareTrack = function () {{}};
    return;
  }}

  (function(c,l,a,r,i,t,y){{
    c[a]=c[a]||function(){{(c[a].q=c[a].q||[]).push(arguments)}};
    t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;
    y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);
  }})(window, document, "clarity", "script", projectId);

  window.softwareTrack = function (eventName) {{
    if (eventName && window.clarity) {{
      window.clarity("event", eventName);
    }}
  }};

  var visitEvents = {{
    "/dashboard": "dashboard_visit",
    "/benchmarks": "benchmark_runner_visit",
    "/benchmark-runner": "benchmark_runner_visit"
  }};
  if (visitEvents[window.location.pathname]) {{
    window.softwareTrack(visitEvents[window.location.pathname]);
  }}

  document.addEventListener("click", function (event) {{
    var target = event.target.closest("a, button");
    if (!target) return;
    var explicitEvent = target.getAttribute("data-clarity-event");
    if (explicitEvent) {{
      window.softwareTrack(explicitEvent);
      return;
    }}
    if (target.tagName === "A" && target.href) {{
      try {{
        if (new URL(target.href, window.location.href).pathname === "/install") {{
          window.softwareTrack("install_click");
        }}
      }} catch (_) {{}}
    }}
  }}, true);
}})();
""".strip()
    return Response(content=script, media_type="application/javascript")


@app.get("/landing.css", include_in_schema=False)
def landing_styles() -> FileResponse:
    return FileResponse(BASE_DIR / "landing.css")


@app.get("/validation.js", include_in_schema=False)
def validation_script() -> FileResponse:
    return FileResponse(BASE_DIR / "validation.js")


@app.get("/pricing", include_in_schema=False)
def pricing_page() -> FileResponse:
    return FileResponse(BASE_DIR / "pricing.html")


@app.get("/demo", include_in_schema=False)
def demo_page() -> FileResponse:
    return FileResponse(BASE_DIR / "demo.html")


@app.get("/onboarding", include_in_schema=False)
def onboarding_page() -> FileResponse:
    return FileResponse(BASE_DIR / "onboarding.html")


@app.get("/install", include_in_schema=False)
def install_page() -> FileResponse:
    return FileResponse(BASE_DIR / "install.html")


@app.get("/sdk", include_in_schema=False)
def sdk_page() -> FileResponse:
    return FileResponse(BASE_DIR / "install.html")


@app.get("/benchmarks", include_in_schema=False)
def benchmark_runner_page(request: Request) -> Response:
    return protected_page(request, "benchmark_runner.html")


@app.get("/benchmark-runner", include_in_schema=False)
def benchmark_runner_alias() -> RedirectResponse:
    return RedirectResponse("/benchmarks", status_code=307)


@app.get("/benchmark_runner.js", include_in_schema=False)
def benchmark_runner_script() -> FileResponse:
    return FileResponse(BASE_DIR / "benchmark_runner.js")


@app.get("/failures", include_in_schema=False)
def failure_analysis_page(request: Request) -> Response:
    return protected_page(request, "failure_analysis.html")


@app.get("/failure-analysis", include_in_schema=False)
def failure_analysis_alias() -> RedirectResponse:
    return RedirectResponse("/failures", status_code=307)


@app.get("/failure_analysis.js", include_in_schema=False)
def failure_analysis_script() -> FileResponse:
    return FileResponse(BASE_DIR / "failure_analysis.js")


@app.get("/install_software_sdk.bat", include_in_schema=False)
def download_windows_batch_installer() -> FileResponse:
    return FileResponse(
        BASE_DIR / "install_software_sdk.bat",
        media_type="application/octet-stream",
        filename="install_software_sdk.bat",
    )


@app.get("/install_software_sdk.ps1", include_in_schema=False)
def download_windows_powershell_installer() -> FileResponse:
    return FileResponse(
        BASE_DIR / "install_software_sdk.ps1",
        media_type="application/octet-stream",
        filename="install_software_sdk.ps1",
    )


@app.get("/dashboard", include_in_schema=False)
def dashboard_page(request: Request) -> Response:
    return protected_page(request, "dashboard.html")


@app.get("/dashboard.css", include_in_schema=False)
def dashboard_styles() -> FileResponse:
    return FileResponse(BASE_DIR / "dashboard.css")


@app.get("/dashboard.js", include_in_schema=False)
def dashboard_script() -> FileResponse:
    return FileResponse(BASE_DIR / "dashboard.js")


@app.get("/ui.css", include_in_schema=False)
def shared_ui_styles() -> FileResponse:
    return FileResponse(BASE_DIR / "ui.css", media_type="text/css")


@app.get("/ui.js", include_in_schema=False)
def shared_ui_script() -> FileResponse:
    return FileResponse(BASE_DIR / "ui.js", media_type="application/javascript")


@app.get("/auth.js", include_in_schema=False)
def auth_script() -> FileResponse:
    return FileResponse(BASE_DIR / "auth.js")


@app.get("/docs.css", include_in_schema=False)
def docs_styles() -> FileResponse:
    return FileResponse(BASE_DIR / "docs.css")


def _matrixs_docs_response(path: Path) -> HTMLResponse:
    html = path.read_text(encoding="utf-8")
    html = html.replace(
        '<link rel="stylesheet" href="/docs.css">',
        '<link rel="stylesheet" href="/docs.css?v=20260808c">'
        '<link rel="stylesheet" href="/ui.css?v=20260808c">'
        '<script src="/ui.js?v=20260808c" defer></script>',
    )
    html = html.replace("<body>", '<body data-matrixs-page="reliability" class="docs-page">', 1)
    html = html.replace("Software Docs", "Matrixs Docs")
    html = html.replace("Software Documentation", "Matrixs Documentation")
    return HTMLResponse(html)


@app.get("/developer-docs", include_in_schema=False)
def developer_docs_page() -> HTMLResponse:
    return _matrixs_docs_response(BASE_DIR / "docs" / "index.html")


@app.get("/docs/{page_slug}", include_in_schema=False)
def developer_docs_detail(page_slug: str) -> HTMLResponse:
    allowed_pages = {
        "quick-start",
        "getting-started",
        "installation",
        "authentication",
        "projects",
        "api-keys",
        "sdk-usage",
        "api-reference",
        "dashboard-guide",
        "guardrails-guide",
        "troubleshooting",
    }
    if page_slug not in allowed_pages:
        raise HTTPException(status_code=404, detail="Documentation page not found.")
    return _matrixs_docs_response(BASE_DIR / "docs" / f"{page_slug}.html")


@app.get("/saas.css", include_in_schema=False)
def saas_styles() -> FileResponse:
    return FileResponse(BASE_DIR / "saas.css")


@app.get("/saas.js", include_in_schema=False)
def saas_script() -> FileResponse:
    return FileResponse(BASE_DIR / "saas.js")


@app.get("/login", include_in_schema=False)
def login_page() -> FileResponse:
    return FileResponse(BASE_DIR / "login.html")


@app.get("/register", include_in_schema=False)
def register_page() -> FileResponse:
    return FileResponse(BASE_DIR / "register.html")


@app.get("/forgot-password", include_in_schema=False)
def forgot_password_page() -> FileResponse:
    return FileResponse(BASE_DIR / "forgot_password.html")


@app.get("/reset-password", include_in_schema=False)
def reset_password_page() -> FileResponse:
    return FileResponse(BASE_DIR / "reset_password.html")


@app.get("/projects", include_in_schema=False)
def projects_page(request: Request) -> Response:
    return protected_page(request, "projects.html")


@app.get("/api-keys", include_in_schema=False)
def api_keys_page(request: Request) -> Response:
    return protected_page(request, "api_keys.html")


@app.get("/auth/config")
def auth_config(request: Request) -> Dict[str, Any]:
    base_url = public_base_url(request)
    return {
        "ok": True,
        **clerk_public_config(),
        "sign_in_url": f"{base_url}/login",
        "sign_up_url": f"{base_url}/register",
        "reset_redirect_url": f"{base_url}/reset-password",
        "email_redirect_url": f"{base_url}/dashboard",
        "sdk_install_public": True,
    }


def local_auth_register(payload: AuthRegister) -> Dict[str, Any]:
    init_db()
    email = normalize_email(payload.email)
    user_id = f"usr_{uuid.uuid4().hex}"
    created_at = now_iso()
    with connect() as db:
        existing = db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="A user with this email already exists.")
        db.execute(
            """
            INSERT INTO users (id, email, password_hash, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, email, hash_password(payload.password), created_at),
        )
        period_start, period_end = month_period()
        db.execute(
            """
            INSERT INTO subscriptions (
                id, user_id, plan_id, status, current_period_start,
                current_period_end, created_at, updated_at, metadata_json
            )
            VALUES (?, ?, 'free', 'active', ?, ?, ?, ?, '{}')
            """,
            (f"sub_{uuid.uuid4().hex}", user_id, period_start, period_end, created_at, created_at),
        )
        record_analytics_event(
            db,
            "signup",
            user_id=user_id,
            email=email,
            metadata={"source": "auth_register"},
        )
    token = create_access_token(user_id)
    return {
        "ok": True,
        "user": {"id": user_id, "email": email, "created_at": created_at},
        "provider": "local",
        **token,
    }


def local_auth_login(payload: AuthLogin) -> Dict[str, Any]:
    init_db()
    email = normalize_email(payload.email)
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = create_access_token(row["id"])
    return {
        "ok": True,
        "user": {"id": row["id"], "email": row["email"], "created_at": row["created_at"]},
        "provider": "local",
        **token,
    }


@app.post("/auth/register")
def auth_register(payload: AuthRegister, response: Response, request: Request) -> Dict[str, Any]:
    if clerk_is_configured():
        return {
            "ok": True,
            "provider": "clerk",
            "message": "Account creation is handled by Clerk. Use the Software sign-up page.",
            "confirmation_required": True,
        }
    result = local_auth_register(payload)
    set_session_cookie(response, result["access_token"])
    return result


@app.post("/auth/login")
def auth_login(payload: AuthLogin, response: Response) -> Dict[str, Any]:
    if clerk_is_configured():
        return {
            "ok": True,
            "provider": "clerk",
            "message": "Login is handled by Clerk. Use the Software sign-in page and send the Clerk session token as a bearer token.",
        }
    result = local_auth_login(payload)
    set_session_cookie(response, result["access_token"])
    return result


@app.post("/auth/logout")
def auth_logout(
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(None),
    _: Optional[Dict[str, Any]] = Depends(optional_current_user),
) -> Dict[str, Any]:
    token = bearer_token(authorization) or request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        redis_delete_session_cache(session_cache_id(token))
    clear_session_cookie(response)
    return {"ok": True, "message": "Logged out. Clerk sessions are signed out in the browser."}


@app.get("/auth/me")
def auth_me(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    return {"ok": True, "user": user}


@app.post("/auth/password-reset")
def auth_password_reset(payload: PasswordResetRequest, request: Request) -> Dict[str, Any]:
    if clerk_is_configured():
        return {
            "ok": True,
            "provider": "clerk",
            "message": "Password reset is handled by Clerk. Open the Software reset page and choose forgot password.",
        }
    raise HTTPException(status_code=503, detail="Password reset requires Clerk Authentication.")


@app.post("/auth/password-update")
def auth_password_update(payload: PasswordUpdateRequest) -> Dict[str, Any]:
    if clerk_is_configured():
        return {
            "ok": True,
            "provider": "clerk",
            "message": "Password update is handled by Clerk after the reset email flow.",
        }
    raise HTTPException(status_code=503, detail="Password update requires Clerk Authentication.")


def require_supabase_operation(result: Dict[str, Any]) -> Any:
    if result.get("ok"):
        return result.get("data")
    status_code = 503 if not result.get("available") else 502
    raise HTTPException(
        status_code=status_code,
        detail=result.get("error") or "Supabase operation failed.",
    )


@app.get("/api/supabase/health")
def api_supabase_health() -> Dict[str, Any]:
    health = supabase_health_check()
    return {"ok": health["ok"], "supabase": health}


@app.get("/api/memory/health")
def api_memory_health() -> Dict[str, Any]:
    health = memory_health_check()
    return {"ok": health["ok"], "memory": health}


@app.get("/api/integrations/redis/health")
def api_redis_health(response: Response) -> Dict[str, Any]:
    health = redis_health_check()
    if health["configured"] and not health["connected"]:
        response.status_code = 503
    return {"ok": health["ok"], "redis": health}


@app.get("/api/composio/health")
def api_composio_health() -> Dict[str, Any]:
    health = composio_health_check()
    return {"ok": health["ok"], "composio": health}


@app.get("/api/composio/tools")
def api_composio_tools(
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    return {
        "ok": True,
        "composio": get_composio_tool_context(user["id"]),
    }


@app.post("/api/composio/tools/refresh")
def api_refresh_composio_tools(
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    tools = refresh_composio_tools(user["id"])
    return {
        "ok": True,
        "tools": composio_tool_descriptors(tools),
        "composio": get_composio_tool_context(user["id"]),
    }


@app.get("/api/memory/recent")
def api_recent_memories(
    limit: int = Query(20, ge=1, le=100),
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    memories = qdrant_get_recent_memories(user["id"], limit=limit)
    return {
        "ok": True,
        "memories": memories,
        "memory_available": memory_health_check()["available"],
    }


@app.get("/api/memory/search")
def api_search_memories(
    query: str = Query(..., min_length=1, max_length=2000),
    limit: int = Query(5, ge=1, le=50),
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    memories = qdrant_search_memory(user["id"], query, limit=limit)
    return {
        "ok": True,
        "query": query,
        "memories": memories,
        "memory_available": memory_health_check()["available"],
    }


@app.post("/api/chats")
def create_chat(
    payload: ChatCreate,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    if payload.project_id:
        init_db()
        with connect() as db:
            user_project_or_404(db, user["id"], payload.project_id)
    result = supabase_create_chat(
        user_id=user["id"],
        project_id=payload.project_id,
        title=payload.title,
        metadata=payload.metadata,
    )
    chat = require_supabase_operation(result)
    if chat and chat.get("id"):
        redis_set_conversation_state(
            user["id"],
            chat["id"],
            {"chat": chat, "messages": []},
        )
    return {
        "ok": True,
        "chat": chat,
        "storage": "supabase",
    }


@app.post("/api/chats/{chat_id}/messages")
def save_chat_message(
    chat_id: str,
    payload: ChatMessageCreate,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    history = redis_get_conversation_state(user["id"], chat_id)
    if history is None:
        history_result = supabase_get_chat_history(chat_id=chat_id, user_id=user["id"])
        history = require_supabase_operation(history_result)
    if history["chat"] is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    relevant_memories: List[Dict[str, Any]] = []
    cached_ai_response: Optional[Dict[str, Any]] = None
    model = str(payload.metadata.get("model") or "") or None
    if payload.role == "user":
        relevant_memories = qdrant_search_memory(
            user["id"],
            payload.content,
        )
        cached_ai_response = redis_get_cached_ai_response(
            user["id"],
            payload.content,
            model=model,
        )
    result = supabase_save_message(
        chat_id=chat_id,
        user_id=user["id"],
        role=payload.role,
        content=payload.content,
        metadata=payload.metadata,
    )
    message = require_supabase_operation(result)
    memory_save = (
        qdrant_save_memory(user["id"], payload.content)
        if payload.role == "user"
        else {"ok": True, "stored": False, "reason": "Only user messages are stored."}
    )
    response_cache = {"ok": True, "cached": False}
    if payload.role == "assistant":
        source_prompt = str(
            payload.metadata.get("prompt")
            or payload.metadata.get("request")
            or ""
        ).strip()
        if source_prompt:
            response_cache = redis_cache_ai_response(
                user["id"],
                source_prompt,
                payload.content,
                model=model,
                metadata={"chat_id": chat_id},
            )
    messages = list(history.get("messages") or [])
    messages.append(message)
    redis_set_conversation_state(
        user["id"],
        chat_id,
        {"chat": history["chat"], "messages": messages},
    )
    return {
        "ok": True,
        "message": message,
        "storage": "supabase",
        "memory_context": relevant_memories,
        "memory_save": memory_save,
        "cached_ai_response": cached_ai_response,
        "response_cache": response_cache,
    }


@app.get("/api/chats/{chat_id}")
def open_chat(
    chat_id: str,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    history = redis_get_conversation_state(user["id"], chat_id)
    storage = "redis_cache"
    if history is None:
        history = require_supabase_operation(
            supabase_get_chat_history(chat_id=chat_id, user_id=user["id"])
        )
        storage = "supabase"
    if history["chat"] is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    redis_set_conversation_state(
        user["id"],
        chat_id,
        {"chat": history["chat"], "messages": history.get("messages") or []},
    )
    return {
        "ok": True,
        **history,
        "storage": storage,
        "recent_memories": qdrant_get_recent_memories(user["id"]),
    }


@app.get("/api/chats/{chat_id}/messages")
def get_chat_messages(
    chat_id: str,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    history = redis_get_conversation_state(user["id"], chat_id)
    storage = "redis_cache"
    if history is None:
        history = require_supabase_operation(
            supabase_get_chat_history(chat_id=chat_id, user_id=user["id"])
        )
        storage = "supabase"
    if history["chat"] is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    redis_set_conversation_state(
        user["id"],
        chat_id,
        {"chat": history["chat"], "messages": history.get("messages") or []},
    )
    return {
        "ok": True,
        "chat_id": chat_id,
        "messages": history["messages"],
        "storage": storage,
    }


@app.post("/api/orgs")
def create_organization(
    payload: OrganizationCreate,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    organization_id = f"org_{uuid.uuid4().hex}"
    member_id = f"mem_{uuid.uuid4().hex}"
    created_at = now_iso()
    name = payload.name.strip()
    with connect() as db:
        db.execute(
            """
            INSERT INTO organizations (id, name, owner_user_id, created_at, metadata_json)
            VALUES (?, ?, ?, ?, '{}')
            """,
            (organization_id, name, user["id"], created_at),
        )
        db.execute(
            """
            INSERT INTO organization_members (
                id, organization_id, user_id, role, created_at, updated_at
            )
            VALUES (?, ?, ?, 'owner', ?, ?)
            """,
            (member_id, organization_id, user["id"], created_at, created_at),
        )
        record_analytics_event(
            db,
            "organization_created",
            user_id=user["id"],
            email=user["email"],
            metadata={"organization_id": organization_id, "organization_name": name},
        )
    return {
        "ok": True,
        "organization": {
            "id": organization_id,
            "name": name,
            "owner_user_id": user["id"],
            "created_at": created_at,
            "role": "owner",
        },
    }


@app.get("/api/orgs")
def list_organizations(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    return {"ok": True, "team_workspaces": team_workspaces_payload(user["id"])}


@app.post("/api/orgs/invite")
def invite_organization_member(
    payload: OrganizationInvite,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    role = normalize_org_role(payload.role)
    email = normalize_email(payload.email)
    invitation_id = f"inv_{uuid.uuid4().hex}"
    token = secrets.token_urlsafe(24)
    created_at = now_iso()
    with connect() as db:
        require_org_role(db, payload.organization_id, user["id"], "admin")
        invited_user = db.execute("SELECT id, email FROM users WHERE email = ?", (email,)).fetchone()
        if invited_user:
            existing_member = organization_membership(db, payload.organization_id, invited_user["id"])
            if existing_member:
                raise HTTPException(status_code=409, detail="User is already an organization member.")
        status = "accepted" if invited_user else "pending"
        accepted_at = created_at if invited_user else None
        db.execute(
            """
            INSERT INTO invitations (
                id, organization_id, email, role, invited_by_user_id, status,
                token, created_at, accepted_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')
            """,
            (
                invitation_id,
                payload.organization_id,
                email,
                role,
                user["id"],
                status,
                token,
                created_at,
                accepted_at,
            ),
        )
        member = None
        if invited_user:
            member_id = f"mem_{uuid.uuid4().hex}"
            db.execute(
                """
                INSERT INTO organization_members (
                    id, organization_id, user_id, role, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (member_id, payload.organization_id, invited_user["id"], role, created_at, created_at),
            )
            member = {
                "id": member_id,
                "organization_id": payload.organization_id,
                "user_id": invited_user["id"],
                "email": invited_user["email"],
                "role": role,
                "created_at": created_at,
            }
        record_analytics_event(
            db,
            "organization_invitation_created",
            user_id=user["id"],
            email=user["email"],
            metadata={
                "organization_id": payload.organization_id,
                "invited_email": email,
                "role": role,
                "status": status,
            },
        )
    return {
        "ok": True,
        "invitation": {
            "id": invitation_id,
            "organization_id": payload.organization_id,
            "email": email,
            "role": role,
            "status": status,
            "created_at": created_at,
            "accepted_at": accepted_at,
        },
        "member_added": bool(member),
        "member": member,
    }


@app.post("/api/orgs/remove")
def remove_organization_member(
    payload: OrganizationRemoveMember,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        actor = require_org_role(db, payload.organization_id, user["id"], "admin")
        target = organization_membership(db, payload.organization_id, payload.user_id)
        if not target:
            raise HTTPException(status_code=404, detail="Organization member not found.")
        if target["role"] == "owner" and owner_count(db, payload.organization_id) <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last organization owner.")
        if actor["role"] == "admin" and role_at_least(target["role"], "admin"):
            raise HTTPException(status_code=403, detail="Admins cannot remove owners or other admins.")
        db.execute(
            """
            DELETE FROM organization_members
            WHERE organization_id = ? AND user_id = ?
            """,
            (payload.organization_id, payload.user_id),
        )
        record_analytics_event(
            db,
            "organization_member_removed",
            user_id=user["id"],
            email=user["email"],
            metadata={"organization_id": payload.organization_id, "removed_user_id": payload.user_id},
        )
    return {"ok": True, "removed": True, "organization_id": payload.organization_id, "user_id": payload.user_id}


@app.post("/api/orgs/transfer-ownership")
def transfer_organization_ownership(
    payload: OrganizationTransferOwnership,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    now = now_iso()
    with connect() as db:
        require_org_role(db, payload.organization_id, user["id"], "owner")
        new_owner = organization_membership(db, payload.organization_id, payload.new_owner_user_id)
        if not new_owner:
            raise HTTPException(status_code=404, detail="New owner must already be an organization member.")
        db.execute(
            """
            UPDATE organization_members
            SET role = CASE WHEN user_id = ? THEN 'owner' ELSE 'admin' END,
                updated_at = ?
            WHERE organization_id = ?
              AND role = 'owner'
            """,
            (payload.new_owner_user_id, now, payload.organization_id),
        )
        db.execute(
            """
            UPDATE organization_members
            SET role = 'owner', updated_at = ?
            WHERE organization_id = ? AND user_id = ?
            """,
            (now, payload.organization_id, payload.new_owner_user_id),
        )
        db.execute(
            "UPDATE organizations SET owner_user_id = ? WHERE id = ?",
            (payload.new_owner_user_id, payload.organization_id),
        )
        record_analytics_event(
            db,
            "organization_ownership_transferred",
            user_id=user["id"],
            email=user["email"],
            metadata={"organization_id": payload.organization_id, "new_owner_user_id": payload.new_owner_user_id},
        )
    return {
        "ok": True,
        "organization_id": payload.organization_id,
        "new_owner_user_id": payload.new_owner_user_id,
        "transferred": True,
    }


@app.get("/api/orgs/members")
def get_organization_members(
    organization_id: str = Query(..., min_length=1, max_length=180),
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        organization = organization_or_404(db, organization_id)
        membership = require_org_role(db, organization_id, user["id"], "viewer")
        member_rows = db.execute(
            """
            SELECT organization_members.id, organization_members.organization_id,
                   organization_members.user_id, users.email,
                   organization_members.role, organization_members.created_at,
                   organization_members.updated_at
            FROM organization_members
            JOIN users ON users.id = organization_members.user_id
            WHERE organization_members.organization_id = ?
            ORDER BY CASE organization_members.role
                       WHEN 'owner' THEN 1
                       WHEN 'admin' THEN 2
                       WHEN 'developer' THEN 3
                       ELSE 4
                     END,
                     users.email ASC
            """,
            (organization_id,),
        ).fetchall()
        invitation_rows = db.execute(
            """
            SELECT invitations.id, invitations.organization_id, invitations.email,
                   invitations.role, invitations.status, invitations.invited_by_user_id,
                   users.email AS invited_by_email, invitations.created_at,
                   invitations.accepted_at
            FROM invitations
            JOIN users ON users.id = invitations.invited_by_user_id
            WHERE invitations.organization_id = ?
            ORDER BY invitations.created_at DESC
            """,
            (organization_id,),
        ).fetchall()
    return {
        "ok": True,
        "organization": row_to_dict(organization),
        "current_user_role": membership["role"],
        "members": [row_to_dict(row) for row in member_rows],
        "invitations": [row_to_dict(row) for row in invitation_rows],
    }


@app.post("/api/request-access")
def request_access(payload: RequestAccessCreate) -> Dict[str, Any]:
    init_db()
    email = normalize_email(payload.email)
    request_id = f"req_{uuid.uuid4().hex}"
    created_at = now_iso()
    metadata = {
        "source": "demo_page",
        "expected_workflows_per_month": payload.expected_workflows_per_month,
    }
    with connect() as db:
        db.execute(
            """
            INSERT INTO request_access_requests (
                id, name, email, company, role, use_case,
                expected_workflows_per_month, timeline, status, created_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
            """,
            (
                request_id,
                payload.name.strip(),
                email,
                payload.company.strip() if payload.company else None,
                payload.role.strip() if payload.role else None,
                payload.use_case.strip(),
                payload.expected_workflows_per_month,
                payload.timeline.strip() if payload.timeline else None,
                created_at,
                json.dumps(metadata, sort_keys=True),
            ),
        )
        record_analytics_event(
            db,
            "request_access",
            email=email,
            metadata={
                "request_id": request_id,
                "company": payload.company,
                "role": payload.role,
                "timeline": payload.timeline,
            },
        )
    return {
        "ok": True,
        "request_id": request_id,
        "message": "Request received. We will follow up with early access details.",
    }


@app.post("/api/analytics/sdk-installation")
def analytics_sdk_installation(payload: SDKInstallationCreate) -> Dict[str, Any]:
    init_db()
    event_id = f"evt_analytics_{uuid.uuid4().hex}"
    created_at = now_iso()
    metadata = {
        "source": payload.source,
        "sdk_version": payload.sdk_version,
        "python_version": payload.python_version,
        "platform": payload.platform,
        "project_name": payload.project_name,
        **payload.metadata,
    }
    with connect() as db:
        db.execute(
            """
            INSERT INTO analytics_events (
                id, event_type, user_id, project_id, email, created_at, metadata_json
            )
            VALUES (?, 'sdk_installation', NULL, NULL, NULL, ?, ?)
            """,
            (event_id, created_at, json.dumps(metadata, sort_keys=True)),
        )
    return {"ok": True, "event_id": event_id, "created_at": created_at}


@app.get("/api/billing/plans")
def list_plans() -> Dict[str, Any]:
    init_db()
    with connect() as db:
        rows = db.execute(
            """
            SELECT id, name, max_projects, max_api_keys, monthly_workflow_limit,
                   created_at, metadata_json
            FROM plans
            ORDER BY
                CASE id WHEN 'free' THEN 1 WHEN 'pro' THEN 2 WHEN 'enterprise' THEN 3 ELSE 4 END
            """
        ).fetchall()
    plans = []
    for row in rows:
        plan = row_to_dict(row)
        plan["metadata"] = json.loads(plan.pop("metadata_json") or "{}")
        plans.append(plan)
    return {"ok": True, "plans": plans}


@app.get("/api/billing/me")
def billing_me(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        return {"ok": True, "billing": billing_summary(db, user["id"])}


@app.post("/api/billing/checkout")
def billing_checkout(
    payload: BillingCheckoutCreate,
    request: Request,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    plan_id = payload.plan_id.strip().lower()
    if plan_id == "free":
        with connect() as db:
            create_local_subscription(
                db,
                user["id"],
                "free",
                metadata={"source": "billing_checkout_free"},
            )
            summary = billing_summary(db, user["id"])
        return {"ok": True, "billing": summary, "message": "Switched to Free plan."}

    price_id = stripe_price_id_for_plan(plan_id)
    if not price_id:
        raise HTTPException(status_code=503, detail=f"Stripe price id is not configured for {plan_id}.")
    stripe = stripe_module()
    base_url = public_base_url(request)
    success_url = payload.success_url or STRIPE_SUCCESS_URL or f"{base_url}/dashboard?checkout=success"
    cancel_url = payload.cancel_url or STRIPE_CANCEL_URL or f"{base_url}/pricing?checkout=cancelled"
    with connect() as db:
        plan = db.execute("SELECT id FROM plans WHERE id = ?", (plan_id,)).fetchone()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found.")
        customer_id = ensure_stripe_customer(db, user)
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        client_reference_id=user["id"],
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"software_user_id": user["id"], "plan_id": plan_id},
        subscription_data={"metadata": {"software_user_id": user["id"], "plan_id": plan_id}},
    )
    return {
        "ok": True,
        "checkout_session_id": stripe_get(session, "id"),
        "checkout_url": stripe_get(session, "url"),
        "plan_id": plan_id,
        "stripe_customer_id": customer_id,
    }


@app.post("/api/billing/portal")
def billing_portal(
    request: Request,
    payload: BillingPortalCreate = BillingPortalCreate(),
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    stripe = stripe_module()
    base_url = public_base_url(request)
    return_url = payload.return_url or STRIPE_PORTAL_RETURN_URL or f"{base_url}/dashboard?billing=portal"
    with connect() as db:
        customer_id = ensure_stripe_customer(db, user)
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return {
        "ok": True,
        "portal_session_id": stripe_get(session, "id"),
        "portal_url": stripe_get(session, "url"),
        "stripe_customer_id": customer_id,
    }


@app.post("/api/billing/webhook")
async def billing_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
) -> Dict[str, Any]:
    payload = await request.body()
    if STRIPE_WEBHOOK_SECRET:
        try:
            import stripe  # type: ignore
        except ImportError as error:
            raise HTTPException(status_code=503, detail="Stripe package is not installed.") from error
        try:
            event = stripe.Webhook.construct_event(payload, stripe_signature, STRIPE_WEBHOOK_SECRET)
        except Exception as error:
            raise HTTPException(status_code=400, detail=f"Invalid Stripe webhook: {error}") from error
    else:
        if ENVIRONMENT == "production":
            raise HTTPException(status_code=503, detail="Stripe webhook secret is not configured.")
        try:
            event = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=400, detail="Invalid JSON webhook payload.") from error

    event_id = stripe_get(event, "id") or f"evt_local_{uuid.uuid4().hex}"
    event_type = stripe_get(event, "type", "unknown")
    event_object = stripe_nested(event, "data", "object", default={})
    processed_at = now_iso()
    result: Dict[str, Any] = {"handled": False}

    with connect() as db:
        existing = db.execute("SELECT id FROM stripe_events WHERE id = ?", (event_id,)).fetchone()
        if existing:
            return {"ok": True, "duplicate": True, "event_id": event_id, "event_type": event_type}

        if event_type in {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }:
            result = sync_stripe_subscription(db, event_object, event_type)
            result["handled"] = True
        elif event_type in {"invoice.payment_failed", "invoice.payment_succeeded"}:
            result = upsert_stripe_invoice(db, event_object, event_type)
            subscription_id = stripe_get(event_object, "subscription")
            if subscription_id:
                stripe_status = "payment_failed" if event_type == "invoice.payment_failed" else "payment_succeeded"
                db.execute(
                    """
                    UPDATE subscriptions
                    SET stripe_status = ?, updated_at = ?
                    WHERE stripe_subscription_id = ?
                    """,
                    (stripe_status, processed_at, subscription_id),
                )
            result["handled"] = True
        else:
            result = {"handled": False, "reason": "Event type ignored."}

        db.execute(
            """
            INSERT INTO stripe_events (id, event_type, processed_at, metadata_json)
            VALUES (?, ?, ?, ?)
            """,
            (event_id, event_type, processed_at, json.dumps({"result": result}, sort_keys=True)),
        )
        record_analytics_event(
            db,
            f"stripe_{event_type}",
            user_id=result.get("user_id"),
            metadata={"stripe_event_id": event_id, "result": result},
        )
    return {"ok": True, "event_id": event_id, "event_type": event_type, "result": result}


@app.post("/api/billing/subscribe")
def billing_subscribe(
    payload: SubscriptionChange,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    plan_id = payload.plan_id.strip().lower()
    with connect() as db:
        plan = db.execute("SELECT id FROM plans WHERE id = ?", (plan_id,)).fetchone()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found.")
        period_start, period_end = month_period()
        now = now_iso()
        db.execute(
            """
            UPDATE subscriptions
            SET status = 'cancelled', updated_at = ?
            WHERE user_id = ? AND status = 'active'
            """,
            (now, user["id"]),
        )
        db.execute(
            """
            INSERT INTO subscriptions (
                id, user_id, plan_id, status, current_period_start,
                current_period_end, created_at, updated_at, metadata_json
            )
            VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?)
            """,
            (
                f"sub_{uuid.uuid4().hex}",
                user["id"],
                plan_id,
                period_start,
                period_end,
                now,
                now,
                json.dumps({"checkout_placeholder": True}, sort_keys=True),
            ),
        )
        summary = billing_summary(db, user["id"])
    return {
        "ok": True,
        "billing": summary,
        "message": "Subscription changed locally. Connect a payment provider before production billing.",
    }


@app.get("/api/admin/usage-analytics")
def admin_usage_analytics(_: Dict[str, Any] = Depends(require_admin_user)) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        totals = db.execute(
            """
            SELECT metric_type, COALESCE(SUM(quantity), 0) AS total
            FROM usage_records
            GROUP BY metric_type
            ORDER BY total DESC
            """
        ).fetchall()
        by_user = db.execute(
            """
            SELECT users.email, usage_records.metric_type,
                   COALESCE(SUM(usage_records.quantity), 0) AS total
            FROM usage_records
            JOIN users ON users.id = usage_records.user_id
            GROUP BY users.id, usage_records.metric_type
            ORDER BY users.email ASC, usage_records.metric_type ASC
            """
        ).fetchall()
    return {
        "ok": True,
        "totals": [row_to_dict(row) for row in totals],
        "by_user": [row_to_dict(row) for row in by_user],
    }


@app.get("/api/admin/subscription-analytics")
def admin_subscription_analytics(_: Dict[str, Any] = Depends(require_admin_user)) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        by_plan = db.execute(
            """
            SELECT plans.id AS plan_id, plans.name AS plan_name,
                   COUNT(subscriptions.id) AS active_subscriptions
            FROM plans
            LEFT JOIN subscriptions
                ON subscriptions.plan_id = plans.id AND subscriptions.status = 'active'
            GROUP BY plans.id
            ORDER BY active_subscriptions DESC, plans.id ASC
            """
        ).fetchall()
        recent = db.execute(
            """
            SELECT subscriptions.id, users.email, subscriptions.plan_id,
                   subscriptions.status, subscriptions.current_period_start,
                   subscriptions.current_period_end, subscriptions.created_at
            FROM subscriptions
            JOIN users ON users.id = subscriptions.user_id
            ORDER BY subscriptions.created_at DESC
            LIMIT 50
            """
        ).fetchall()
    return {
        "ok": True,
        "by_plan": [row_to_dict(row) for row in by_plan],
        "recent_subscriptions": [row_to_dict(row) for row in recent],
    }


@app.get("/api/admin/customer-validation")
def admin_customer_validation(_: Dict[str, Any] = Depends(require_admin_user)) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        summary = customer_validation_summary(db)
    return {"ok": True, "customer_validation": summary}


@app.post("/api/install/api-key")
def create_install_api_key(
    payload: InstallApiKeyCreate,
    request: Request,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    project_name = payload.project_name.strip() or "my-agent"
    created_at = now_iso()
    try:
        with connect() as db:
            project = db.execute(
                """
                SELECT id, name, created_at
                FROM projects
                WHERE user_id = ?
                ORDER BY
                    CASE WHEN organization_id IS NULL THEN 0 ELSE 1 END,
                    created_at ASC
                LIMIT 1
                """,
                (user["id"],),
            ).fetchone()
            if project is None:
                enforce_limit(db, user["id"], "projects")
                project_id = f"prj_{uuid.uuid4().hex}"
                db.execute(
                    """
                    INSERT INTO projects (id, user_id, organization_id, name, created_at)
                    VALUES (?, ?, NULL, ?, ?)
                    """,
                    (project_id, user["id"], project_name, created_at),
                )
                record_analytics_event(
                    db,
                    "project_created",
                    user_id=user["id"],
                    project_id=project_id,
                    email=user["email"],
                    metadata={"project_name": project_name, "source": "simple_install"},
                )
                project = db.execute(
                    "SELECT id, name, created_at FROM projects WHERE id = ?",
                    (project_id,),
                ).fetchone()

            if project is None:
                raise HTTPException(status_code=500, detail="Could not prepare a project for this API key.")

            project_id = str(project["id"])
            project_display_name = str(project["name"])
            replaced_cursor = db.execute(
                """
                UPDATE api_keys
                SET is_active = 0
                WHERE user_id = ? AND is_active = 1
                """,
                (user["id"],),
            )
            replaced_existing_keys = max(0, int(replaced_cursor.rowcount or 0))
            enforce_limit(db, user["id"], "api_keys")
            generated = generate_api_key()
            key_id = f"key_{uuid.uuid4().hex}"
            db.execute(
                """
                INSERT INTO api_keys (
                    id, user_id, project_id, key_hash, key_prefix,
                    created_at, last_used_at, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, 1)
                """,
                (
                    key_id,
                    user["id"],
                    project_id,
                    generated["key_hash"],
                    generated["key_prefix"],
                    created_at,
                ),
            )
            record_analytics_event(
                db,
                "api_key_created",
                user_id=user["id"],
                project_id=project_id,
                email=user["email"],
                metadata={
                    "key_id": key_id,
                    "source": "simple_install",
                    "replaced_existing_keys": replaced_existing_keys,
                },
            )
    except HTTPException:
        raise
    except sqlite3.Error as error:
        LOGGER.exception("Install API key creation failed for user %s", user["id"])
        capture_operational_error(
            error,
            category="api_key_creation_failure",
            user_id=user["id"],
            operation="simple_install_api_key",
        )
        raise HTTPException(
            status_code=500,
            detail="Could not create your API key. Please try again in a moment.",
        ) from error

    api_url = public_base_url(request).rstrip("/")
    login_command = (
        f"software login --api-url {api_url} "
        f"--api-key {generated['api_key']} --project-name {project_display_name}"
    )
    return {
        "ok": True,
        "api_key": generated["api_key"],
        "api_url": api_url,
        "project": {"id": project_id, "name": project_display_name},
        "key": {
            "id": key_id,
            "project_id": project_id,
            "key_prefix": generated["key_prefix"],
            "created_at": created_at,
            "is_active": True,
            "replaced_existing_keys": replaced_existing_keys,
        },
        "commands": {
            "install": "pip install software-sdk",
            "login": login_command,
            "env": f"SOFTWARE_API_KEY={generated['api_key']}",
            "test": "software test",
        },
        "message": "Copy this API key now. It will not be shown again.",
    }


@app.post("/api/projects")
def create_project(payload: ProjectCreate, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    init_db()
    project_id = f"prj_{uuid.uuid4().hex}"
    created_at = now_iso()
    organization_id = payload.organization_id.strip() if payload.organization_id else None
    with connect() as db:
        enforce_limit(db, user["id"], "projects")
        organization_name = None
        organization_role = None
        if organization_id:
            membership = require_org_role(db, organization_id, user["id"], "admin")
            organization = organization_or_404(db, organization_id)
            organization_name = organization["name"]
            organization_role = membership["role"]
        db.execute(
            """
            INSERT INTO projects (id, user_id, organization_id, name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, user["id"], organization_id, payload.name.strip(), created_at),
        )
        record_analytics_event(
            db,
            "project_created",
            user_id=user["id"],
            project_id=project_id,
            email=user["email"],
            metadata={"project_name": payload.name.strip(), "organization_id": organization_id},
        )
    return {
        "ok": True,
        "project": {
            "id": project_id,
            "user_id": user["id"],
            "organization_id": organization_id,
            "organization_name": organization_name,
            "organization_role": organization_role,
            "name": payload.name.strip(),
            "created_at": created_at,
        },
    }


@app.get("/api/projects")
def list_projects(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        rows = db.execute(
            """
            SELECT projects.*,
                   organizations.name AS organization_name,
                   organization_members.role AS organization_role,
                   COUNT(DISTINCT sdk_workflows.workflow_id) AS workflow_count,
                   COUNT(DISTINCT api_keys.id) AS api_key_count
            FROM projects
            LEFT JOIN organizations ON organizations.id = projects.organization_id
            LEFT JOIN organization_members
                   ON organization_members.organization_id = projects.organization_id
                  AND organization_members.user_id = ?
            LEFT JOIN sdk_workflows ON sdk_workflows.project_id = projects.id
            LEFT JOIN api_keys ON api_keys.project_id = projects.id AND api_keys.is_active = 1
            WHERE projects.user_id = ? OR organization_members.user_id = ?
            GROUP BY projects.id
            ORDER BY projects.created_at DESC
            """,
            (user["id"], user["id"], user["id"]),
        ).fetchall()
    return {"ok": True, "projects": [row_to_dict(row) for row in rows]}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        project = user_project_or_404(db, user["id"], project_id)
        workflows = dashboard_sdk_payload([project_id])
    return {"ok": True, "project": row_to_dict(project), "sdk_workflows": workflows}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        project = user_project_or_404(db, user["id"], project_id)
        if project["organization_id"]:
            require_org_role(db, project["organization_id"], user["id"], "admin")
        elif project["user_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="Only the project owner can delete this project.")
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return {"ok": True, "deleted": True, "project_id": project_id}


@app.post("/api/projects/{project_id}/api-keys")
def create_project_api_key(
    project_id: str,
    _: APIKeyCreate = APIKeyCreate(),
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    generated = generate_api_key()
    key_id = f"key_{uuid.uuid4().hex}"
    created_at = now_iso()
    with connect() as db:
        project_permission_or_404(db, user["id"], project_id, "developer")
        enforce_limit(db, user["id"], "api_keys")
        db.execute(
            """
            INSERT INTO api_keys (
                id, user_id, project_id, key_hash, key_prefix,
                created_at, last_used_at, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, 1)
            """,
            (
                key_id,
                user["id"],
                project_id,
                generated["key_hash"],
                generated["key_prefix"],
                created_at,
            ),
        )
    return {
        "ok": True,
        "api_key": generated["api_key"],
        "message": "Copy this API key now. It will not be shown again.",
        "key": {
            "id": key_id,
            "project_id": project_id,
            "key_prefix": generated["key_prefix"],
            "created_at": created_at,
            "last_used_at": None,
            "is_active": True,
        },
    }


@app.get("/api/projects/{project_id}/api-keys")
def list_project_api_keys(project_id: str, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        project_permission_or_404(db, user["id"], project_id, "viewer")
        rows = db.execute(
            """
            SELECT id, project_id, key_prefix, created_at, last_used_at, is_active
            FROM api_keys
            WHERE project_id = ?
            ORDER BY created_at DESC
            """,
            (project_id,),
        ).fetchall()
    return {"ok": True, "api_keys": [row_to_dict(row) for row in rows]}


@app.delete("/api/projects/{project_id}/api-keys/{key_id}")
def delete_project_api_key(
    project_id: str,
    key_id: str,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        project_permission_or_404(db, user["id"], project_id, "developer")
        row = db.execute(
            """
            SELECT id FROM api_keys
            WHERE id = ? AND project_id = ?
            """,
            (key_id, project_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="API key not found.")
        db.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))
    return {"ok": True, "deleted": True, "key_id": key_id}


@app.get("/api/me/dashboard")
def api_me_dashboard(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    return {"ok": True, **user_dashboard_payload(user)}


@app.get("/api/dashboard")
def api_dashboard() -> Dict[str, Any]:
    return {"ok": True, **dashboard_payload()}


@app.get("/api/dashboard/overview")
def api_dashboard_overview() -> Dict[str, Any]:
    return {"ok": True, "overview": dashboard_overview_payload()}


@app.get("/api/dashboard/model-leaderboard")
def api_dashboard_model_leaderboard() -> Dict[str, Any]:
    return {"ok": True, "model_leaderboard": dashboard_model_leaderboard_payload()}


@app.get("/api/dashboard/tool-reliability")
def api_dashboard_tool_reliability() -> Dict[str, Any]:
    return {"ok": True, "tool_reliability": dashboard_tool_reliability_payload()}


@app.get("/api/dashboard/workflow-analytics")
def api_dashboard_workflow_analytics() -> Dict[str, Any]:
    return {"ok": True, "workflow_analytics": dashboard_workflow_analytics_payload()}


@app.get("/api/dashboard/prediction-analytics")
def api_dashboard_prediction_analytics() -> Dict[str, Any]:
    return {"ok": True, "prediction_analytics": dashboard_prediction_payload()}


@app.get("/api/dashboard/guardrail-analytics")
def api_dashboard_guardrail_analytics() -> Dict[str, Any]:
    return {"ok": True, "guardrail_analytics": dashboard_guardrail_payload()}


@app.get("/api/dashboard/recovery-analytics")
def api_dashboard_recovery_analytics() -> Dict[str, Any]:
    return {"ok": True, "recovery_analytics": recovery_summary()}


@app.get("/api/failure-analysis")
def api_failure_analysis(
    limit: int = Query(500, ge=1, le=2000),
    _: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    return {"ok": True, **failure_analysis_payload(limit)}


@app.get("/api/copilot/recommendations")
def api_copilot_recommendations(
    limit: int = Query(10, ge=1, le=50),
) -> Dict[str, Any]:
    return {"ok": True, "recommendations": copilot_recommendations_payload(limit=limit)}


@app.get("/api/copilot/summary")
def api_copilot_summary() -> Dict[str, Any]:
    return {"ok": True, "summary": copilot_summary_payload()}


@app.post("/api/decisions/validate")
def api_decision_validate(payload: DecisionValidateRequest) -> Dict[str, Any]:
    init_db()
    action = {
        **payload.action,
        "action_type": payload.action_type.strip(),
        "target": payload.target.strip(),
        "confidence": payload.confidence,
        "reason": payload.reason.strip(),
    }
    if payload.rollback_plan:
        action["rollback_plan"] = payload.rollback_plan
    with connect() as db:
        recommendation = recommendation_by_id(db, payload.recommendation_id)
        if recommendation is None and payload.recommendation_id:
            recommendation = {
                "id": payload.recommendation_id,
                "confidence": payload.confidence,
                "recommendation": payload.reason,
                "estimated_success_improvement": 0.0,
                "supporting_evidence": [],
            }
        decision = validate_ai_decision(
            db,
            recommendation=recommendation,
            action=action,
            source=payload.source.strip(),
            risk_level=payload.risk_level,
            metadata=payload.metadata,
        )
    return {"ok": True, "decision": decision}


@app.post("/api/decisions/approve")
def api_decision_approve(
    payload: DecisionApprovalRequest,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    decision = record_human_decision(
        decision_id=payload.decision_id,
        approver_user_id=user["id"],
        approved=True,
        reason=payload.reason,
    )
    return {"ok": True, "decision": decision}


@app.post("/api/decisions/reject")
def api_decision_reject(
    payload: DecisionApprovalRequest,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    decision = record_human_decision(
        decision_id=payload.decision_id,
        approver_user_id=user["id"],
        approved=False,
        reason=payload.reason,
    )
    return {"ok": True, "decision": decision}


@app.get("/api/decisions/pending")
def api_decisions_pending(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    return {"ok": True, "decisions": pending_decisions_payload(limit)}


@app.post("/api/optimizer/run")
def api_optimizer_run(payload: OptimizerRunRequest = OptimizerRunRequest()) -> Dict[str, Any]:
    result = run_optimizer(
        dry_run=payload.dry_run,
        min_confidence=payload.min_confidence,
        limit=payload.limit,
    )
    return {"ok": True, "optimizer": result, "stats": optimizer_stats_payload()}


@app.post("/api/optimizer/rollback")
def api_optimizer_rollback(payload: OptimizerRollbackRequest) -> Dict[str, Any]:
    result = rollback_optimizer_event(payload.event_id, dry_run=payload.dry_run)
    return {"ok": True, "rollback": result, "stats": optimizer_stats_payload()}


@app.get("/api/optimizer/history")
def api_optimizer_history(limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    return {"ok": True, "history": optimizer_history_payload(limit)}


@app.get("/api/optimizer/stats")
def api_optimizer_stats() -> Dict[str, Any]:
    return {"ok": True, "stats": optimizer_stats_payload()}


@app.get("/api/dashboard/historical-trends")
def api_dashboard_historical_trends() -> Dict[str, Any]:
    return {"ok": True, "historical_trends": dashboard_trends_payload()}


@app.get("/api/dashboard/sdk-workflows")
def api_dashboard_sdk_workflows() -> Dict[str, Any]:
    return {"ok": True, "sdk_workflows": dashboard_sdk_payload()}


@app.get("/api/sdk/status")
def sdk_status(api_key_context: Dict[str, Any] = Depends(require_sdk_api_key)) -> Dict[str, Any]:
    base_url = PUBLIC_BASE_URL or ""
    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "environment": ENVIRONMENT,
        "project": {
            "id": api_key_context["project_id"],
            "name": api_key_context["project_name"],
        },
        "api_key": {
            "id": api_key_context["api_key_id"],
            "prefix": api_key_context["key_prefix"],
            "last_used_at": api_key_context["last_used_at"],
        },
        "dashboard_url": f"{base_url}/dashboard" if base_url else "/dashboard",
        "onboarding_url": f"{base_url}/onboarding" if base_url else "/onboarding",
    }


@app.post("/api/sdk/test-workflow")
def sdk_test_workflow(
    payload: SDKTestWorkflowRequest,
    api_key_context: Dict[str, Any] = Depends(require_sdk_api_key),
) -> Dict[str, Any]:
    init_db()
    workflow_id = f"wf_install_test_{uuid.uuid4().hex}"
    started_at = now_iso()
    completed_at = now_iso()
    project_name = payload.project_name or api_key_context["project_name"]
    workflow_name = payload.workflow_name
    metadata = {
        "source": "install_page",
        **payload.metadata,
    }
    with connect() as db:
        enforce_limit(db, api_key_context["user_id"], "workflows")
        db.execute(
            """
            INSERT INTO sdk_workflows (
                workflow_id, user_id, project_id, api_key_id,
                project_name, workflow_name, status, success, confidence,
                predicted_failure_probability, guardrail_action, total_latency_ms,
                started_at, completed_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, 'completed', 1, 0.99, 0.05, 'continue', 46, ?, ?, ?)
            """,
            (
                workflow_id,
                api_key_context["user_id"],
                api_key_context["project_id"],
                api_key_context["api_key_id"],
                project_name,
                workflow_name,
                started_at,
                completed_at,
                json_dumps(metadata),
            ),
        )
        sdk_insert_event(
            db,
            workflow_id,
            "workflow_start",
            name=workflow_name,
            payload={"project_name": project_name, "metadata": metadata},
        )
        sdk_insert_event(
            db,
            workflow_id,
            "stage",
            stage_name="install_test",
            name="completed",
            success=True,
            latency_ms=12,
            confidence=0.99,
            payload={"metadata": metadata},
        )
        sdk_insert_event(
            db,
            workflow_id,
            "tool_call",
            stage_name="install_test",
            tool_name="install_page",
            name="install_page",
            success=True,
            latency_ms=24,
            confidence=0.99,
            payload={"result_count": 1, "metadata": metadata},
        )
        sdk_insert_event(
            db,
            workflow_id,
            "workflow_complete",
            success=True,
            latency_ms=46,
            confidence=0.99,
            payload={"metadata": metadata, "guardrail": {"action": "continue", "should_continue": True}},
        )
        record_usage(
            db,
            api_key_context["user_id"],
            "workflow",
            project_id=api_key_context["project_id"],
            api_key_id=api_key_context["api_key_id"],
            metadata={"workflow_id": workflow_id, "workflow_name": workflow_name, "source": "install_page"},
        )
        record_usage(
            db,
            api_key_context["user_id"],
            "tool_call",
            project_id=api_key_context["project_id"],
            api_key_id=api_key_context["api_key_id"],
            metadata={"workflow_id": workflow_id, "tool_name": "install_page"},
        )
    return {
        "ok": True,
        "workflow_id": workflow_id,
        "project": {
            "id": api_key_context["project_id"],
            "name": api_key_context["project_name"],
        },
        "started_at": started_at,
        "completed_at": completed_at,
        "dashboard_url": f"{PUBLIC_BASE_URL}/dashboard" if PUBLIC_BASE_URL else "/dashboard",
        "message": "SDK test workflow recorded.",
    }


@app.post("/api/sdk/workflows/start")
def sdk_start_workflow(
    payload: SDKWorkflowStart,
    api_key_context: Dict[str, Any] = Depends(require_sdk_api_key),
) -> Dict[str, Any]:
    init_db()
    workflow_id = payload.workflow_id or f"wf_{uuid.uuid4().hex}"
    set_monitoring_context(
        user_id=api_key_context["user_id"],
        workflow_id=workflow_id,
        agent_name=str(payload.metadata.get("agent_name") or "") or None,
        project_id=api_key_context["project_id"],
    )
    composio_context = get_composio_tool_context(api_key_context["user_id"])
    started_at = now_iso()
    with connect() as db:
        existing_workflow = db.execute(
            "SELECT workflow_id FROM sdk_workflows WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchone()
        if not existing_workflow:
            enforce_limit(db, api_key_context["user_id"], "workflows")
        db.execute(
            """
            INSERT OR REPLACE INTO sdk_workflows (
                workflow_id, user_id, project_id, api_key_id,
                project_name, workflow_name, status, success, confidence,
                predicted_failure_probability, guardrail_action, total_latency_ms,
                started_at, completed_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, 'running', NULL, NULL, NULL, NULL, 0, ?, NULL, ?)
            """,
            (
                workflow_id,
                api_key_context["user_id"],
                api_key_context["project_id"],
                api_key_context["api_key_id"],
                payload.project_name,
                payload.workflow_name,
                started_at,
                json_dumps(payload.metadata),
            ),
        )
        sdk_insert_event(
            db,
            workflow_id,
            "workflow_start",
            name=payload.workflow_name,
            payload={"project_name": payload.project_name, "metadata": payload.metadata},
        )
        if not existing_workflow:
            record_usage(
                db,
                api_key_context["user_id"],
                "workflow",
                project_id=api_key_context["project_id"],
                api_key_id=api_key_context["api_key_id"],
                metadata={"workflow_id": workflow_id, "workflow_name": payload.workflow_name},
            )
    return {
        "ok": True,
        "workflow_id": workflow_id,
        "started_at": started_at,
        "agent_tools": composio_context["tools"],
        "composio": {
            key: value
            for key, value in composio_context.items()
            if key != "tools"
        },
    }


@app.get("/api/sdk/tools")
def sdk_get_composio_tools(
    api_key_context: Dict[str, Any] = Depends(require_sdk_api_key),
) -> Dict[str, Any]:
    return {
        "ok": True,
        "composio": get_composio_tool_context(api_key_context["user_id"]),
    }


@app.post("/api/sdk/tools/refresh")
def sdk_refresh_composio_tools(
    api_key_context: Dict[str, Any] = Depends(require_sdk_api_key),
) -> Dict[str, Any]:
    tools = refresh_composio_tools(api_key_context["user_id"])
    return {
        "ok": True,
        "tools": composio_tool_descriptors(tools),
        "composio": get_composio_tool_context(api_key_context["user_id"]),
    }


@app.post("/api/sdk/tools/execute")
def sdk_execute_composio_tool(
    payload: ComposioToolExecuteRequest,
    api_key_context: Dict[str, Any] = Depends(require_sdk_api_key),
) -> Dict[str, Any]:
    init_db()
    started = time.perf_counter()
    with connect() as db:
        sdk_fetch_owned_workflow(db, payload.workflow_id, api_key_context)

    result = execute_composio_tool(
        api_key_context["user_id"],
        payload.tool_slug,
        payload.arguments,
        account=payload.account,
        workflow_id=payload.workflow_id,
        agent_name=payload.agent_name,
        chat_id=payload.chat_id,
        return_to=payload.return_to,
    )
    latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    connection_required = bool(result.get("connection_required"))
    with connect() as db:
        event_id = sdk_insert_event(
            db,
            payload.workflow_id,
            "tool_call",
            stage_name="composio",
            tool_name=payload.tool_slug.upper(),
            name=payload.tool_slug.upper(),
            success=None if connection_required else bool(result["ok"]),
            latency_ms=latency_ms,
            error_type=(
                None
                if result["ok"] or connection_required
                else "connected_app_action_failure"
            ),
            error_message=result.get("error"),
            payload={
                "provider": "connected_apps",
                "log_id": result.get("log_id"),
                "agent_name": payload.agent_name,
                "connection_required": connection_required,
                "pending_action_id": result.get("pending_action_id"),
            },
        )
        record_usage(
            db,
            api_key_context["user_id"],
            "tool_call",
            project_id=api_key_context["project_id"],
            api_key_id=api_key_context["api_key_id"],
            metadata={
                "workflow_id": payload.workflow_id,
                "tool_name": payload.tool_slug.upper(),
                "provider": "connected_apps",
                "success": None if connection_required else bool(result["ok"]),
            },
        )
    return {
        "ok": bool(result["ok"]),
        "connection_required": connection_required,
        "app": result.get("app"),
        "pending_action_id": result.get("pending_action_id"),
        "message": result.get("message"),
        "event_id": event_id,
        "workflow_id": payload.workflow_id,
        "tool_slug": payload.tool_slug.upper(),
        "latency_ms": latency_ms,
        "result": result,
    }


@app.post("/api/sdk/workflows/stage")
def sdk_track_stage(
    payload: SDKStageEvent,
    api_key_context: Dict[str, Any] = Depends(require_sdk_api_key),
) -> Dict[str, Any]:
    set_monitoring_context(
        user_id=api_key_context["user_id"],
        workflow_id=payload.workflow_id,
        agent_name=str(payload.metadata.get("agent_name") or "") or None,
        stage_name=payload.stage_name,
    )
    init_db()
    with connect() as db:
        sdk_fetch_owned_workflow(db, payload.workflow_id, api_key_context)
        event_id = sdk_insert_event(
            db,
            payload.workflow_id,
            "stage",
            stage_name=payload.stage_name,
            name=payload.status,
            success=payload.success,
            latency_ms=payload.latency_ms,
            confidence=payload.confidence,
            payload={"metadata": payload.metadata},
        )
    return {"ok": True, "event_id": event_id}


@app.get("/api/sdk/docs")
def api_sdk_docs() -> Dict[str, Any]:
    return {
        "ok": True,
        "auth_required_for_install": False,
        "auth_required_for_docs": False,
        "install": {
            "python": "pip install software-sdk",
            "node": "npm install software-sdk",
            "github": "pip install git+https://github.com/Tejaswin846/software-reliability-engine.git",
            "local": "pip install -e .",
        },
        "public_local_mode": [
            "local validation",
            "local plan creation",
            "dry-run examples",
            "sandbox workflow tests",
        ],
        "authenticated_cloud_mode": [
            "cloud workflow execution",
            "saved projects",
            "user memory",
            "audit logs",
            "external app integrations",
            "team/workspace features",
        ],
        "optional_cloud_login": ["software login", "SOFTWARE_API_KEY=..."],
    }


@app.post("/api/sdk/workflows/model-call")
def sdk_log_model_call(
    payload: SDKModelCall,
    api_key_context: Dict[str, Any] = Depends(require_sdk_api_key),
) -> Dict[str, Any]:
    agent_name = str(payload.metadata.get("agent_name") or payload.stage_name or "") or None
    set_monitoring_context(
        user_id=api_key_context["user_id"],
        workflow_id=payload.workflow_id,
        agent_name=agent_name,
        model=payload.model,
        stage_name=payload.stage_name,
    )
    init_db()
    with connect() as db:
        sdk_fetch_owned_workflow(db, payload.workflow_id, api_key_context)
        event_id = sdk_insert_event(
            db,
            payload.workflow_id,
            "model_call",
            stage_name=payload.stage_name,
            model=payload.model,
            name=payload.model,
            success=payload.success,
            latency_ms=payload.latency_ms,
            confidence=payload.confidence,
            payload={"metadata": payload.metadata},
        )
        record_usage(
            db,
            api_key_context["user_id"],
            "model_call",
            project_id=api_key_context["project_id"],
            api_key_id=api_key_context["api_key_id"],
            metadata={"workflow_id": payload.workflow_id, "model": payload.model},
        )
    if not payload.success:
        normalized_model = payload.model.lower()
        provider = (
            "openai"
            if "openai" in normalized_model or normalized_model.startswith("gpt")
            else "anthropic"
            if "anthropic" in normalized_model or "claude" in normalized_model
            else "model_provider"
        )
        capture_operational_error(
            f"Model call failed: {payload.model}",
            category=f"{provider}_api_error",
            user_id=api_key_context["user_id"],
            workflow_id=payload.workflow_id,
            agent_name=agent_name,
            provider=provider,
            model=payload.model,
            stage_name=payload.stage_name,
        )
    return {"ok": True, "event_id": event_id}


@app.post("/api/sdk/workflows/tool-call")
def sdk_log_tool_call(
    payload: SDKToolCall,
    api_key_context: Dict[str, Any] = Depends(require_sdk_api_key),
) -> Dict[str, Any]:
    agent_name = str(payload.metadata.get("agent_name") or payload.stage_name or "") or None
    set_monitoring_context(
        user_id=api_key_context["user_id"],
        workflow_id=payload.workflow_id,
        agent_name=agent_name,
        tool_name=payload.tool_name,
        stage_name=payload.stage_name,
    )
    init_db()
    with connect() as db:
        sdk_fetch_owned_workflow(db, payload.workflow_id, api_key_context)
        event_id = sdk_insert_event(
            db,
            payload.workflow_id,
            "tool_call",
            stage_name=payload.stage_name,
            tool_name=payload.tool_name,
            name=payload.tool_name,
            success=payload.success,
            latency_ms=payload.latency_ms,
            confidence=payload.confidence,
            payload={"result_count": payload.result_count, "metadata": payload.metadata},
        )
        record_usage(
            db,
            api_key_context["user_id"],
            "tool_call",
            project_id=api_key_context["project_id"],
            api_key_id=api_key_context["api_key_id"],
            metadata={"workflow_id": payload.workflow_id, "tool_name": payload.tool_name},
        )
    if not payload.success:
        capture_operational_error(
            f"External tool call failed: {payload.tool_name}",
            category="external_http_or_tool_failure",
            user_id=api_key_context["user_id"],
            workflow_id=payload.workflow_id,
            agent_name=agent_name,
            tool_name=payload.tool_name,
            stage_name=payload.stage_name,
        )
    return {"ok": True, "event_id": event_id}


@app.post("/api/sdk/workflows/error")
def sdk_log_error(
    payload: SDKErrorEvent,
    api_key_context: Dict[str, Any] = Depends(require_sdk_api_key),
) -> Dict[str, Any]:
    agent_name = str(payload.metadata.get("agent_name") or payload.stage_name or "") or None
    set_monitoring_context(
        user_id=api_key_context["user_id"],
        workflow_id=payload.workflow_id,
        agent_name=agent_name,
        failure_type=payload.error_type,
        stage_name=payload.stage_name,
    )
    init_db()
    with connect() as db:
        workflow = sdk_fetch_owned_workflow(db, payload.workflow_id, api_key_context)
        event_id = sdk_insert_event(
            db,
            payload.workflow_id,
            "error",
            stage_name=payload.stage_name,
            name=payload.error_type,
            success=False,
            error_type=payload.error_type,
            error_message=payload.error_message,
            payload={"fatal": payload.fatal, "metadata": payload.metadata},
        )
        if payload.fatal:
            db.execute(
                "UPDATE sdk_workflows SET status = 'failed', success = 0 WHERE workflow_id = ?",
                (payload.workflow_id,),
            )
            events = sdk_fetch_events(db, payload.workflow_id)
            record_failure(
                db,
                source="sdk",
                workflow_id=payload.workflow_id,
                workflow_name=workflow["workflow_name"],
                failure_reason=payload.error_type or payload.error_message,
                execution_duration=float(workflow["total_latency_ms"] or 0) / 1000.0,
                retry_count=sdk_retry_count(events),
                created_at=now_iso(),
                metadata={
                    "project_name": workflow["project_name"],
                    "stage_name": payload.stage_name,
                    "fatal": payload.fatal,
                },
            )
    capture_operational_error(
        payload.error_message,
        category="agent_execution_error",
        level="error" if payload.fatal else "warning",
        user_id=api_key_context["user_id"],
        workflow_id=payload.workflow_id,
        agent_name=agent_name,
        failure_type=payload.error_type,
        stage_name=payload.stage_name,
    )
    return {"ok": True, "event_id": event_id}


@app.post("/api/sdk/workflows/complete")
def sdk_complete_workflow(
    payload: SDKWorkflowComplete,
    api_key_context: Dict[str, Any] = Depends(require_sdk_api_key),
) -> Dict[str, Any]:
    init_db()
    completed_at = now_iso()
    with connect() as db:
        workflow = sdk_fetch_owned_workflow(db, payload.workflow_id, api_key_context)
        events = sdk_fetch_events(db, payload.workflow_id)
        calculated_latency = sum(int(event["latency_ms"] or 0) for event in events)
        total_latency_ms = payload.total_latency_ms if payload.total_latency_ms is not None else calculated_latency
        probability = sdk_failure_probability_from_events(events)
        guardrail = sdk_guardrail_action(probability)
        db.execute(
            """
            UPDATE sdk_workflows
            SET status = 'completed', success = ?, confidence = ?,
                predicted_failure_probability = ?, guardrail_action = ?,
                total_latency_ms = ?, completed_at = ?, metadata_json = ?
            WHERE workflow_id = ?
            """,
            (
                1 if payload.success else 0,
                payload.confidence,
                probability,
                guardrail["action"],
                total_latency_ms,
                completed_at,
                json_dumps(payload.metadata),
                payload.workflow_id,
            ),
        )
        sdk_insert_event(
            db,
            payload.workflow_id,
            "workflow_complete",
            success=payload.success,
            latency_ms=total_latency_ms,
            confidence=payload.confidence,
            payload={"metadata": payload.metadata, "guardrail": guardrail},
        )
        if not payload.success:
            record_failure(
                db,
                source="sdk",
                workflow_id=payload.workflow_id,
                workflow_name=workflow["workflow_name"],
                failure_reason=sdk_failure_reason_from_events(events),
                execution_duration=float(total_latency_ms or 0) / 1000.0,
                retry_count=sdk_retry_count(events),
                created_at=completed_at,
                metadata={
                    "project_name": workflow["project_name"],
                    "guardrail_action": guardrail["action"],
                    "probability_of_failure": probability,
                },
            )
    return {
        "ok": True,
        "workflow_id": payload.workflow_id,
        "completed_at": completed_at,
        "probability_of_failure": probability,
        "probability_of_success": round(1.0 - probability, 4),
        "guardrail": guardrail,
    }


@app.post("/api/sdk/workflows/predict")
def sdk_predict_workflow(
    payload: SDKPredictRequest,
    api_key_context: Dict[str, Any] = Depends(require_sdk_api_key),
) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        sdk_fetch_owned_workflow(db, payload.workflow_id, api_key_context)
        events = sdk_fetch_events(db, payload.workflow_id)
        probability = sdk_failure_probability_from_events(events)
    return {
        "ok": True,
        "workflow_id": payload.workflow_id,
        "probability_of_failure": probability,
        "probability_of_success": round(1.0 - probability, 4),
        "guardrail": sdk_guardrail_action(probability),
    }


@app.post("/api/sdk/workflows/recover")
def sdk_recover_workflow(
    payload: SDKRecoveryRequest,
    api_key_context: Dict[str, Any] = Depends(require_sdk_api_key),
) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        workflow = sdk_fetch_owned_workflow(db, payload.workflow_id, api_key_context)
        events = sdk_fetch_events(db, payload.workflow_id)
        classifier = classify_failure(events)
        category = classifier["failure_category"]
        existing_count = int(
            db.execute(
                "SELECT COUNT(*) FROM recovery_events WHERE workflow_id = ?",
                (payload.workflow_id,),
            ).fetchone()[0]
        )
        action = recovery_action_for_category(category, existing_count + 1)
        if payload.auto_apply:
            recovery = insert_recovery_event(db, workflow, category, action, classifier)
            sdk_insert_event(
                db,
                payload.workflow_id,
                "recovery",
                name=action["recovery_action"],
                success=action["success"],
                latency_ms=action["latency_ms"],
                payload={"failure_category": category, "classifier": classifier},
            )
        else:
            recovery = {
                "workflow_id": payload.workflow_id,
                "failure_category": category,
                "recovery_action": action["recovery_action"],
                "attempt_number": existing_count + 1,
                "success": action["success"],
                "recovery_latency_ms": action["latency_ms"],
                "reason": action["reason"],
            }
    return {
        "ok": True,
        "workflow_id": payload.workflow_id,
        "failure_category": category,
        "classifier": classifier,
        "recovery": recovery,
    }


@app.get("/v1/reliability/health")
def health() -> Dict[str, Any]:
    init_db()
    return {
        "ok": True,
        "service": "software-reliability-engine",
        "version": APP_VERSION,
        "database": str(DB_PATH),
    }


def persist_benchmark_run(
    payload: BenchmarkRunCreate,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    init_db()
    validate_counts(payload)
    run_id = payload.run_id or make_run_id(payload.model)
    created_at = now_iso()
    metrics = build_metrics_from_summary(
        model=payload.model,
        benchmark_status="api_created",
        total_workflows=payload.total_workflows,
        successful_workflows=payload.successful,
        failed_workflows=payload.failed,
        retries=payload.retries,
        rollbacks=payload.rollbacks,
        escalations=payload.escalations,
        stops=payload.stops,
        average_execution_time_seconds=payload.average_execution_time,
        average_confidence=payload.average_confidence,
        simulation_success_rate=payload.simulation_success_rate,
        tool_reliability=payload.tool_reliability,
        timeout_rate=payload.timeout_rate,
        data_completeness=payload.data_completeness,
        notes="Created through Software Reliability Engine API.",
    )

    try:
        with connect() as db:
            db.execute(
                """
                INSERT INTO benchmark_runs (
                    run_id, user_id, model, provider_url, environment, total_workflows, successful,
                    failed, success_rate, failure_rate, reliability_score_v2,
                    reliability_band_v2, average_execution_time, average_confidence,
                    created_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    user_id,
                    payload.model,
                    payload.provider_url,
                    payload.environment,
                    payload.total_workflows,
                    payload.successful,
                    payload.failed,
                    metrics.success_rate,
                    metrics.failure_rate,
                    metrics.reliability_score_v2,
                    metrics.reliability_band_v2,
                    payload.average_execution_time,
                    payload.average_confidence,
                    created_at,
                    json.dumps(payload.metadata, ensure_ascii=False),
                ),
            )
            db.execute(
                """
                INSERT INTO model_results (
                    id, run_id, user_id, model, provider_url, success_rate, failure_rate,
                    retry_rate, recovery_rate, tool_reliability, timeout_rate,
                    average_execution_time, confidence_accuracy, reliability_score_v2,
                    reliability_band_v2, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"model_result_{uuid.uuid4().hex[:12]}",
                    run_id,
                    user_id,
                    payload.model,
                    payload.provider_url,
                    metrics.success_rate,
                    metrics.failure_rate,
                    metrics.retry_rate,
                    metrics.recovery_rate,
                    metrics.tool_reliability,
                    metrics.timeout_rate,
                    payload.average_execution_time,
                    metrics.confidence_accuracy,
                    metrics.reliability_score_v2,
                    metrics.reliability_band_v2,
                    created_at,
                ),
            )
            db.execute(
                """
                INSERT INTO reliability_scores (
                    id, run_id, user_id, model, reliability_score_v1, reliability_score_v2,
                    reliability_band_v1, reliability_band_v2, success_rate, failure_rate,
                    retry_rate, recovery_rate, retry_success_rate, tool_reliability,
                    timeout_rate, confidence_accuracy, average_execution_time_ms,
                    execution_time_score, escalation_rate, workflow_completion_rate,
                    simulation_success_rate, simulation_gap, data_completeness, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"score_{uuid.uuid4().hex[:12]}",
                    run_id,
                    user_id,
                    payload.model,
                    metrics.reliability_score_v1,
                    metrics.reliability_score_v2,
                    metrics.reliability_band_v1,
                    metrics.reliability_band_v2,
                    metrics.success_rate,
                    metrics.failure_rate,
                    metrics.retry_rate,
                    metrics.recovery_rate,
                    metrics.retry_success_rate,
                    metrics.tool_reliability,
                    metrics.timeout_rate,
                    metrics.confidence_accuracy,
                    metrics.average_execution_time_ms,
                    metrics.execution_time_score,
                    metrics.escalation_rate,
                    metrics.workflow_completion_rate,
                    metrics.simulation_success_rate,
                    metrics.simulation_gap,
                    metrics.data_completeness,
                    created_at,
                ),
            )
            for workflow in payload.workflows:
                db.execute(
                    """
                    INSERT INTO workflow_results (
                        id, run_id, workflow_id, status, successful, failed_agent,
                        failure_reason, execution_time, confidence, retry_count,
                        rollback_count, escalation_count, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"workflow_result_{uuid.uuid4().hex[:12]}",
                        run_id,
                        workflow.workflow_id,
                        workflow.status,
                        1 if workflow.successful else 0,
                        workflow.failed_agent,
                        workflow.failure_reason,
                        workflow.execution_time,
                        workflow.confidence,
                        workflow.retry_count,
                        workflow.rollback_count,
                        workflow.escalation_count,
                        created_at,
                    ),
                )
                if not workflow.successful:
                    record_failure(
                        db,
                        source="benchmark",
                        run_id=run_id,
                        workflow_id=workflow.workflow_id,
                        workflow_name=payload.model,
                        failure_reason=workflow.failure_reason or workflow.failed_agent or workflow.status,
                        execution_duration=workflow.execution_time,
                        retry_count=workflow.retry_count,
                        created_at=created_at,
                        metadata={
                            "failed_agent": workflow.failed_agent,
                            "status": workflow.status,
                            "rollback_count": workflow.rollback_count,
                            "escalation_count": workflow.escalation_count,
                            "environment": payload.environment,
                        },
                    )
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail=f"Could not create benchmark run: {error}") from error

    sync_benchmark_to_dashboard_db(run_id, payload, metrics, created_at)
    supabase_sync = supabase_save_benchmark_run(
        {
            "run_id": run_id,
            "user_id": user_id,
            "model": payload.model,
            "provider_url": payload.provider_url,
            "environment": payload.environment,
            "total_workflows": payload.total_workflows,
            "successful": payload.successful,
            "failed": payload.failed,
            "success_rate": metrics.success_rate,
            "failure_rate": metrics.failure_rate,
            "reliability_score_v2": metrics.reliability_score_v2,
            "reliability_band_v2": metrics.reliability_band_v2,
            "average_execution_time": payload.average_execution_time,
            "average_confidence": payload.average_confidence,
            "retries": payload.retries,
            "rollbacks": payload.rollbacks,
            "escalations": payload.escalations,
            "stops": payload.stops,
            "tool_reliability": metrics.tool_reliability,
            "timeout_rate": metrics.timeout_rate,
            "created_at": created_at,
            "metadata": payload.metadata,
            "workflow_results": [workflow.model_dump() for workflow in payload.workflows],
        }
    )

    return {
        "ok": True,
        "run": fetch_run(run_id),
        "score": fetch_score(run_id),
        "workflow_results_count": len(payload.workflows),
        "supabase_sync": {
            "ok": bool(supabase_sync.get("ok")),
            "available": bool(supabase_sync.get("available")),
            "error": supabase_sync.get("error"),
        },
    }


@app.post("/v1/reliability/benchmark-runs")
def create_benchmark_run(
    payload: BenchmarkRunCreate,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    return persist_benchmark_run(payload, user["id"])


@app.get("/api/benchmark-runner/history")
def benchmark_runner_history(
    limit: int = Query(20, ge=1, le=200),
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        rows = db.execute(
            """
            SELECT *
            FROM benchmark_runs
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user["id"], limit),
        ).fetchall()
    return {
        "ok": True,
        "overview": user_benchmark_overview(user["id"]),
        "trends": user_benchmark_trends(user["id"]),
        "runs": [row_to_dict(row) for row in rows],
    }


@app.post("/api/benchmark-runner/run")
def run_benchmark_from_runner(
    payload: BenchmarkRunnerRequest,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    lock_resource = f"benchmark:{user['id']}:{payload.model}"
    with redis_distributed_lock(
        lock_resource,
        ttl_seconds=120,
        wait_seconds=0.25,
    ) as lock:
        if not lock["acquired"]:
            raise HTTPException(
                status_code=409,
                detail="A benchmark for this model is already running.",
            )
        benchmark_payload = build_simulated_benchmark_payload(payload)
        result = persist_benchmark_run(benchmark_payload, user["id"])
    queue_result = redis_enqueue_background_job(
        "benchmark.dashboard.refresh",
        {
            "user_id": user["id"],
            "run_id": result["run"]["run_id"],
        },
    )
    return {
        "ok": True,
        "message": "Benchmark run completed.",
        **result,
        "background_job_queued": bool(queue_result["ok"]),
        "overview": user_benchmark_overview(user["id"]),
        "trends": user_benchmark_trends(user["id"]),
    }


@app.post("/api/benchmark-runner/sample-data")
def generate_benchmark_sample_data(
    payload: BenchmarkSampleRequest,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    scenarios = ["success", "mixed", "failure", "mixed", "success", "mixed"]
    created: List[Dict[str, Any]] = []
    for index in range(payload.runs):
        scenario = scenarios[index % len(scenarios)]
        target = 92 - (index * 4) if scenario == "success" else None
        request = BenchmarkRunnerRequest(
            model="sample-agent",
            provider_url="sample-generator",
            workflow_count=payload.workflow_count,
            scenario=scenario,
            target_success_rate=target,
            seed=payload.seed + index if payload.seed is not None else None,
        )
        result = persist_benchmark_run(
            build_simulated_benchmark_payload(request, run_index=index, sample_mode=True),
            user["id"],
        )
        created.append(
            {
                "run_id": result["run"]["run_id"],
                "model": result["run"]["model"],
                "success_rate": result["run"]["success_rate"],
                "failure_rate": result["run"]["failure_rate"],
                "reliability_score_v2": result["run"]["reliability_score_v2"],
            }
        )
    return {
        "ok": True,
        "message": f"Generated {len(created)} sample benchmark runs.",
        "created": created,
        "overview": user_benchmark_overview(user["id"]),
        "trends": user_benchmark_trends(user["id"]),
    }


@app.get("/v1/reliability/benchmark-runs")
def list_benchmark_runs(
    limit: int = Query(50, ge=1, le=500),
    model: Optional[str] = None,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    query = "SELECT * FROM benchmark_runs WHERE user_id = ?"
    params: List[Any] = [user["id"]]
    if model:
        query += " AND model = ?"
        params.append(model)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with connect() as db:
        rows = db.execute(query, params).fetchall()
    return {"ok": True, "runs": [row_to_dict(row) for row in rows]}


@app.get("/v1/reliability/benchmark-runs/{run_id}")
def get_benchmark_run(
    run_id: str,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        owned = db.execute(
            "SELECT 1 FROM benchmark_runs WHERE run_id = ? AND user_id = ?",
            (run_id, user["id"]),
        ).fetchone()
    if not owned:
        raise HTTPException(status_code=404, detail="Benchmark run not found.")
    return {
        "ok": True,
        "run": fetch_run(run_id),
        "score": fetch_score(run_id),
        "workflow_results": fetch_workflows(run_id),
    }


@app.get("/v1/reliability/benchmark-runs/{run_id}/report")
def get_benchmark_report(
    run_id: str,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    get_benchmark_run(run_id, user)
    run = fetch_run(run_id)
    score = fetch_score(run_id)
    workflows = fetch_workflows(run_id)
    return {
        "ok": True,
        "run_id": run_id,
        "run": run,
        "score": score,
        "workflow_results": workflows,
        "markdown": build_markdown_report(run, score, workflows),
    }


@app.get("/v1/reliability/benchmark-runs/{run_id}/export.md", response_class=PlainTextResponse)
def export_benchmark_markdown(
    run_id: str,
    user: Dict[str, Any] = Depends(current_user),
) -> str:
    init_db()
    get_benchmark_run(run_id, user)
    return build_markdown_report(fetch_run(run_id), fetch_score(run_id), fetch_workflows(run_id))


@app.get("/v1/reliability/leaderboard")
def leaderboard(
    limit: int = Query(20, ge=1, le=100),
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        rows = db.execute(
            """
            SELECT
                model,
                MAX(reliability_score_v2) AS reliability_score_v2,
                MAX(success_rate) AS success_rate,
                MIN(failure_rate) AS failure_rate,
                AVG(average_execution_time) AS average_execution_time,
                COUNT(*) AS benchmark_runs
            FROM model_results
            WHERE user_id = ?
            GROUP BY model
            ORDER BY reliability_score_v2 DESC, success_rate DESC
            LIMIT ?
            """,
            (user["id"], limit),
        ).fetchall()
    entries = []
    for index, row in enumerate(rows, start=1):
        item = row_to_dict(row)
        item["rank"] = index
        entries.append(item)
    return {"ok": True, "leaderboard": entries}


@app.get("/v1/reliability/compare/models")
def compare_models(
    models: Optional[str] = None,
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    init_db()
    selected = [item.strip() for item in (models or "").split(",") if item.strip()]
    params: List[Any] = []
    query = """
        SELECT *
        FROM model_results
        WHERE user_id = ?
    """
    params.append(user["id"])
    if selected:
        placeholders = ",".join("?" for _ in selected)
        query += f" AND model IN ({placeholders})"
        params.extend(selected)
    query += " ORDER BY reliability_score_v2 DESC, success_rate DESC, created_at DESC"
    with connect() as db:
        rows = db.execute(query, params).fetchall()
    return {
        "ok": True,
        "models": selected,
        "results": [row_to_dict(row) for row in rows],
    }


@app.get("/v1/reliability/dashboard")
def dashboard(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    init_db()
    with connect() as db:
        latest = db.execute(
            "SELECT * FROM benchmark_runs WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
        trend_rows = db.execute(
            """
            SELECT created_at, model, reliability_score_v2, success_rate, failure_rate,
                   average_execution_time, average_confidence
            FROM benchmark_runs
            WHERE user_id = ?
            ORDER BY created_at ASC
            LIMIT 200
            """,
            (user["id"],),
        ).fetchall()
    return {
        "ok": True,
        "latest_run": row_to_dict(latest) if latest else None,
        "historical_trends": [row_to_dict(row) for row in trend_rows],
    }


if __name__ == "__main__":
    import uvicorn

    run_startup_checks()
    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8200")),
        reload=ENVIRONMENT != "production",
    )
