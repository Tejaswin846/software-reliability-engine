from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt

try:
    from composio import Composio
    from composio.exceptions import (
        ComposioClientError,
        ComposioError,
        ComposioSDKTimeoutError,
    )
    from composio_openai_agents import OpenAIAgentsProvider
except ImportError:  # pragma: no cover
    Composio = None  # type: ignore[assignment]
    OpenAIAgentsProvider = None  # type: ignore[assignment]

    class ComposioError(Exception):
        pass

    class ComposioClientError(ComposioError):
        pass

    class ComposioSDKTimeoutError(ComposioError, TimeoutError):
        pass

try:
    from ..sentry_monitoring import capture_operational_error, redact_text
except ImportError:
    from sentry_monitoring import capture_operational_error, redact_text

from .models import APPS, APP_BY_TOOLKIT, AppDefinition, app_for_tool, get_app
from .storage import (
    complete_pending_action,
    create_pending_action,
    encryption_is_production_configured,
    get_connection,
    get_pending_action,
    init_storage,
    save_connection,
)


LOGGER = logging.getLogger("software.integrations")
SUPPORTED_TOOLKITS = tuple(dict.fromkeys(app.toolkit_slug for app in APPS))
SESSION_TOOLKITS = tuple(
    toolkit
    for toolkit in SUPPORTED_TOOLKITS
    if toolkit not in {"postgresql", "webhook"}
)


@dataclass
class UserSession:
    session: Any
    tools: List[Any]
    created_at: str


_client: Optional[Any] = None
_client_error: Optional[str] = None
_sessions: Dict[str, UserSession] = {}
_lock = threading.RLock()
composio: Optional[Any] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _api_key() -> str:
    return os.getenv("COMPOSIO_API_KEY", "").strip()


def _state_secret() -> str:
    return (
        os.getenv("INTEGRATION_STATE_SECRET", "").strip()
        or os.getenv("SOFTWARE_JWT_SECRET", "").strip()
        or os.getenv("JWT_SECRET", "").strip()
        or "software-local-integration-state-secret"
    )


def composio_is_configured() -> bool:
    return bool(_api_key() and Composio is not None and OpenAIAgentsProvider is not None)


def initialize_composio() -> Optional[Any]:
    global _client, _client_error, composio
    init_storage()
    if not composio_is_configured():
        _client_error = None if not _api_key() else "Connected Apps packages are unavailable."
        return None
    with _lock:
        if _client is not None:
            return _client
        try:
            _client = Composio(provider=OpenAIAgentsProvider())
            composio = _client
            _client_error = None
            LOGGER.info("Connected Apps service initialized.")
        except Exception as error:
            _client = None
            composio = None
            _client_error = _public_error(error)
            LOGGER.error("Connected Apps initialization failed: %s", _client_error)
            capture_operational_error(
                error,
                category="connected_apps_initialization_failure",
                provider="composio",
                operation="initialize",
            )
    return _client


def _normalize_user_id(user_id: str) -> str:
    normalized = str(user_id).strip()
    if not normalized:
        raise ValueError("user_id is required.")
    return normalized


def _public_error(error: BaseException | str) -> str:
    message = redact_text(str(error))
    replacements = {
        "Composio": "Connected Apps",
        "composio": "connected apps",
        "toolkit": "app",
        "Toolkit": "App",
    }
    for source, target in replacements.items():
        message = message.replace(source, target)
    return message[:500]


def _create_user_session(user_id: str) -> UserSession:
    global _client_error
    client = initialize_composio()
    if client is None:
        raise RuntimeError(_client_error or "Connected Apps is unavailable.")
    session = client.create(
        user_id=user_id,
        toolkits=list(SESSION_TOOLKITS),
        manage_connections={"enable": True},
    )
    tools = list(session.tools())
    state = UserSession(session=session, tools=tools, created_at=_now_iso())
    _client_error = None
    LOGGER.info("Created Connected Apps session for user %s.", user_id)
    return state


def _get_user_session(user_id: str) -> UserSession:
    normalized = _normalize_user_id(user_id)
    with _lock:
        state = _sessions.get(normalized)
        if state is None:
            state = _create_user_session(normalized)
            _sessions[normalized] = state
        return state


def get_user_tools(user_id: str) -> List[Any]:
    normalized = _normalize_user_id(user_id)
    if not composio_is_configured():
        return []
    try:
        return list(_get_user_session(normalized).tools)
    except Exception as error:
        global _client_error
        _client_error = _public_error(error)
        LOGGER.error("Could not load app tools for user %s: %s", normalized, _client_error)
        capture_operational_error(
            error,
            category="connected_apps_tool_discovery_failure",
            user_id=normalized,
            provider="composio",
            operation="get_user_tools",
        )
        return []


def attach_user_tools(user_id: str, existing_tools: Optional[List[Any]] = None) -> List[Any]:
    return [*(existing_tools or []), *get_user_tools(user_id)]


def refresh_tools(user_id: str) -> List[Any]:
    normalized = _normalize_user_id(user_id)
    with _lock:
        _sessions.pop(normalized, None)
    return get_user_tools(normalized)


def tool_descriptors(tools: List[Any]) -> List[Dict[str, Any]]:
    descriptors: List[Dict[str, Any]] = []
    for tool in tools:
        name = str(getattr(tool, "name", "") or "").strip()
        if name:
            descriptors.append(
                {
                    "name": name,
                    "description": str(getattr(tool, "description", "") or ""),
                    "parameters": getattr(tool, "params_json_schema", None) or {},
                }
            )
    return descriptors


def _safe_account(item: Any) -> Dict[str, Any]:
    toolkit = getattr(item, "toolkit", None)
    auth_config = getattr(item, "auth_config", None)
    return {
        "id": str(getattr(item, "id", "") or ""),
        "user_id": str(getattr(item, "user_id", "") or ""),
        "toolkit_slug": str(getattr(toolkit, "slug", "") or "").lower(),
        "status": str(getattr(item, "status", "") or "").upper(),
        "status_reason": _public_error(getattr(item, "status_reason", "") or ""),
        "updated_at": str(getattr(item, "updated_at", "") or ""),
        "created_at": str(getattr(item, "created_at", "") or ""),
        "auth_scheme": str(getattr(auth_config, "auth_scheme", "") or ""),
        "requested_scopes": list(getattr(item, "requested_scopes", None) or []),
        "requested_user_scopes": list(
            getattr(item, "requested_user_scopes", None) or []
        ),
    }


def _list_accounts(user_id: str) -> List[Dict[str, Any]]:
    client = initialize_composio()
    if client is None:
        return []
    response = client.connected_accounts.list(
        user_ids=[user_id],
        toolkit_slugs=list(SUPPORTED_TOOLKITS),
        account_type="PRIVATE",
        limit=100,
        order_by="updated_at",
        order_direction="desc",
    )
    accounts = [_safe_account(item) for item in getattr(response, "items", []) or []]
    return [account for account in accounts if account["user_id"] == user_id]


def _health_for_status(status: str) -> str:
    return {
        "ACTIVE": "Healthy",
        "INITIATED": "Waiting for authorization",
        "INITIALIZING": "Connecting",
        "INACTIVE": "Disconnected",
        "FAILED": "Needs attention",
        "EXPIRED": "Reconnect required",
        "REVOKED": "Disconnected",
    }.get(status, "Not connected")


def _connection_for_app(
    user_id: str,
    app: AppDefinition,
    accounts: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    matching = [
        account
        for account in (accounts if accounts is not None else _list_accounts(user_id))
        if account["toolkit_slug"] == app.toolkit_slug
    ]
    return matching[0] if matching else None


def _app_status(
    user_id: str,
    app: AppDefinition,
    account: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    local = get_connection(user_id, app.id)
    status = account["status"] if account else str((local or {}).get("status") or "NOT_CONNECTED")
    connected = status == "ACTIVE"
    permissions = (
        account["requested_user_scopes"] or account["requested_scopes"]
        if account
        else []
    )
    if not permissions:
        permissions = list(app.permissions) if connected else []
    last_sync = (
        account.get("updated_at")
        if account
        else (local or {}).get("last_sync_at")
    )
    metadata = {
        "connected_account_id": account.get("id") if account else None,
        "permissions": permissions,
        "auth_scheme": account.get("auth_scheme") if account else app.auth_type,
        "status_reason": account.get("status_reason") if account else None,
    }
    save_connection(
        user_id,
        app.id,
        app.toolkit_slug,
        status=status,
        health=_health_for_status(status),
        metadata=metadata,
        last_sync_at=last_sync,
    )
    return {
        **app.public_dict(),
        "connected": connected,
        "status": status,
        "health": _health_for_status(status),
        "last_sync_at": last_sync,
        "permissions_granted": permissions,
        "permission_status": "Granted" if connected else "Not granted",
        "can_retry": status in {"FAILED", "EXPIRED", "INACTIVE"},
    }


def list_integrations(user_id: str) -> Dict[str, Any]:
    normalized = _normalize_user_id(user_id)
    accounts: List[Dict[str, Any]] = []
    error: Optional[str] = None
    if composio_is_configured():
        try:
            accounts = _list_accounts(normalized)
        except Exception as provider_error:
            error = _public_error(provider_error)
            LOGGER.error("Could not refresh app status for user %s: %s", normalized, error)
            capture_operational_error(
                provider_error,
                category="connected_apps_status_failure",
                user_id=normalized,
                provider="composio",
                operation="list_connections",
            )
    apps = [
        _app_status(normalized, app, _connection_for_app(normalized, app, accounts))
        for app in APPS
    ]
    return {
        "configured": composio_is_configured(),
        "apps": apps,
        "connected_count": sum(1 for app in apps if app["connected"]),
        "total_count": len(apps),
        "last_checked_at": _now_iso(),
        "error": error,
    }


def create_connection_state(
    user_id: str,
    app_id: str,
    *,
    return_to: str,
    pending_action_id: Optional[str] = None,
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user_id,
            "app_id": app_id,
            "return_to": return_to,
            "pending_action_id": pending_action_id,
            "iat": now,
            "exp": now + timedelta(minutes=20),
            "type": "integration_connection",
        },
        _state_secret(),
        algorithm="HS256",
    )


def decode_connection_state(token: str) -> Dict[str, Any]:
    payload = jwt.decode(token, _state_secret(), algorithms=["HS256"])
    if payload.get("type") != "integration_connection":
        raise ValueError("Invalid connection state.")
    return payload


def begin_connection(
    user_id: str,
    app_id: str,
    *,
    callback_url: str,
    retry: bool = False,
) -> Dict[str, Any]:
    normalized = _normalize_user_id(user_id)
    app = get_app(app_id)
    if app is None:
        return {"ok": False, "error": "Unknown app."}
    if not composio_is_configured():
        return {"ok": False, "error": "App connections are not configured."}

    try:
        existing = _connection_for_app(normalized, app)
        if retry and existing and existing["id"]:
            response = initialize_composio().connected_accounts.refresh(
                existing["id"],
                query_redirect_url=callback_url,
                body_redirect_url=callback_url,
                validate_credentials=True,
            )
            redirect_url = getattr(response, "redirect_url", None)
            status = str(getattr(response, "status", "") or "INITIATED").upper()
            account_id = str(getattr(response, "id", "") or existing["id"])
        else:
            request = _get_user_session(normalized).session.authorize(
                app.toolkit_slug,
                callback_url=callback_url,
            )
            redirect_url = request.redirect_url
            status = str(request.status or "INITIATED").upper()
            account_id = str(request.id)

        save_connection(
            normalized,
            app.id,
            app.toolkit_slug,
            status=status,
            health=_health_for_status(status),
            metadata={
                "connected_account_id": account_id,
                "permissions": [],
                "auth_type": app.auth_type,
            },
            last_sync_at=_now_iso(),
        )
        return {
            "ok": True,
            "app": app.public_dict(),
            "status": status,
            "redirect_url": redirect_url,
        }
    except Exception as error:
        message = _public_error(error)
        LOGGER.error("Could not connect %s for user %s: %s", app.name, normalized, message)
        capture_operational_error(
            error,
            category="connected_apps_authentication_failure",
            user_id=normalized,
            provider="composio",
            operation="connect",
        )
        return {
            "ok": False,
            "app": app.public_dict(),
            "error": f"{app.name} could not be connected. {message}",
        }


def disconnect_app(user_id: str, app_id: str) -> Dict[str, Any]:
    normalized = _normalize_user_id(user_id)
    app = get_app(app_id)
    if app is None:
        return {"ok": False, "error": "Unknown app."}
    try:
        accounts = [
            account
            for account in _list_accounts(normalized)
            if account["toolkit_slug"] == app.toolkit_slug
        ]
        client = initialize_composio()
        for account in accounts:
            try:
                client.connected_accounts.delete(account["id"], revoke_on_delete=True)
            except Exception:
                client.connected_accounts.delete(account["id"])
        save_connection(
            normalized,
            app.id,
            app.toolkit_slug,
            status="REVOKED",
            health="Disconnected",
            metadata={"permissions": []},
            last_sync_at=_now_iso(),
        )
        refresh_tools(normalized)
        return {"ok": True, "app_id": app.id, "status": "REVOKED"}
    except Exception as error:
        message = _public_error(error)
        LOGGER.error("Could not disconnect %s for user %s: %s", app.name, normalized, message)
        capture_operational_error(
            error,
            category="connected_apps_disconnect_failure",
            user_id=normalized,
            provider="composio",
            operation="disconnect",
        )
        return {"ok": False, "error": f"{app.name} could not be disconnected. {message}"}


def is_app_connected(user_id: str, app_id: str) -> bool:
    app = get_app(app_id)
    if app is None or not composio_is_configured():
        return False
    try:
        account = _connection_for_app(_normalize_user_id(user_id), app)
        return bool(account and account["status"] == "ACTIVE")
    except Exception:
        return False


def _response_payload(response: Any) -> Dict[str, Any]:
    if hasattr(response, "model_dump"):
        payload = response.model_dump()
    elif isinstance(response, dict):
        payload = dict(response)
    else:
        payload = {
            "data": getattr(response, "data", None),
            "error": getattr(response, "error", None),
            "log_id": getattr(response, "log_id", None),
        }
    error = payload.get("error")
    return {
        "ok": not bool(error),
        "data": payload.get("data"),
        "error": _public_error(error) if error else None,
        "log_id": payload.get("log_id"),
    }


def execute_tool(
    user_id: str,
    tool_slug: str,
    arguments: Optional[Dict[str, Any]] = None,
    *,
    account: Optional[str] = None,
    workflow_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    chat_id: Optional[str] = None,
    return_to: str = "/apps",
    skip_connection_check: bool = False,
) -> Dict[str, Any]:
    normalized = _normalize_user_id(user_id)
    normalized_slug = str(tool_slug).strip().upper()
    app = app_for_tool(normalized_slug)
    if app and not skip_connection_check and not is_app_connected(normalized, app.id):
        action_id = create_pending_action(
            normalized,
            app.id,
            {
                "workflow_id": workflow_id,
                "tool_slug": normalized_slug,
                "arguments": arguments or {},
                "account": account,
                "agent_name": agent_name,
                "chat_id": chat_id,
            },
            return_to,
        )
        return {
            "ok": False,
            "connection_required": True,
            "app": app.public_dict(),
            "pending_action_id": action_id,
            "message": f"This action requires {app.name}. Connect {app.name}?",
            "data": None,
            "error": None,
            "log_id": None,
        }
    if not normalized_slug:
        return {"ok": False, "data": None, "error": "Tool name is required.", "log_id": None}
    if not composio_is_configured():
        return {"ok": False, "data": None, "error": "App connections are unavailable.", "log_id": None}

    try:
        response = _get_user_session(normalized).session.execute(
            normalized_slug,
            arguments=arguments or {},
            account=account,
        )
        result = _response_payload(response)
        if not result["ok"]:
            capture_operational_error(
                result["error"] or f"App action {normalized_slug} failed.",
                category="connected_app_action_failure",
                user_id=normalized,
                workflow_id=workflow_id,
                agent_name=agent_name,
                provider="composio",
                operation="execute_tool",
                tool_name=normalized_slug,
            )
        return result
    except ComposioSDKTimeoutError as error:
        category = "connected_app_timeout"
    except (ComposioClientError, ComposioError) as error:
        category = "connected_app_api_failure"
    except Exception as error:
        category = "connected_app_action_failure"

    message = _public_error(error)
    capture_operational_error(
        error,
        category=category,
        user_id=normalized,
        workflow_id=workflow_id,
        agent_name=agent_name,
        provider="composio",
        operation="execute_tool",
        tool_name=normalized_slug,
    )
    return {"ok": False, "data": None, "error": message, "log_id": None}


def resume_pending_action(user_id: str, action_id: str) -> Dict[str, Any]:
    normalized = _normalize_user_id(user_id)
    pending = get_pending_action(normalized, action_id)
    if pending is None:
        return {"ok": False, "status": "not_found", "error": "Pending action not found."}
    if pending["status"] in {"completed", "failed"}:
        return {
            "ok": pending["status"] == "completed",
            "status": pending["status"],
            "result": pending["result"],
            "return_to": pending["return_to"],
        }
    expires_at = datetime.fromisoformat(pending["expires_at"])
    if expires_at < datetime.now(timezone.utc):
        complete_pending_action(
            normalized,
            action_id,
            status="expired",
            result={"ok": False, "error": "The pending action expired."},
        )
        return {"ok": False, "status": "expired", "error": "The pending action expired."}
    if not is_app_connected(normalized, pending["app_id"]):
        return {
            "ok": False,
            "status": "waiting_for_connection",
            "app_id": pending["app_id"],
            "return_to": pending["return_to"],
        }

    action = pending["action"]
    result = execute_tool(
        normalized,
        action.get("tool_slug", ""),
        action.get("arguments") or {},
        account=action.get("account"),
        workflow_id=action.get("workflow_id"),
        agent_name=action.get("agent_name"),
        chat_id=action.get("chat_id"),
        return_to=pending["return_to"],
        skip_connection_check=True,
    )
    status = "completed" if result.get("ok") else "failed"
    complete_pending_action(normalized, action_id, status=status, result=result)
    return {
        "ok": bool(result.get("ok")),
        "status": status,
        "result": result,
        "workflow_id": action.get("workflow_id"),
        "tool_slug": action.get("tool_slug"),
        "agent_name": action.get("agent_name"),
        "chat_id": action.get("chat_id"),
        "return_to": pending["return_to"],
    }


def get_pending_action_result(user_id: str, action_id: str) -> Dict[str, Any]:
    pending = get_pending_action(_normalize_user_id(user_id), action_id)
    if pending is None:
        return {"ok": False, "status": "not_found", "error": "Pending action not found."}
    return {
        "ok": pending["status"] == "completed",
        "status": pending["status"],
        "app_id": pending["app_id"],
        "result": pending["result"],
        "return_to": pending["return_to"],
    }


def get_user_tool_context(user_id: str) -> Dict[str, Any]:
    normalized = _normalize_user_id(user_id)
    tools = get_user_tools(normalized)
    catalog = list_integrations(normalized)
    connected_apps = [
        {"id": app["id"], "name": app["name"]}
        for app in catalog["apps"]
        if app["connected"]
    ]
    return {
        "configured": composio_is_configured(),
        "available": bool(_sessions.get(normalized)),
        "session_created_at": (
            _sessions[normalized].created_at if normalized in _sessions else None
        ),
        "connected_apps": connected_apps,
        "tools": tool_descriptors(tools),
        "agent_instruction": (
            "Use connected apps when they are relevant. If an app is not connected, "
            "return the native connection_required response so Software can ask the user."
        ),
    }


def composio_health_check() -> Dict[str, Any]:
    configured = composio_is_configured()
    initialized = bool(_client is not None)
    return {
        "ok": True,
        "configured": configured,
        "initialized": initialized,
        "available": bool(initialized and not _client_error),
        "degraded": bool(configured and (not initialized or _client_error)),
        "active_user_sessions": len(_sessions),
        "encrypted_metadata": True,
        "production_encryption_key": encryption_is_production_configured(),
        "error": _client_error,
    }


def reset_composio_state() -> None:
    global _client, _client_error, composio
    with _lock:
        _client = None
        _client_error = None
        composio = None
        _sessions.clear()
