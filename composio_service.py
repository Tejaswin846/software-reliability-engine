from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from composio import Composio
    from composio.exceptions import (
        ComposioClientError,
        ComposioError,
        ComposioSDKTimeoutError,
    )
    from composio_openai_agents import OpenAIAgentsProvider
except ImportError:  # pragma: no cover - dependency failures are reported by health checks
    Composio = None  # type: ignore[assignment]
    OpenAIAgentsProvider = None  # type: ignore[assignment]

    class ComposioError(Exception):
        pass

    class ComposioClientError(ComposioError):
        pass

    class ComposioSDKTimeoutError(ComposioError, TimeoutError):
        pass

try:
    from .sentry_monitoring import capture_operational_error, redact_text
except ImportError:
    from sentry_monitoring import capture_operational_error, redact_text


LOGGER = logging.getLogger("software.composio")

SUPPORTED_TOOLKITS = (
    "gmail",
    "googlecalendar",
    "googledrive",
    "github",
    "slack",
    "notion",
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

# Public alias retained for direct orchestration imports.
composio: Optional[Any] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _api_key() -> str:
    return os.getenv("COMPOSIO_API_KEY", "").strip()


def composio_is_configured() -> bool:
    return bool(_api_key() and Composio is not None and OpenAIAgentsProvider is not None)


def initialize_composio() -> Optional[Any]:
    global _client, _client_error, composio
    if not composio_is_configured():
        _client_error = None if not _api_key() else "Composio packages are not installed."
        return None
    with _lock:
        if _client is not None:
            return _client
        try:
            # Composio reads COMPOSIO_API_KEY from the process environment.
            _client = Composio(provider=OpenAIAgentsProvider())
            composio = _client
            _client_error = None
            LOGGER.info("Composio initialized with OpenAI Agents tool support.")
        except Exception as error:
            _client = None
            composio = None
            _client_error = redact_text(str(error))
            LOGGER.error("Composio initialization failed: %s", _client_error)
            capture_operational_error(
                error,
                category="composio_initialization_failure",
                provider="composio",
                operation="initialize",
            )
    return _client


def _normalize_user_id(user_id: str) -> str:
    normalized = str(user_id).strip()
    if not normalized:
        raise ValueError("user_id is required.")
    return normalized


def _create_user_session(user_id: str) -> UserSession:
    global _client_error
    client = initialize_composio()
    if client is None:
        raise RuntimeError(_client_error or "Composio is unavailable.")
    session = client.create(
        user_id=user_id,
        toolkits=list(SUPPORTED_TOOLKITS),
        manage_connections={"enable": True},
    )
    tools = list(session.tools())
    state = UserSession(
        session=session,
        tools=tools,
        created_at=_now_iso(),
    )
    LOGGER.info(
        "Created Composio session for user %s with %s agent tools.",
        user_id,
        len(tools),
    )
    _client_error = None
    return state


def _get_user_session(user_id: str) -> UserSession:
    normalized = _normalize_user_id(user_id)
    with _lock:
        existing = _sessions.get(normalized)
        if existing is not None:
            return existing
        state = _create_user_session(normalized)
        _sessions[normalized] = state
        return state


def get_user_tools(user_id: str) -> List[Any]:
    """Return native OpenAI Agents tools for the authenticated user."""
    normalized = _normalize_user_id(user_id)
    if not composio_is_configured():
        return []
    try:
        return list(_get_user_session(normalized).tools)
    except Exception as error:
        global _client_error
        _client_error = redact_text(str(error))
        LOGGER.error(
            "Could not load Composio tools for user %s: %s",
            normalized,
            redact_text(str(error)),
        )
        capture_operational_error(
            error,
            category="composio_tool_discovery_failure",
            user_id=normalized,
            provider="composio",
            operation="get_user_tools",
        )
        return []


def attach_user_tools(user_id: str, existing_tools: Optional[List[Any]] = None) -> List[Any]:
    """Add Composio tools to an existing agent tool list without replacing it."""
    return [*(existing_tools or []), *get_user_tools(user_id)]


def refresh_tools(user_id: str) -> List[Any]:
    """Recreate the user's session so newly connected applications are available."""
    normalized = _normalize_user_id(user_id)
    with _lock:
        _sessions.pop(normalized, None)
    return get_user_tools(normalized)


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
        "error": redact_text(str(error)) if error else None,
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
) -> Dict[str, Any]:
    normalized = _normalize_user_id(user_id)
    normalized_slug = str(tool_slug).strip().upper()
    if not normalized_slug:
        return {"ok": False, "data": None, "error": "tool_slug is required.", "log_id": None}
    if not composio_is_configured():
        return {
            "ok": False,
            "data": None,
            "error": "Composio is not configured.",
            "log_id": None,
        }
    try:
        response = _get_user_session(normalized).session.execute(
            normalized_slug,
            arguments=arguments or {},
            account=account,
        )
        result = _response_payload(response)
        if result["ok"]:
            LOGGER.info(
                "Executed Composio tool %s for user %s.",
                normalized_slug,
                normalized,
            )
        else:
            LOGGER.warning(
                "Composio tool %s failed for user %s: %s",
                normalized_slug,
                normalized,
                result["error"],
            )
            capture_operational_error(
                result["error"] or f"Composio tool {normalized_slug} failed.",
                category="composio_tool_failure",
                user_id=normalized,
                workflow_id=workflow_id,
                agent_name=agent_name,
                provider="composio",
                operation="execute_tool",
                tool_name=normalized_slug,
            )
        return result
    except ComposioSDKTimeoutError as error:
        category = "composio_timeout"
    except (ComposioClientError, ComposioError) as error:
        category = "composio_api_failure"
    except Exception as error:
        category = "composio_tool_failure"

    clean_error = redact_text(str(error))
    LOGGER.error(
        "Composio tool %s raised an error for user %s: %s",
        normalized_slug,
        normalized,
        clean_error,
    )
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
    return {
        "ok": False,
        "data": None,
        "error": clean_error,
        "log_id": None,
    }


def tool_descriptors(tools: List[Any]) -> List[Dict[str, Any]]:
    descriptors: List[Dict[str, Any]] = []
    for tool in tools:
        name = str(getattr(tool, "name", "") or "").strip()
        if not name:
            continue
        descriptors.append(
            {
                "name": name,
                "description": str(getattr(tool, "description", "") or ""),
                "parameters": getattr(tool, "params_json_schema", None) or {},
            }
        )
    return descriptors


def _connected_toolkits(session: Any) -> List[Dict[str, Any]]:
    try:
        states = session.toolkits(
            toolkits=list(SUPPORTED_TOOLKITS),
            is_connected=True,
            limit=len(SUPPORTED_TOOLKITS),
        )
    except Exception as error:
        LOGGER.warning(
            "Could not inspect Composio connected applications: %s",
            redact_text(str(error)),
        )
        return []

    connected: List[Dict[str, Any]] = []
    for item in getattr(states, "items", []) or []:
        connection = getattr(item, "connection", None)
        if getattr(item, "is_no_auth", False) or (
            connection is not None and getattr(connection, "is_active", False)
        ):
            connected.append(
                {
                    "slug": str(getattr(item, "slug", "")),
                    "name": str(getattr(item, "name", "")),
                }
            )
    return connected


def get_user_tool_context(user_id: str) -> Dict[str, Any]:
    normalized = _normalize_user_id(user_id)
    tools = get_user_tools(normalized)
    state = _sessions.get(normalized)
    return {
        "configured": composio_is_configured(),
        "available": bool(state),
        "session_created_at": state.created_at if state else None,
        "supported_toolkits": list(SUPPORTED_TOOLKITS),
        "connected_toolkits": _connected_toolkits(state.session) if state else [],
        "tools": tool_descriptors(tools),
    }


def composio_health_check() -> Dict[str, Any]:
    configured = composio_is_configured()
    initialized = bool(_client is not None)
    degraded = bool(configured and (not initialized or _client_error))
    return {
        "ok": True,
        "configured": configured,
        "initialized": initialized,
        "available": bool(initialized and not _client_error),
        "degraded": degraded,
        "active_user_sessions": len(_sessions),
        "supported_toolkits": list(SUPPORTED_TOOLKITS),
        "error": _client_error,
    }


def reset_composio_state() -> None:
    global _client, _client_error, composio
    with _lock:
        _client = None
        composio = None
        _client_error = None
        _sessions.clear()
