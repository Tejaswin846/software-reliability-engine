from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from supabase import Client, create_client
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
    Client = Any  # type: ignore[misc,assignment]
    create_client = None


_CLIENT: Optional[Client] = None
_CLIENT_CONFIG: Optional[tuple[str, str]] = None
_CLIENT_LOCK = threading.Lock()
_LAST_ERROR: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _credentials() -> tuple[str, str]:
    return (
        os.getenv("SUPABASE_URL", "").strip(),
        os.getenv("SUPABASE_ANON_KEY", "").strip(),
    )


def supabase_is_configured() -> bool:
    url, anon_key = _credentials()
    return bool(url and anon_key and create_client is not None)


def _new_client() -> Optional[Client]:
    url, anon_key = _credentials()
    if not url or not anon_key or create_client is None:
        return None
    return create_client(url, anon_key)


def _auth_user_payload(user: Any) -> Optional[Dict[str, Any]]:
    if user is None:
        return None
    return {
        "id": str(getattr(user, "id", "")),
        "email": getattr(user, "email", None),
        "created_at": str(getattr(user, "created_at", "") or ""),
        "metadata": getattr(user, "user_metadata", None) or {},
    }


def _auth_session_payload(session: Any) -> Optional[Dict[str, Any]]:
    if session is None:
        return None
    return {
        "access_token": getattr(session, "access_token", None),
        "refresh_token": getattr(session, "refresh_token", None),
        "expires_at": getattr(session, "expires_at", None),
        "expires_in": getattr(session, "expires_in", None),
        "token_type": getattr(session, "token_type", "bearer"),
    }


def _failure(operation: str, error: str, *, available: bool = False) -> Dict[str, Any]:
    global _LAST_ERROR
    _LAST_ERROR = error
    return {
        "ok": False,
        "available": available,
        "operation": operation,
        "error": error,
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


def get_supabase_client() -> Optional[Client]:
    global _CLIENT, _CLIENT_CONFIG, _LAST_ERROR
    url, anon_key = _credentials()
    if not url or not anon_key:
        _LAST_ERROR = "SUPABASE_URL and SUPABASE_ANON_KEY are required."
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
            _LAST_ERROR = f"Could not create Supabase client: {error}"
    return _CLIENT


def supabase_health_check() -> Dict[str, Any]:
    url, anon_key = _credentials()
    if not url or not anon_key:
        return {
            "ok": False,
            "available": False,
            "configured": False,
            "url": url or None,
            "error": "SUPABASE_URL and SUPABASE_ANON_KEY are required.",
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
        return {
            "ok": False,
            "available": False,
            "configured": True,
            "url": url,
            "error": f"Supabase health check failed: {error}",
        }
    return {
        "ok": True,
        "available": True,
        "configured": True,
        "url": url,
        "error": None,
    }


def auth_sign_up(
    *,
    email: str,
    password: str,
    email_redirect_to: Optional[str] = None,
) -> Dict[str, Any]:
    client = _new_client()
    if client is None:
        return _failure("auth_sign_up", "Supabase Authentication is not configured.")
    credentials: Dict[str, Any] = {"email": email, "password": password}
    if email_redirect_to:
        credentials["options"] = {"email_redirect_to": email_redirect_to}
    try:
        response = client.auth.sign_up(credentials)
        return _success(
            "auth_sign_up",
            {
                "user": _auth_user_payload(response.user),
                "session": _auth_session_payload(response.session),
            },
        )
    except Exception as error:
        return _failure("auth_sign_up", f"Could not create account: {error}", available=True)


def auth_sign_in(*, email: str, password: str) -> Dict[str, Any]:
    client = _new_client()
    if client is None:
        return _failure("auth_sign_in", "Supabase Authentication is not configured.")
    try:
        response = client.auth.sign_in_with_password({"email": email, "password": password})
        return _success(
            "auth_sign_in",
            {
                "user": _auth_user_payload(response.user),
                "session": _auth_session_payload(response.session),
            },
        )
    except Exception as error:
        return _failure("auth_sign_in", f"Could not sign in: {error}", available=True)


def auth_get_user(access_token: str) -> Dict[str, Any]:
    client = _new_client()
    if client is None:
        return _failure("auth_get_user", "Supabase Authentication is not configured.")
    try:
        response = client.auth.get_user(access_token)
        return _success("auth_get_user", _auth_user_payload(response.user))
    except Exception as error:
        return _failure("auth_get_user", f"Invalid Supabase session: {error}", available=True)


def auth_request_password_reset(*, email: str, redirect_to: str) -> Dict[str, Any]:
    client = _new_client()
    if client is None:
        return _failure(
            "auth_request_password_reset",
            "Supabase Authentication is not configured.",
        )
    try:
        client.auth.reset_password_email(email, {"redirect_to": redirect_to})
        return _success("auth_request_password_reset", {"email": email})
    except Exception as error:
        return _failure(
            "auth_request_password_reset",
            f"Could not send password reset email: {error}",
            available=True,
        )


def auth_update_password(
    *,
    access_token: str,
    refresh_token: str,
    password: str,
) -> Dict[str, Any]:
    client = _new_client()
    if client is None:
        return _failure("auth_update_password", "Supabase Authentication is not configured.")
    try:
        client.auth.set_session(access_token, refresh_token)
        response = client.auth.update_user({"password": password})
        return _success("auth_update_password", _auth_user_payload(response.user))
    except Exception as error:
        return _failure(
            "auth_update_password",
            f"Could not update password: {error}",
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
