from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

try:
    from supabase import Client, create_client
    from supabase.client import ClientOptions
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
    Client = Any  # type: ignore[misc,assignment]
    ClientOptions = None  # type: ignore[misc,assignment]
    create_client = None

try:
    from .sentry_monitoring import capture_operational_error, redact_text
except ImportError:
    from sentry_monitoring import capture_operational_error, redact_text


_CLIENT: Client | None = None
_CLIENT_CONFIG: tuple[str, str] | None = None
_CLIENTS: dict[tuple[str, str, float], Client] = {}
_ENDPOINT_STATE: dict[str, dict[str, float]] = {}
_CLIENT_LOCK = threading.Lock()
_LAST_ERROR: str | None = None
LOGGER = logging.getLogger("software.supabase")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _credentials() -> tuple[str, str]:
    return (
        os.getenv("SUPABASE_URL", "").strip(),
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
    )


def _timeout_seconds() -> float:
    try:
        configured = float(os.getenv("SOFTWARE_SUPABASE_TIMEOUT_SECONDS", "5"))
    except ValueError:
        configured = 5.0
    return max(1.0, min(30.0, configured))


def _endpoint_specs(*, read_only: bool) -> list[tuple[str, str, str]]:
    primary_url, service_key = _credentials()
    replica_key = os.getenv("SUPABASE_READ_REPLICA_KEY", "").strip() or service_key
    load_balancer_url = os.getenv("SUPABASE_LOAD_BALANCER_URL", "").strip()
    replica_url = os.getenv("SUPABASE_READ_REPLICA_URL", "").strip()
    candidates = [("load_balancer", load_balancer_url, service_key)]
    if read_only:
        candidates.append(("read_replica", replica_url, replica_key))
    candidates.append(("primary", primary_url, service_key))
    unique: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for label, url, key in candidates:
        normalized = url.rstrip("/")
        if not normalized or not key or normalized in seen:
            continue
        seen.add(normalized)
        unique.append((label, normalized, key))
    return unique


def _circuit_settings() -> tuple[int, float]:
    try:
        failure_limit = int(os.getenv("SOFTWARE_SUPABASE_CIRCUIT_FAILURES", "2"))
    except ValueError:
        failure_limit = 2
    try:
        cooldown = float(os.getenv("SOFTWARE_SUPABASE_CIRCUIT_COOLDOWN_SECONDS", "30"))
    except ValueError:
        cooldown = 30.0
    return max(1, min(10, failure_limit)), max(5.0, min(300.0, cooldown))


def _circuit_available(url: str) -> bool:
    state = _ENDPOINT_STATE.get(url) or {}
    return time.monotonic() >= float(state.get("open_until") or 0)


def _record_endpoint_result(url: str, *, success: bool) -> None:
    failure_limit, cooldown = _circuit_settings()
    with _CLIENT_LOCK:
        state = _ENDPOINT_STATE.setdefault(url, {"failures": 0.0, "open_until": 0.0})
        if success:
            state.update({"failures": 0.0, "open_until": 0.0})
            return
        failures = int(state.get("failures") or 0) + 1
        state["failures"] = float(failures)
        if failures >= failure_limit:
            state["open_until"] = time.monotonic() + cooldown


def supabase_is_configured() -> bool:
    return bool(_endpoint_specs(read_only=False) and create_client is not None)


def _new_client(url: str | None = None, key: str | None = None) -> Client | None:
    primary_url, service_key = _credentials()
    selected_url = (url or primary_url).rstrip("/")
    selected_key = key or service_key
    if not selected_url or not selected_key or create_client is None:
        return None
    timeout = _timeout_seconds()
    if ClientOptions is None:
        return create_client(selected_url, selected_key)
    return create_client(
        selected_url,
        selected_key,
        options=ClientOptions(
            postgrest_client_timeout=timeout,
            storage_client_timeout=max(1, int(timeout)),
            function_client_timeout=max(1, int(timeout)),
            schema="public",
        ),
    )


def _failure(
    operation: str,
    error: str,
    *,
    available: bool = False,
    attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    global _LAST_ERROR
    clean_error = redact_text(error)
    _LAST_ERROR = clean_error
    return {
        "ok": False,
        "available": available,
        "operation": operation,
        "error": clean_error,
        "data": None,
        "failover_attempts": attempts or [],
    }


def _success(
    operation: str,
    data: Any,
    *,
    routing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    global _LAST_ERROR
    _LAST_ERROR = None
    result = {
        "ok": True,
        "available": True,
        "operation": operation,
        "error": None,
        "data": data,
    }
    result.update(routing or {})
    return result


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


def _client_for(url: str, key: str) -> Client | None:
    global _LAST_ERROR
    timeout = _timeout_seconds()
    config = (url, key, timeout)
    with _CLIENT_LOCK:
        cached = _CLIENTS.get(config)
        if cached is not None:
            return cached
        try:
            client = _new_client(url, key)
        except Exception as error:
            _LAST_ERROR = redact_text(f"Could not create Supabase client: {error}")
            _report_provider_failure("create_client", error)
            return None
        if client is not None:
            _CLIENTS[config] = client
        return client


def get_supabase_client(*, read_only: bool = False) -> Client | None:
    global _CLIENT, _CLIENT_CONFIG, _LAST_ERROR
    specs = _endpoint_specs(read_only=read_only)
    if not specs:
        _LAST_ERROR = "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required."
        return None
    if create_client is None:
        _LAST_ERROR = "The supabase Python package is not installed."
        return None
    available = [spec for spec in specs if _circuit_available(spec[1])]
    candidates = available or specs[:1]
    for _, url, key in candidates:
        client = _client_for(url, key)
        if client is None:
            continue
        if not read_only:
            _CLIENT = client
            _CLIENT_CONFIG = (url, key)
        _LAST_ERROR = None
        return client
    _CLIENT = None
    _CLIENT_CONFIG = None
    return None


class _SupabaseUnavailable(RuntimeError):
    def __init__(self, message: str, attempts: list[dict[str, Any]]):
        super().__init__(message)
        self.attempts = attempts


def _execute_with_failover(
    operation: str,
    executor: Any,
    *,
    read_only: bool,
) -> tuple[Any, dict[str, Any]]:
    specs = _endpoint_specs(read_only=read_only)
    preferred = get_supabase_client(read_only=read_only)
    candidates: list[tuple[str, str, Client]] = []
    if preferred is not None:
        matched = next(
            (
                (label, url)
                for label, url, key in specs
                if _CLIENTS.get((url, key, _timeout_seconds())) is preferred
            ),
            ("configured", ""),
        )
        candidates.append((matched[0], matched[1], preferred))
    for label, url, key in specs:
        if not _circuit_available(url):
            continue
        client = _client_for(url, key)
        if client is not None and all(
            existing[2] is not client for existing in candidates
        ):
            candidates.append((label, url, client))
    if not candidates:
        raise _SupabaseUnavailable(
            _LAST_ERROR or "No configured Supabase endpoint is available.", []
        )
    attempts: list[dict[str, Any]] = []
    last_error = "Supabase operation failed."
    for label, url, client in candidates:
        started = time.perf_counter()
        try:
            result = executor(client)
        except Exception as error:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            last_error = redact_text(str(error)) or "Supabase operation failed."
            attempts.append(
                {
                    "endpoint": label,
                    "ok": False,
                    "latency_ms": latency_ms,
                    "error": last_error[:300],
                }
            )
            if url:
                _record_endpoint_result(url, success=False)
            _report_provider_failure(operation, error, level="warning")
            continue
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        if url:
            _record_endpoint_result(url, success=True)
        attempts.append(
            {"endpoint": label, "ok": True, "latency_ms": latency_ms, "error": None}
        )
        return result, {
            "selected_endpoint": label,
            "failover_used": len(attempts) > 1,
            "degraded": len(attempts) > 1,
            "failover_attempts": attempts,
        }
    raise _SupabaseUnavailable(last_error, attempts)


def supabase_health_check() -> dict[str, Any]:
    primary_url, service_key = _credentials()
    if not primary_url or not service_key:
        return {
            "ok": False,
            "available": False,
            "configured": False,
            "error": "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.",
            "redundancy": {
                "load_balancer": False,
                "read_replica": False,
                "endpoint_count": 0,
            },
        }
    specs = _endpoint_specs(read_only=True)
    redundancy = {
        "load_balancer": any(label == "load_balancer" for label, _, _ in specs),
        "read_replica": any(label == "read_replica" for label, _, _ in specs),
        "endpoint_count": len(specs),
    }
    try:
        _, routing = _execute_with_failover(
            "health_check",
            lambda client: client.table("chats").select("id").limit(1).execute(),
            read_only=True,
        )
    except _SupabaseUnavailable as error:
        return {
            "ok": False,
            "available": False,
            "configured": True,
            "error": "Supabase endpoints are currently unavailable.",
            "redundancy": redundancy,
            "failover_attempts": [
                {
                    "endpoint": item.get("endpoint"),
                    "ok": bool(item.get("ok")),
                    "latency_ms": item.get("latency_ms"),
                    "error_type": "request_failed" if not item.get("ok") else None,
                }
                for item in error.attempts
            ],
        }
    return {
        "ok": True,
        "available": True,
        "configured": True,
        "error": None,
        "redundancy": redundancy,
        **routing,
    }


def upsert_user_profile(
    *,
    user_id: str,
    email: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = _now_iso()
    payload = {
        "id": user_id,
        "clerk_user_id": user_id,
        "email": email,
        "updated_at": timestamp,
        "metadata": metadata or {},
    }
    try:
        response, routing = _execute_with_failover(
            "upsert_user_profile",
            lambda client: (
                client.table("user_profiles")
                .upsert(payload, on_conflict="id")
                .execute()
            ),
            read_only=False,
        )
        data = response.data[0] if response.data else payload
        return _success("upsert_user_profile", data, routing=routing)
    except _SupabaseUnavailable as error:
        return _failure(
            "upsert_user_profile",
            f"Could not upsert user profile: {error}",
            available=bool(error.attempts),
            attempts=error.attempts,
        )


def create_chat(
    *,
    user_id: str,
    title: str = "New chat",
    project_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    chat_id: str | None = None,
) -> dict[str, Any]:
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
        response, routing = _execute_with_failover(
            "create_chat",
            lambda client: (
                client.table("chats").upsert(payload, on_conflict="id").execute()
            ),
            read_only=False,
        )
        data = response.data[0] if response.data else payload
        return _success("create_chat", data, routing=routing)
    except _SupabaseUnavailable as error:
        return _failure(
            "create_chat",
            f"Could not create chat: {error}",
            available=bool(error.attempts),
            attempts=error.attempts,
        )


def save_message(
    *,
    chat_id: str,
    user_id: str,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    message_id: str | None = None,
) -> dict[str, Any]:
    payload = {
        "id": message_id or f"msg_{uuid.uuid4().hex}",
        "chat_id": chat_id,
        "user_id": user_id,
        "role": role,
        "content": content,
        "created_at": _now_iso(),
        "metadata": metadata or {},
    }

    def persist(client: Client) -> Any:
        response = client.table("messages").upsert(payload, on_conflict="id").execute()
        client.table("chats").update({"updated_at": payload["created_at"]}).eq(
            "id", chat_id
        ).eq("user_id", user_id).execute()
        return response

    try:
        response, routing = _execute_with_failover(
            "save_message", persist, read_only=False
        )
        data = response.data[0] if response.data else payload
        return _success("save_message", data, routing=routing)
    except _SupabaseUnavailable as error:
        return _failure(
            "save_message",
            f"Could not save message: {error}",
            available=bool(error.attempts),
            attempts=error.attempts,
        )


def get_chat_history(*, chat_id: str, user_id: str) -> dict[str, Any]:
    def load(client: Client) -> dict[str, Any]:
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
            return {"chat": None, "messages": []}
        messages_response = (
            client.table("messages")
            .select("*")
            .eq("chat_id", chat_id)
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
        )
        return {"chat": chat, "messages": messages_response.data or []}

    try:
        history, routing = _execute_with_failover(
            "get_chat_history", load, read_only=True
        )
        return _success("get_chat_history", history, routing=routing)
    except _SupabaseUnavailable as error:
        return _failure(
            "get_chat_history",
            f"Could not load chat history: {error}",
            available=bool(error.attempts),
            attempts=error.attempts,
        )


def save_benchmark_run(run: dict[str, Any]) -> dict[str, Any]:
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
        response, routing = _execute_with_failover(
            "save_benchmark_run",
            lambda client: (
                client.table("benchmark_runs")
                .upsert(payload, on_conflict="run_id")
                .execute()
            ),
            read_only=False,
        )
        data = response.data[0] if response.data else payload
        return _success("save_benchmark_run", data, routing=routing)
    except _SupabaseUnavailable as error:
        return _failure(
            "save_benchmark_run",
            f"Could not save benchmark run: {error}",
            available=bool(error.attempts),
            attempts=error.attempts,
        )


def reset_supabase_client() -> None:
    global _CLIENT, _CLIENT_CONFIG, _LAST_ERROR
    with _CLIENT_LOCK:
        _CLIENT = None
        _CLIENT_CONFIG = None
        _CLIENTS.clear()
        _ENDPOINT_STATE.clear()
        _LAST_ERROR = None
