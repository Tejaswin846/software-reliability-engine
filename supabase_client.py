from __future__ import annotations

import os
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from supabase import Client, create_client
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
    Client = Any  # type: ignore[misc,assignment]
    create_client = None

try:
    from .sentry_monitoring import capture_operational_error, redact_text
except ImportError:
    from sentry_monitoring import capture_operational_error, redact_text


_CLIENT: Optional[Client] = None
_CLIENT_CONFIG: Optional[tuple[str, str]] = None
_CLIENT_LOCK = threading.Lock()
_LAST_ERROR: Optional[str] = None
LOGGER = logging.getLogger("software.supabase")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _credentials() -> tuple[str, str]:
    return (
        os.getenv("SUPABASE_URL", "").strip(),
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
    )


def supabase_is_configured() -> bool:
    url, anon_key = _credentials()
    return bool(url and anon_key and create_client is not None)


def _new_client() -> Optional[Client]:
    url, anon_key = _credentials()
    if not url or not anon_key or create_client is None:
        return None
    return create_client(url, anon_key)


def _failure(operation: str, error: str, *, available: bool = False) -> Dict[str, Any]:
    global _LAST_ERROR
    clean_error = redact_text(error)
    _LAST_ERROR = clean_error
    return {
        "ok": False,
        "available": available,
        "operation": operation,
        "error": clean_error,
        "data": None,
    }


def _success(operation: str, data: Any) -> Dict[str, Any]:
    global _LAST_ERROR
    _LAST_ERROR = None
    return {
        "ok": True,
        "available": True,
        "operation": operation,
        "error": None,
        "data": data,
    }


def _report_provider_failure(
    operation: str,
    error: BaseException,
    *,
    level: str = "error",
) -> None:
    LOGGER.log(
        logging.ERROR if level == "error" else logging.WARNING,
        "Supabase operation %s failed: %s",
        operation,
        redact_text(str(error)),
    )
    capture_operational_error(
        error,
        category="external_http_or_provider_failure",
        level=level,
        provider="supabase",
        operation=operation,
    )


def get_supabase_client() -> Optional[Client]:
    global _CLIENT, _CLIENT_CONFIG, _LAST_ERROR
    url, anon_key = _credentials()
    if not url or not anon_key:
        _LAST_ERROR = "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required."
        return None
    if create_client is None:
        _LAST_ERROR = "The supabase Python package is not installed."
        return None
    config = (url, anon_key)
    with _CLIENT_LOCK:
        if _CLIENT is not None and _CLIENT_CONFIG == config:
            return _CLIENT
        try:
            _CLIENT = create_client(url, anon_key)
            _CLIENT_CONFIG = config
            _LAST_ERROR = None
        except Exception as error:
            _CLIENT = None
            _CLIENT_CONFIG = None
            _LAST_ERROR = redact_text(f"Could not create Supabase client: {error}")
            _report_provider_failure("create_client", error)
    return _CLIENT


def supabase_health_check() -> Dict[str, Any]:
    url, anon_key = _credentials()
    if not url or not anon_key:
        return {
            "ok": False,
            "available": False,
            "configured": False,
            "url": url or None,
            "error": "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.",
        }
    client = get_supabase_client()
    if client is None:
        return {
            "ok": False,
            "available": False,
            "configured": True,
            "url": url,
            "error": _LAST_ERROR or "Supabase client is unavailable.",
        }
    try:
        client.table("chats").select("id").limit(1).execute()
    except Exception as error:
        _report_provider_failure("health_check", error, level="warning")
        return {
            "ok": False,
            "available": False,
            "configured": True,
            "url": url,
            "error": redact_text(f"Supabase health check failed: {error}"),
        }
    return {
        "ok": True,
        "available": True,
        "configured": True,
        "url": url,
        "error": None,
    }


def upsert_user_profile(
    *,
    user_id: str,
    email: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client = get_supabase_client()
    if client is None:
        return _failure("upsert_user_profile", _LAST_ERROR or "Supabase is unavailable.")
    timestamp = _now_iso()
    payload = {
        "id": user_id,
        "clerk_user_id": user_id,
        "email": email,
        "updated_at": timestamp,
        "metadata": metadata or {},
    }
    try:
        response = (
            client.table("user_profiles")
            .upsert(payload, on_conflict="id")
            .execute()
        )
        data = response.data[0] if response.data else payload
        return _success("upsert_user_profile", data)
    except Exception as error:
        _report_provider_failure("upsert_user_profile", error, level="warning")
        return _failure(
            "upsert_user_profile",
            f"Could not upsert user profile: {error}",
            available=True,
        )


def create_chat(
    *,
    user_id: str,
    title: str = "New chat",
    project_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    chat_id: Optional[str] = None,
) -> Dict[str, Any]:
    client = get_supabase_client()
    if client is None:
        return _failure("create_chat", _LAST_ERROR or "Supabase is unavailable.")
    timestamp = _now_iso()
    payload = {
        "id": chat_id or f"chat_{uuid.uuid4().hex}",
        "user_id": user_id,
        "project_id": project_id,
        "title": title.strip() or "New chat",
        "created_at": timestamp,
        "updated_at": timestamp,
        "metadata": metadata or {},
    }
    try:
        response = client.table("chats").insert(payload).execute()
        data = response.data[0] if response.data else payload
        return _success("create_chat", data)
    except Exception as error:
        _report_provider_failure("create_chat", error)
        return _failure("create_chat", f"Could not create chat: {error}", available=True)


def save_message(
    *,
    chat_id: str,
    user_id: str,
    role: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
    message_id: Optional[str] = None,
) -> Dict[str, Any]:
    client = get_supabase_client()
    if client is None:
        return _failure("save_message", _LAST_ERROR or "Supabase is unavailable.")
    payload = {
        "id": message_id or f"msg_{uuid.uuid4().hex}",
        "chat_id": chat_id,
        "user_id": user_id,
        "role": role,
        "content": content,
        "created_at": _now_iso(),
        "metadata": metadata or {},
    }
    try:
        response = client.table("messages").insert(payload).execute()
        data = response.data[0] if response.data else payload
        client.table("chats").update({"updated_at": payload["created_at"]}).eq(
            "id", chat_id
        ).eq("user_id", user_id).execute()
        return _success("save_message", data)
    except Exception as error:
        _report_provider_failure("save_message", error)
        return _failure("save_message", f"Could not save message: {error}", available=True)


def get_chat_history(*, chat_id: str, user_id: str) -> Dict[str, Any]:
    client = get_supabase_client()
    if client is None:
        return _failure("get_chat_history", _LAST_ERROR or "Supabase is unavailable.")
    try:
        chat_response = (
            client.table("chats")
            .select("*")
            .eq("id", chat_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        chat = chat_response.data[0] if chat_response.data else None
        if chat is None:
            return _success("get_chat_history", {"chat": None, "messages": []})
        messages_response = (
            client.table("messages")
            .select("*")
            .eq("chat_id", chat_id)
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
        )
        return _success(
            "get_chat_history",
            {"chat": chat, "messages": messages_response.data or []},
        )
    except Exception as error:
        _report_provider_failure("get_chat_history", error)
        return _failure(
            "get_chat_history",
            f"Could not load chat history: {error}",
            available=True,
        )


def save_benchmark_run(run: Dict[str, Any]) -> Dict[str, Any]:
    client = get_supabase_client()
    if client is None:
        return _failure("save_benchmark_run", _LAST_ERROR or "Supabase is unavailable.")
    payload = {
        "run_id": run["run_id"],
        "user_id": run.get("user_id"),
        "model": run["model"],
        "provider_url": run.get("provider_url"),
        "environment": run.get("environment", "real_world"),
        "total_workflows": int(run.get("total_workflows", 0)),
        "successful": int(run.get("successful", 0)),
        "failed": int(run.get("failed", 0)),
        "success_rate": float(run.get("success_rate", 0.0)),
        "failure_rate": float(run.get("failure_rate", 0.0)),
        "reliability_score_v2": float(run.get("reliability_score_v2", 0.0)),
        "reliability_band_v2": run.get("reliability_band_v2"),
        "average_execution_time": float(run.get("average_execution_time", 0.0)),
        "average_confidence": float(run.get("average_confidence", 0.0)),
        "retries": int(run.get("retries", 0)),
        "rollbacks": int(run.get("rollbacks", 0)),
        "escalations": int(run.get("escalations", 0)),
        "stops": int(run.get("stops", 0)),
        "tool_reliability": float(run.get("tool_reliability", 0.0)),
        "timeout_rate": float(run.get("timeout_rate", 0.0)),
        "created_at": run.get("created_at") or _now_iso(),
        "metadata": run.get("metadata") or {},
        "workflow_results": run.get("workflow_results") or [],
    }
    try:
        response = (
            client.table("benchmark_runs")
            .upsert(payload, on_conflict="run_id")
            .execute()
        )
        data = response.data[0] if response.data else payload
        return _success("save_benchmark_run", data)
    except Exception as error:
        _report_provider_failure("save_benchmark_run", error)
        return _failure(
            "save_benchmark_run",
            f"Could not save benchmark run: {error}",
            available=True,
        )


def reset_supabase_client() -> None:
    global _CLIENT, _CLIENT_CONFIG, _LAST_ERROR
    with _CLIENT_LOCK:
        _CLIENT = None
        _CLIENT_CONFIG = None
        _LAST_ERROR = None
