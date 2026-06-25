from __future__ import annotations

import logging
import os
import re
import inspect
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration


LOGGER = logging.getLogger("software.monitoring")

SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "dsn",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "session",
    "token",
)
SAFE_CONTEXT_KEYS = {
    "agent_name",
    "category",
    "chat_id",
    "failure_type",
    "model",
    "operation",
    "project_id",
    "provider",
    "request_id",
    "stage_name",
    "tool_name",
    "user_id",
    "workflow_id",
}
TOKEN_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(
        r"(?i)\b(api[-_ ]?key|authorization|password|secret|token|dsn)"
        r"(\s*[=:]\s*)([^\s,;]+)"
    ),
    re.compile(
        r"(?i)([?&](?:api[-_]?key|access[-_]?token|auth|password|secret|token)=)"
        r"[^&#\s]+"
    ),
)

_INITIALIZED = False
_INITIALIZATION_ERROR: Optional[str] = None
_DEPLOYMENT_VERSION = ""

F = TypeVar("F", bound=Callable[..., Any])


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        LOGGER.warning("%s is invalid; using %.2f.", name, default)
        return default
    if not 0.0 <= value <= 1.0:
        LOGGER.warning("%s must be between 0 and 1; using %.2f.", name, default)
        return default
    return value


def _deployment_version() -> str:
    explicit_release = os.getenv("SENTRY_RELEASE", "").strip()
    if explicit_release:
        return explicit_release
    app_version = os.getenv("SOFTWARE_VERSION", "0.2.0").strip()
    commit = (
        os.getenv("RENDER_GIT_COMMIT", "").strip()
        or os.getenv("GIT_COMMIT", "").strip()
    )
    return f"software@{app_version}+{commit[:12]}" if commit else f"software@{app_version}"


def _secret_values() -> list[str]:
    values: list[str] = []
    for key, value in os.environ.items():
        normalized_key = key.lower()
        if not any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
            continue
        clean_value = value.strip()
        if len(clean_value) >= 8:
            values.append(clean_value)
    return sorted(set(values), key=len, reverse=True)


def redact_text(value: str) -> str:
    redacted = value
    for secret in _secret_values():
        redacted = redacted.replace(secret, "[Filtered]")
    redacted = TOKEN_PATTERNS[0].sub("Bearer [Filtered]", redacted)
    redacted = TOKEN_PATTERNS[1].sub("[Filtered JWT]", redacted)
    redacted = TOKEN_PATTERNS[2].sub(
        lambda match: f"{match.group(1)}{match.group(2)}[Filtered]",
        redacted,
    )
    redacted = TOKEN_PATTERNS[3].sub(
        lambda match: f"{match.group(1)}[Filtered]",
        redacted,
    )
    return redacted


def scrub_sensitive_data(value: Any, key: Optional[str] = None) -> Any:
    normalized_key = (key or "").lower()
    if normalized_key and any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
        return "[Filtered]"
    if isinstance(value, dict):
        return {
            str(item_key): scrub_sensitive_data(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [scrub_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_sensitive_data(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def _before_send(event: Dict[str, Any], hint: Dict[str, Any]) -> Dict[str, Any]:
    return scrub_sensitive_data(event)


def _before_send_transaction(
    event: Dict[str, Any],
    hint: Dict[str, Any],
) -> Dict[str, Any]:
    return scrub_sensitive_data(event)


def _before_breadcrumb(
    breadcrumb: Dict[str, Any],
    hint: Dict[str, Any],
) -> Dict[str, Any]:
    return scrub_sensitive_data(breadcrumb)


def _before_send_log(log: Dict[str, Any], hint: Dict[str, Any]) -> Dict[str, Any]:
    return scrub_sensitive_data(log)


def initialize_sentry() -> Dict[str, Any]:
    global _DEPLOYMENT_VERSION, _INITIALIZED, _INITIALIZATION_ERROR
    dsn = os.getenv("SENTRY_DSN", "").strip()
    _DEPLOYMENT_VERSION = _deployment_version()
    if not dsn:
        _INITIALIZED = False
        _INITIALIZATION_ERROR = None
        LOGGER.info("Sentry monitoring is disabled because SENTRY_DSN is not set.")
        return sentry_health_check()
    if _INITIALIZED and sentry_sdk.get_client().is_active():
        return sentry_health_check()

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("SOFTWARE_ENV", "development")),
            release=_DEPLOYMENT_VERSION,
            traces_sample_rate=_env_float("SENTRY_TRACES_SAMPLE_RATE", 0.2),
            enable_logs=os.getenv("SENTRY_ENABLE_LOGS", "true").lower() == "true",
            send_default_pii=False,
            include_local_variables=False,
            max_request_body_size="never",
            attach_stacktrace=True,
            auto_enabling_integrations=False,
            integrations=[
                FastApiIntegration(transaction_style="url"),
                StarletteIntegration(transaction_style="url"),
                AsyncioIntegration(task_spans=True),
                HttpxIntegration(),
                LoggingIntegration(
                    level=logging.INFO,
                    event_level=logging.ERROR,
                    sentry_logs_level=logging.INFO,
                ),
            ],
            before_send=_before_send,
            before_send_transaction=_before_send_transaction,
            before_breadcrumb=_before_breadcrumb,
            before_send_log=_before_send_log,
        )
        _INITIALIZED = sentry_sdk.get_client().is_active()
        _INITIALIZATION_ERROR = None if _INITIALIZED else "Sentry client is inactive."
        if _INITIALIZED:
            sentry_sdk.set_tag("service", "software-reliability-engine")
            sentry_sdk.set_tag("deployment_version", _DEPLOYMENT_VERSION)
            LOGGER.info("Sentry monitoring initialized for %s.", _DEPLOYMENT_VERSION)
    except Exception as error:
        _INITIALIZED = False
        _INITIALIZATION_ERROR = redact_text(str(error))
        LOGGER.error(
            "Sentry monitoring initialization failed: %s",
            _INITIALIZATION_ERROR,
        )
    return sentry_health_check()


def sentry_health_check() -> Dict[str, Any]:
    configured = bool(os.getenv("SENTRY_DSN", "").strip())
    active = bool(_INITIALIZED and sentry_sdk.get_client().is_active())
    return {
        "ok": active if configured else True,
        "configured": configured,
        "initialized": active,
        "error_monitoring": active,
        "logging": active and os.getenv("SENTRY_ENABLE_LOGS", "true").lower() == "true",
        "performance_tracing": active,
        "traces_sample_rate": _env_float("SENTRY_TRACES_SAMPLE_RATE", 0.2),
        "deployment_version": _DEPLOYMENT_VERSION or _deployment_version(),
        "error": _INITIALIZATION_ERROR,
    }


def set_monitoring_context(
    *,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    **context: Any,
) -> None:
    if not sentry_sdk.get_client().is_active():
        return
    if user_id:
        sentry_sdk.set_user({"id": str(user_id)})
    for key, value in {
        "request_id": request_id,
        "workflow_id": workflow_id,
        "agent_name": agent_name,
    }.items():
        if value:
            sentry_sdk.set_tag(key, redact_text(str(value))[:200])
    safe_context = {
        key: scrub_sensitive_data(value, key)
        for key, value in context.items()
        if key in SAFE_CONTEXT_KEYS and value is not None
    }
    if safe_context:
        sentry_sdk.set_context("software", safe_context)


def capture_operational_error(
    error: BaseException | str,
    *,
    category: str,
    level: str = "error",
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    **context: Any,
) -> Optional[str]:
    if not sentry_sdk.get_client().is_active():
        return None
    with sentry_sdk.new_scope() as scope:
        scope.set_level(level)
        scope.set_tag("failure_category", category)
        if user_id:
            scope.set_user({"id": str(user_id)})
        for key, value in {
            "request_id": request_id,
            "workflow_id": workflow_id,
            "agent_name": agent_name,
        }.items():
            if value:
                scope.set_tag(key, redact_text(str(value))[:200])
        safe_context = {
            key: scrub_sensitive_data(value, key)
            for key, value in {"category": category, **context}.items()
            if key in SAFE_CONTEXT_KEYS and value is not None
        }
        if safe_context:
            scope.set_context("software_failure", safe_context)
        if isinstance(error, BaseException):
            return sentry_sdk.capture_exception(error)
        return sentry_sdk.capture_message(redact_text(error), level=level)


def monitor_background_task(
    *,
    task_name: Optional[str] = None,
    workflow_id: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> Callable[[F], F]:
    def decorator(function: F) -> F:
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await function(*args, **kwargs)
                except Exception as error:
                    capture_operational_error(
                        error,
                        category="background_task_failure",
                        workflow_id=workflow_id,
                        agent_name=agent_name,
                        operation=task_name or function.__name__,
                    )
                    raise

            return async_wrapper  # type: ignore[return-value]

        @wraps(function)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return function(*args, **kwargs)
            except Exception as error:
                capture_operational_error(
                    error,
                    category="background_task_failure",
                    workflow_id=workflow_id,
                    agent_name=agent_name,
                    operation=task_name or function.__name__,
                )
                raise

        return sync_wrapper  # type: ignore[return-value]

    return decorator
