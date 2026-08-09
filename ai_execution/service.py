from __future__ import annotations

import os
import re
import socket
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .control_plane import (
    ControlPlaneError,
    ExecutionCancelled,
    ExecutionLease,
    IdempotencyConflict,
    LeaseConflict,
    StaleFence,
    create_execution_control_plane,
)
from .risk_adaptive import evaluate_verification
from .storage import (
    append_audit_event,
    get_audit,
    get_request,
    get_workflow_risk_state,
    list_workflow_decisions,
    list_workflow_evidence,
    pending_semantic_audits,
    record_semantic_audit,
    record_verification_evaluation,
    save_request,
    verification_metrics,
)

INTENTS = {
    "answer_question",
    "summarize",
    "search_data",
    "create_workflow",
    "send_email",
    "create_calendar_event",
    "modify_database",
    "delete_data",
    "external_tool_action",
}

HIGH_RISK_INTENTS = {
    "send_email",
    "create_calendar_event",
    "modify_database",
    "delete_data",
    "external_tool_action",
}

SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)

SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"(?i)\b(api[-_ ]?key|password|secret|token)\s*[=:]\s*[^\s,;]+"),
)

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
DATE_PATTERN = re.compile(
    r"\b(?:20\d{2}-\d{2}-\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?\b"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def classify_intent(request_text: str, action: dict[str, Any] | None = None) -> str:
    text = request_text.lower()
    action = action or {}
    explicit = _normalized_text(action.get("intent")).lower()
    if explicit in INTENTS:
        return explicit
    if _contains_any(
        text,
        (
            "delete ",
            "remove permanently",
            "drop table",
            "truncate table",
            "erase ",
            "purge ",
        ),
    ):
        return "delete_data"
    if _contains_any(
        text,
        ("send email", "send an email", "email this", "email to", "mail this"),
    ):
        return "send_email"
    if _contains_any(
        text,
        (
            "schedule meeting",
            "create calendar",
            "calendar event",
            "book a meeting",
            "add to calendar",
        ),
    ):
        return "create_calendar_event"
    if _contains_any(
        text,
        (
            "update database",
            "modify database",
            "insert into",
            "update table",
            "alter table",
            "write to database",
        ),
    ):
        return "modify_database"
    if _contains_any(
        text,
        (
            "create workflow",
            "build workflow",
            "define workflow",
            "new workflow",
            "run workflow",
        ),
    ):
        return "create_workflow"
    if _contains_any(
        text,
        (
            "summarize",
            "summary",
            "condense",
            "shorten this",
        ),
    ):
        return "summarize"
    if _contains_any(
        text,
        (
            "search ",
            "find ",
            "look up",
            "query database",
            "search files",
            "retrieve ",
        ),
    ):
        return "search_data"
    if action.get("tool_slug") or action.get("app_id") or action.get("target_app"):
        return "external_tool_action"
    if _contains_any(
        text,
        (
            "publish ",
            "post to ",
            "create draft",
            "draft email",
            "call the tool",
            "run the tool",
        ),
    ):
        return "external_tool_action"
    return "answer_question"


def detect_risk_level(
    intent: str,
    request_text: str,
    action: dict[str, Any] | None = None,
) -> str:
    text = request_text.lower()
    action = action or {}
    if intent in HIGH_RISK_INTENTS:
        if intent == "external_tool_action" and _contains_any(
            text, ("create draft", "draft email")
        ):
            return "medium_risk"
        return "high_risk"
    if _contains_any(
        text,
        (
            "publish ",
            "production",
            "external system",
            "run workflow",
        ),
    ) or action.get("affects_external_systems"):
        return "high_risk"
    if intent in {"search_data", "create_workflow"} or _contains_any(
        text,
        (
            "search files",
            "query database",
            "generate report",
            "create report",
            "create draft",
        ),
    ):
        return "medium_risk"
    return "low_risk"


def _extract_recipient(request_text: str, action: dict[str, Any]) -> str | None:
    for key in ("recipient", "to", "email"):
        value = _normalized_text(action.get(key))
        if value:
            return value
    match = EMAIL_PATTERN.search(request_text)
    return match.group(0) if match else None


def _extract_date_time(request_text: str, action: dict[str, Any]) -> str | None:
    for key in ("date_time", "datetime", "start_time", "start", "date"):
        value = _normalized_text(action.get(key))
        if value:
            return value
    match = DATE_PATTERN.search(request_text)
    return match.group(0) if match else None


def _target_app(intent: str, request_text: str, action: dict[str, Any]) -> str | None:
    explicit = _normalized_text(
        action.get("app_id") or action.get("target_app")
    ).lower()
    if explicit:
        return explicit.replace("_", "-").replace(" ", "-")
    text = request_text.lower()
    if "outlook" in text:
        return "outlook"
    if intent == "send_email":
        return "gmail"
    if "microsoft teams" in text or "teams calendar" in text:
        return "microsoft-teams"
    if intent == "create_calendar_event":
        return "google-calendar"
    if "postgres" in text:
        return "postgresql"
    if "supabase" in text or intent in {"modify_database", "delete_data"}:
        return "supabase"
    return None


def _default_tool_slug(intent: str, target_app: str | None) -> str | None:
    if intent == "send_email":
        return "OUTLOOK_SEND_EMAIL" if target_app == "outlook" else "GMAIL_SEND_EMAIL"
    if intent == "create_calendar_event":
        return (
            "MICROSOFT_TEAMS_CREATE_MEETING"
            if target_app == "microsoft-teams"
            else "GOOGLECALENDAR_CREATE_EVENT"
        )
    return None


def create_plan(
    request_text: str,
    action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details = dict(action or {})
    intent = classify_intent(request_text, details)
    risk_level = detect_risk_level(intent, request_text, details)
    target_app = _target_app(intent, request_text, details)
    recipient = _extract_recipient(request_text, details)
    date_time = _extract_date_time(request_text, details)
    tool_slug = _normalized_text(
        details.get("tool_slug")
    ).upper() or _default_tool_slug(intent, target_app)
    arguments = dict(details.get("arguments") or {})
    if intent == "send_email":
        if recipient:
            arguments.setdefault("recipient_email", recipient)
            arguments.setdefault("to", recipient)
        if details.get("subject"):
            arguments.setdefault("subject", details["subject"])
        if details.get("body"):
            arguments.setdefault("body", details["body"])
    elif intent == "create_calendar_event" and date_time:
        arguments.setdefault("start_time", date_time)

    required_tools = [tool_slug] if tool_slug else []
    missing_info: list[str] = []
    if intent == "send_email" and not recipient:
        missing_info.append("recipient")
    if intent == "create_calendar_event" and not date_time:
        missing_info.append("date_time")
    if intent in {"modify_database", "delete_data", "external_tool_action"}:
        if not tool_slug:
            missing_info.append("tool_slug")
        if not target_app:
            missing_info.append("target_app")
    if intent == "create_workflow" and details.get("affects_external_systems"):
        if not tool_slug:
            missing_info.append("tool_slug")
        if not target_app:
            missing_info.append("target_app")
    if intent == "search_data" and _contains_any(
        request_text.lower(),
        ("search files", "query database"),
    ):
        if not tool_slug:
            missing_info.append("tool_slug")
        if not target_app:
            missing_info.append("target_app")
    if intent == "delete_data" and not _normalized_text(
        details.get("target") or details.get("data_affected")
    ):
        missing_info.append("data_affected")

    if intent in {"answer_question", "summarize"}:
        proposed_actions = [
            {
                "type": "generate_response",
                "description": (
                    "Generate a summary without changing external data."
                    if intent == "summarize"
                    else "Generate an informational answer without external side effects."
                ),
            }
        ]
    elif intent == "search_data" and not tool_slug:
        proposed_actions = [
            {
                "type": "search_memory",
                "description": "Search the authenticated user's memory context.",
                "query": request_text,
            }
        ]
    elif intent == "create_workflow" and not details.get("affects_external_systems"):
        proposed_actions = [
            {
                "type": "prepare_workflow",
                "description": "Prepare an internal workflow definition for review.",
                "workflow_name": details.get("workflow_name"),
            }
        ]
    else:
        proposed_actions = [
            {
                "type": "execute_tool",
                "description": f"Run the proposed {intent.replace('_', ' ')} action.",
                "target_app": target_app,
                "tool_slug": tool_slug,
                "recipient": recipient,
                "date_time": date_time,
                "target": details.get("target"),
                "data_affected": details.get("data_affected") or details.get("target"),
                "arguments": arguments,
                "fallback_tools": list(details.get("fallback_tools") or []),
                "fallback_safe": bool(details.get("fallback_safe")),
                "idempotent": bool(details.get("idempotent")),
            }
        ]

    return {
        "intent": intent,
        "risk_level": risk_level,
        "proposed_actions": proposed_actions,
        "required_tools": required_tools,
        "missing_info": sorted(set(missing_info)),
        "requires_user_confirmation": risk_level == "high_risk",
    }


def _find_secrets(value: Any, path: str = "request") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            item_path = f"{path}.{key}"
            if any(part in normalized for part in SECRET_KEY_PARTS):
                findings.append(item_path)
            findings.extend(_find_secrets(item, item_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_find_secrets(item, f"{path}[{index}]"))
    elif isinstance(value, str) and any(
        pattern.search(value) for pattern in SECRET_PATTERNS
    ):
        findings.append(path)
    return sorted(set(findings))


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


class AIExecutionService:
    def __init__(
        self,
        *,
        get_integrations: Callable[[str], dict[str, Any]],
        get_tool_context: Callable[[str], dict[str, Any]],
        execute_tool: Callable[..., dict[str, Any]],
        search_memory: Callable[[str, str], list[dict[str, Any]]],
        supabase_health: Callable[[], dict[str, Any]],
        redis_health: Callable[[], dict[str, Any]],
        set_temporary_state: Callable[[str, str, dict[str, Any]], bool],
        get_temporary_state: Callable[[str, str], dict[str, Any] | None],
        capture_error: Callable[..., Any],
        redact: Callable[[str], str],
        scrub: Callable[[Any], Any],
        control_plane: Any | None = None,
        reliability_platform: Any | None = None,
    ):
        self.get_integrations = get_integrations
        self.get_tool_context = get_tool_context
        self.execute_tool = execute_tool
        self.search_memory = search_memory
        self.supabase_health = supabase_health
        self.redis_health = redis_health
        self.set_temporary_state = set_temporary_state
        self.get_temporary_state = get_temporary_state
        self.capture_error = capture_error
        self.redact = redact
        self.scrub = scrub
        self.control_plane = control_plane or create_execution_control_plane()
        self.reliability_platform = reliability_platform
        self.worker_id = (
            os.getenv("RENDER_INSTANCE_ID")
            or os.getenv("HOSTNAME")
            or socket.gethostname()
            or "api-worker"
        )

    @staticmethod
    def _control_workflow_id(state: dict[str, Any]) -> str:
        return _normalized_text(state.get("workflow_id")) or state["request_id"]

    def _safe(self, value: Any) -> Any:
        return self.scrub(value)

    def _platform_project_id(self, state: dict[str, Any]) -> str | None:
        value = (state.get("metadata") or {}).get("project_id")
        return _normalized_text(value) or None

    def _platform_observe(
        self,
        state: dict[str, Any],
        *,
        observation_type: str,
        status: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Record normalized lifecycle evidence without weakening the control path."""
        if self.reliability_platform is None:
            return
        try:
            self.reliability_platform.ingest_observation(
                user_id=state["user_id"],
                project_id=self._platform_project_id(state),
                source="ai-execution-service",
                framework="matrixs",
                force_sample=status not in {"ok", "completed", "passed"},
                observation={
                    "observation_type": observation_type,
                    "status": status,
                    "workflow_id": self._control_workflow_id(state),
                    "trace_id": state["request_id"],
                    "span_id": f"{state['request_id']}:{observation_type}",
                    "risk_score": {
                        "low_risk": 0.15,
                        "medium_risk": 0.5,
                        "high_risk": 0.85,
                    }.get(state.get("risk_level"), 0.5),
                    "attributes": self._safe(payload or {}),
                },
            )
        except Exception as error:  # noqa: BLE001 - observability is isolated
            self.capture_error(
                error,
                category="reliability_observation_failure",
                user_id=state.get("user_id"),
                request_id=state.get("request_id"),
                operation=observation_type,
            )

    def _persist(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _now_iso()
        save_request(self._safe(state))
        self.set_temporary_state(
            state["user_id"],
            state["request_id"],
            self._safe(state),
        )

    def _audit(
        self,
        state: dict[str, Any],
        stage: str,
        status: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return append_audit_event(
            state["request_id"],
            state["user_id"],
            stage,
            status,
            self._safe(payload),
        )

    def _load(self, request_id: str, user_id: str) -> dict[str, Any] | None:
        cached = self.get_temporary_state(user_id, request_id)
        if cached and str(cached.get("user_id")) == str(user_id):
            return cached
        stored = get_request(request_id, user_id)
        if stored:
            self.set_temporary_state(user_id, request_id, self._safe(stored))
        return stored

    def plan(
        self,
        *,
        user_id: str,
        request_text: str,
        action: dict[str, Any] | None = None,
        chat_id: str | None = None,
        workflow_id: str | None = None,
        return_to: str = "/",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_id = f"air_{uuid.uuid4().hex}"
        plan = create_plan(request_text, action)
        secret_input_detected = bool(
            _find_secrets({"request": request_text, "action": action or {}})
        )
        created_at = _now_iso()
        state = {
            "request_id": request_id,
            "user_id": user_id,
            "request_text": self.redact(request_text),
            "intent": plan["intent"],
            "risk_level": plan["risk_level"],
            "status": "planned",
            "plan": self._safe(plan),
            "validation_result": {},
            "verification_result": {},
            "confirmation_status": (
                "required" if plan["requires_user_confirmation"] else "not_required"
            ),
            "execution_result": {},
            "chat_id": chat_id,
            "workflow_id": workflow_id,
            "return_to": return_to,
            "created_at": created_at,
            "updated_at": created_at,
            "metadata": self._safe(
                {
                    **(metadata or {}),
                    "sensitive_input_detected": secret_input_detected,
                }
            ),
        }
        if self.reliability_platform is not None:
            risk_score = {
                "low_risk": 0.15,
                "medium_risk": 0.5,
                "high_risk": 0.85,
            }.get(plan["risk_level"], 0.5)
            try:
                self.reliability_platform.admit(
                    user_id=user_id,
                    project_id=self._platform_project_id(state),
                    risk_score=risk_score,
                    tokens=max(1, round(len(request_text) / 4)),
                )
                self.reliability_platform.upsert_goal(
                    user_id=user_id,
                    project_id=self._platform_project_id(state),
                    workflow_id=self._control_workflow_id(state),
                    original_goal=request_text,
                    state={
                        "current_plan": plan,
                        "budget": (metadata or {}).get("budget") or {},
                        "cumulative_risk": risk_score,
                    },
                )
            except Exception as error:  # noqa: BLE001 - admission boundary
                self.capture_error(
                    error,
                    category="reliability_admission_failure",
                    user_id=user_id,
                    request_id=request_id,
                    operation="plan",
                )
                return {
                    "ok": False,
                    "status": "backpressure",
                    "error": "Reliability admission control rejected this request.",
                }
        self._persist(state)
        self.control_plane.start(
            user_id=user_id,
            workflow_id=self._control_workflow_id(state),
            step_id=request_id,
            policy_version="execution-control-v1",
            risk_score={"low_risk": 0.15, "medium_risk": 0.5, "high_risk": 0.85}.get(
                plan["risk_level"], 0.5
            ),
            metadata={
                "intent": plan["intent"],
                "risk_level": plan["risk_level"],
                "chat_id": chat_id,
            },
        )
        self._audit(
            state,
            "request_received",
            "completed",
            {"request_id": request_id, "user_id": user_id},
        )
        self._audit(
            state,
            "intent_classification",
            "completed",
            {"intent": plan["intent"]},
        )
        self._audit(
            state,
            "risk_detection",
            "completed",
            {"risk_level": plan["risk_level"]},
        )
        self._audit(state, "planning", "completed", {"plan": plan})
        self._platform_observe(
            state,
            observation_type="planning",
            status="completed",
            payload={"intent": plan["intent"]},
        )
        return {
            "ok": True,
            "request_id": request_id,
            "plan": plan,
            "status": state["status"],
            "next_step": "validate",
        }

    def _validation(
        self,
        state: dict[str, Any],
        integrations: dict[str, Any],
        tool_context: dict[str, Any],
    ) -> dict[str, Any]:
        plan = state["plan"]
        actions = plan.get("proposed_actions") or []
        action = actions[0] if actions else {}
        target_app = _normalized_text(action.get("target_app")).lower()
        connected_apps = {
            str(app.get("id")): app
            for app in integrations.get("apps") or []
            if app.get("connected")
        }
        tool_names = {
            str(tool.get("name") or "").upper()
            for tool in tool_context.get("tools") or []
        }
        secret_locations = _find_secrets(
            {
                "request": state["request_text"],
                "plan": plan,
            }
        )
        if state.get("metadata", {}).get("sensitive_input_detected"):
            secret_locations.append("request_input")
        required_tools = [
            str(tool).upper() for tool in plan.get("required_tools") or []
        ]
        checks = [
            _check(
                "required_plan_fields",
                all(
                    field in plan
                    for field in (
                        "intent",
                        "risk_level",
                        "proposed_actions",
                        "required_tools",
                        "missing_info",
                        "requires_user_confirmation",
                    )
                ),
                "The planner returned the required contract fields.",
            ),
            _check(
                "user_id_exists",
                bool(state.get("user_id")),
                "The request is bound to an authenticated user.",
            ),
            _check(
                "missing_information",
                not plan.get("missing_info"),
                (
                    "All required action information is present."
                    if not plan.get("missing_info")
                    else f"Missing: {', '.join(plan['missing_info'])}."
                ),
            ),
            _check(
                "connected_app",
                not target_app or target_app in connected_apps,
                (
                    f"{target_app or 'No external app'} is available."
                    if not target_app or target_app in connected_apps
                    else f"{target_app} is not connected."
                ),
            ),
            _check(
                "email_recipient",
                plan["intent"] != "send_email" or bool(action.get("recipient")),
                "Email recipient is present."
                if action.get("recipient")
                else "Email actions require a recipient.",
            ),
            _check(
                "calendar_date_time",
                plan["intent"] != "create_calendar_event"
                or bool(action.get("date_time")),
                "Calendar date/time is present."
                if action.get("date_time")
                else "Calendar actions require a date/time.",
            ),
            _check(
                "tool_permissions",
                not required_tools
                or all(tool in tool_names for tool in required_tools),
                (
                    "Required tool permissions are available."
                    if not required_tools
                    or all(tool in tool_names for tool in required_tools)
                    else "One or more required tools are unavailable."
                ),
            ),
            _check(
                "secret_exposure",
                not secret_locations,
                (
                    "No secrets were detected."
                    if not secret_locations
                    else "Potential secret material was detected and rejected."
                ),
            ),
            _check(
                "destructive_confirmation_contract",
                plan["intent"] != "delete_data"
                or plan.get("requires_user_confirmation") is True,
                "Destructive actions are protected by confirmation.",
            ),
        ]
        return {
            "passed": all(check["passed"] for check in checks),
            "checks": checks,
            "errors": [check["detail"] for check in checks if not check["passed"]],
        }

    def _verification(
        self,
        state: dict[str, Any],
        integrations: dict[str, Any],
        tool_context: dict[str, Any],
    ) -> dict[str, Any]:
        plan = state["plan"]
        actions = plan.get("proposed_actions") or []
        action = actions[0] if actions else {}
        target_app = _normalized_text(action.get("target_app")).lower()
        connected_apps = {
            str(app.get("id")): app
            for app in integrations.get("apps") or []
            if app.get("connected")
        }
        required_tools = {
            str(tool).upper() for tool in plan.get("required_tools") or []
        }
        available_tools = {
            str(tool.get("name") or "").upper()
            for tool in tool_context.get("tools") or []
        }
        memories = self.search_memory(
            state["user_id"],
            state["request_text"],
        )
        supabase = self.supabase_health()
        redis = self.redis_health()
        redis_state = self.get_temporary_state(
            state["user_id"],
            state["request_id"],
        )
        database_action = plan["intent"] in {"modify_database", "delete_data"}
        connected_database = (
            target_app in {"supabase", "postgresql"} and target_app in connected_apps
        )
        checks = [
            _check(
                "qdrant_context",
                True,
                f"Retrieved {len(memories)} memory context items; memory is evidence only.",
            ),
            _check(
                "database_availability",
                not database_action
                or bool(supabase.get("available"))
                or connected_database,
                (
                    "A verified database connection is available."
                    if not database_action
                    or supabase.get("available")
                    or connected_database
                    else "No verified database connection is available."
                ),
            ),
            _check(
                "connected_app_status",
                not target_app or target_app in connected_apps,
                (
                    f"{target_app or 'No app'} connection verified."
                    if not target_app or target_app in connected_apps
                    else f"{target_app} connection could not be verified."
                ),
            ),
            _check(
                "actual_tool_availability",
                not required_tools or required_tools.issubset(available_tools),
                (
                    "Required tools were found in the authenticated tool session."
                    if not required_tools or required_tools.issubset(available_tools)
                    else "The authenticated tool session does not expose every required tool."
                ),
            ),
            _check(
                "redis_temporary_state",
                bool(redis_state) or not redis.get("configured"),
                (
                    "Temporary execution state is available."
                    if redis_state
                    else "Redis is not configured; durable audit storage is the fallback."
                    if not redis.get("configured")
                    else "Temporary execution state is unavailable."
                ),
            ),
        ]
        return {
            "passed": all(check["passed"] for check in checks),
            "checks": checks,
            "evidence": {
                "memory_matches": self._safe(memories[:5]),
                "connected_apps": sorted(connected_apps),
                "required_tools": sorted(required_tools),
                "supabase_available": bool(supabase.get("available")),
                "redis_connected": bool(redis.get("connected")),
            },
            "errors": [check["detail"] for check in checks if not check["passed"]],
        }

    def _risk_adaptive_verification(
        self,
        *,
        state: dict[str, Any],
        validation: dict[str, Any],
        verification: dict[str, Any],
        integrations: dict[str, Any],
        tool_context: dict[str, Any],
    ) -> dict[str, Any]:
        plan = state["plan"]
        proposed = dict((plan.get("proposed_actions") or [{}])[0])
        proposed["intent"] = plan.get("intent")
        proposed.setdefault(
            "side_effect",
            plan.get("intent")
            in {
                "send_email",
                "create_calendar_event",
                "modify_database",
                "delete_data",
                "external_tool_action",
            },
        )
        proposed.setdefault("irreversible", plan.get("intent") == "delete_data")
        proposed.setdefault(
            "idempotent",
            plan.get("intent") in {"answer_question", "summarize", "search_data"},
        )
        request_metadata = dict(state.get("metadata") or {})
        proposed.setdefault(
            "sensitive_data_classes",
            request_metadata.get("sensitive_data_classes") or [],
        )
        workflow_id = _normalized_text(state.get("workflow_id")) or state["request_id"]
        step_id = state["request_id"]
        events: list[dict[str, Any]] = [
            {
                "event_type": "agent",
                "source": "planner_output",
                "status": "proposed",
                "success": True,
                "trusted": False,
                "independent": False,
                "untrusted_data": {
                    "intent": plan.get("intent"),
                    "description": proposed.get("description"),
                },
            },
            {
                "event_type": "state",
                "source": "authenticated_request_context",
                "status": "confirmed",
                "success": bool(state.get("user_id")),
                "trusted": True,
                "independent": True,
            },
            {
                "event_type": "state",
                "source": "schema_and_policy_validation",
                "status": "confirmed" if validation.get("passed") else "failed",
                "success": bool(validation.get("passed")),
                "trusted": True,
                "independent": True,
            },
            {
                "event_type": "state",
                "source": "execution_boundary_policy",
                "status": "confirmed",
                "success": True,
                "trusted": True,
                "independent": True,
            },
        ]
        for check in verification.get("checks") or []:
            events.append(
                {
                    "event_type": "tool"
                    if check.get("name") == "actual_tool_availability"
                    else "state",
                    "source": check.get("name") or "verification_check",
                    "tool_name": proposed.get("tool_slug")
                    if check.get("name") == "actual_tool_availability"
                    else None,
                    "status": "available" if check.get("passed") else "failed",
                    "success": bool(check.get("passed")),
                    "trusted": True,
                    "independent": True,
                }
            )
        known_tools = [
            _normalized_text(tool.get("name")).upper()
            for tool in tool_context.get("tools") or []
            if _normalized_text(tool.get("name"))
        ]
        original_tokens = max(1, round(len(state.get("request_text") or "") / 4))
        engine_metadata = {
            **request_metadata,
            "known_tools": known_tools,
            "tool_inventory_complete": True,
            "original_tokens": request_metadata.get("original_tokens")
            or original_tokens,
            "retry_count": request_metadata.get("retry_count") or 0,
            "retry_limit": request_metadata.get("retry_limit") or 2,
            "policy_floor": request_metadata.get("verification_policy_floor"),
            "connected_apps": [
                app.get("id")
                for app in integrations.get("apps") or []
                if app.get("connected")
            ],
        }
        result = evaluate_verification(
            user_id=state["user_id"],
            workflow_id=workflow_id,
            step_id=step_id,
            phase="pre",
            action=proposed,
            evidence_events=events,
            workflow_state=get_workflow_risk_state(state["user_id"], workflow_id),
            metadata=engine_metadata,
        )
        record_verification_evaluation(user_id=state["user_id"], result=result)
        return result

    def confirmation_card(self, state: dict[str, Any]) -> dict[str, Any]:
        plan = state["plan"]
        action = (plan.get("proposed_actions") or [{}])[0]
        return {
            "title": "Review before running",
            "request_id": state["request_id"],
            "action": action.get("description")
            or plan["intent"].replace("_", " ").title(),
            "target_app": action.get("target_app") or "Software",
            "recipient_or_target": action.get("recipient")
            or action.get("target")
            or action.get("date_time")
            or "Not specified",
            "data_affected": action.get("data_affected")
            or (
                "External communication"
                if plan["intent"] == "send_email"
                else "Calendar"
                if plan["intent"] == "create_calendar_event"
                else "External system"
            ),
            "possible_risk": (
                "This action can change data or communicate outside Software."
            ),
            "confirm_label": "Confirm",
            "cancel_label": "Cancel",
        }

    def validate(self, *, user_id: str, request_id: str) -> dict[str, Any]:
        state = self._load(request_id, user_id)
        if state is None:
            return {"ok": False, "not_found": True, "error": "AI request not found."}
        if state["status"] in {"executed", "cancelled"}:
            return {
                "ok": False,
                "error": f"Request is already {state['status']}.",
                "status": state["status"],
            }
        try:
            integrations = self.get_integrations(user_id)
            tool_context = self.get_tool_context(user_id)
            validation = self._validation(state, integrations, tool_context)
            verification = self._verification(state, integrations, tool_context)
            risk_adaptive = self._risk_adaptive_verification(
                state=state,
                validation=validation,
                verification=verification,
                integrations=integrations,
                tool_context=tool_context,
            )
            taint_state = (
                self.reliability_platform.workflow_taint_state(
                    user_id=user_id,
                    workflow_id=self._control_workflow_id(state),
                )
                if self.reliability_platform is not None
                else {"tainted": False}
            )
        except Exception as error:  # noqa: BLE001 - provider boundary is fail-closed
            self.capture_error(
                error,
                category="ai_execution_verification_failure",
                user_id=user_id,
                request_id=request_id,
                operation="validate_and_verify",
            )
            self._audit(
                state,
                "verification",
                "failed",
                {"error": self.redact(str(error))},
            )
            return {"ok": False, "error": "Validation infrastructure failed."}

        state["validation_result"] = validation
        verification["risk_adaptive"] = risk_adaptive
        state["verification_result"] = verification
        engine_decision = risk_adaptive["decision"]
        if taint_state.get("tainted"):
            engine_decision = "REVIEW"
            risk_adaptive["decision"] = "REVIEW"
            risk_adaptive["reason"] = (
                "Trusted-state enforcement detected contaminated upstream evidence."
            )
            risk_adaptive["taint_state"] = taint_state
        passed = bool(
            validation["passed"]
            and verification["passed"]
            and engine_decision not in {"BLOCK", "RETRY"}
        )
        review_required = passed and (
            engine_decision == "REVIEW" or state["risk_level"] == "high_risk"
        )
        control_decision = (
            "RETRY"
            if engine_decision == "RETRY"
            else "BLOCK"
            if not passed
            else "REVIEW"
            if review_required
            else "ALLOW"
        )
        try:
            self.control_plane.record_verification(
                user_id=user_id,
                workflow_id=self._control_workflow_id(state),
                step_id=request_id,
                decision=control_decision,
                reason=risk_adaptive.get("reason")
                or "Risk-adaptive verification completed.",
                policy_version=risk_adaptive.get("policy_version")
                or "risk-adaptive-v2",
                risk_score=float(risk_adaptive.get("current_risk") or 0),
                evidence_ids=risk_adaptive.get("evidence_ids") or [],
                auto_authorize=passed and not review_required,
            )
        except ControlPlaneError as error:
            self.capture_error(
                error,
                category="execution_control_failure",
                user_id=user_id,
                request_id=request_id,
                operation="record_verification",
            )
            if state["risk_level"] == "high_risk":
                passed = False
                review_required = False
                validation["errors"].append(
                    "Durable execution authorization could not be recorded."
                )
        if not passed:
            state["status"] = (
                "retry_required" if engine_decision == "RETRY" else "rejected"
            )
            state["confirmation_status"] = "blocked"
        elif review_required:
            state["status"] = "awaiting_confirmation"
            state["confirmation_status"] = "pending"
        else:
            state["status"] = "ready"
            state["confirmation_status"] = "not_required"
        self._persist(state)
        self._audit(
            state,
            "validation",
            "passed" if validation["passed"] else "failed",
            {"validation_result": validation},
        )
        self._platform_observe(
            state,
            observation_type="verification",
            status="passed" if passed else "failed",
            payload={
                "decision": control_decision,
                "tainted": bool(taint_state.get("tainted")),
            },
        )
        self._audit(
            state,
            "verification",
            "passed" if verification["passed"] else "failed",
            {"verification_result": verification},
        )
        confirmation_required = review_required
        return {
            "ok": passed,
            "request_id": request_id,
            "status": state["status"],
            "validation_result": validation,
            "verification_result": verification,
            "risk_adaptive": risk_adaptive,
            "confirmation_required": confirmation_required,
            "confirmation_card": (
                self.confirmation_card(state) if confirmation_required else None
            ),
            "next_step": "confirm"
            if confirmation_required
            else "execute"
            if passed
            else None,
        }

    def confirm(
        self,
        *,
        user_id: str,
        request_id: str,
        decision: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        state = self._load(request_id, user_id)
        if state is None:
            return {"ok": False, "not_found": True, "error": "AI request not found."}
        engine_decision = (
            state.get("verification_result", {})
            .get("risk_adaptive", {})
            .get("decision")
        )
        if state["risk_level"] != "high_risk" and engine_decision != "REVIEW":
            return {
                "ok": False,
                "error": "This request does not require human confirmation.",
            }
        if state["status"] != "awaiting_confirmation":
            return {
                "ok": False,
                "error": "This request is not awaiting confirmation.",
                "status": state["status"],
            }
        confirmed = decision == "confirm"
        try:
            if confirmed:
                self.control_plane.authorize(
                    user_id=user_id,
                    workflow_id=self._control_workflow_id(state),
                    step_id=request_id,
                    actor=f"user:{user_id}",
                    reason=reason or "Explicit user approval recorded.",
                )
            else:
                self.control_plane.cancel(
                    user_id=user_id,
                    workflow_id=self._control_workflow_id(state),
                    step_id=request_id,
                    actor=f"user:{user_id}",
                    reason=reason or "User rejected the proposed action.",
                )
        except ControlPlaneError as error:
            self.capture_error(
                error,
                category="execution_control_failure",
                user_id=user_id,
                request_id=request_id,
                operation="authorize_or_cancel",
            )
            return {
                "ok": False,
                "blocked": True,
                "status": state["status"],
                "error": "Durable authorization could not be recorded.",
            }
        state["confirmation_status"] = "confirmed" if confirmed else "cancelled"
        state["status"] = "ready" if confirmed else "cancelled"
        self._persist(state)
        self._audit(
            state,
            "human_confirmation",
            "confirmed" if confirmed else "cancelled",
            {
                "confirmation_status": state["confirmation_status"],
                "reason": reason,
            },
        )
        return {
            "ok": True,
            "request_id": request_id,
            "status": state["status"],
            "confirmation_status": state["confirmation_status"],
            "next_step": "execute" if confirmed else None,
        }

    def _execute_action(self, state: dict[str, Any]) -> dict[str, Any]:
        plan = state["plan"]
        action = (plan.get("proposed_actions") or [{}])[0]
        intent = plan["intent"]
        tool_slug = _normalized_text(action.get("tool_slug")).upper()
        if tool_slug:
            fallback_tools = [
                _normalized_text(item).upper()
                for item in action.get("fallback_tools") or []
                if _normalized_text(item)
            ]
            fallback_safe = bool(
                action.get("fallback_safe")
                or action.get("idempotent")
                or plan.get("intent") in {"search_data", "answer_question", "summarize"}
            )
            if self.reliability_platform is None:
                return self.execute_tool(
                    state["user_id"],
                    tool_slug,
                    action.get("arguments") or {},
                    workflow_id=state.get("workflow_id"),
                    agent_name="reliability-first-execution-engine",
                    chat_id=state.get("chat_id"),
                    return_to=state.get("return_to") or "/",
                )
            gate = self.reliability_platform.before_dependency_call(
                user_id=state["user_id"],
                project_id=self._platform_project_id(state),
                dependency_type="tool",
                dependency_name=tool_slug,
                fallback_chain=fallback_tools,
            )
            if gate["decision"] == "BLOCK" or (
                gate["decision"] == "FALLBACK" and not fallback_safe
            ):
                return {
                    "ok": False,
                    "error": "Dependency circuit is open and no safe fallback is available.",
                    "circuit_breaker": gate,
                }
            candidates = (
                list(gate.get("fallback_chain") or [])
                if gate["decision"] == "FALLBACK"
                else [tool_slug, *(fallback_tools if fallback_safe else [])]
            )
            attempts = []
            initial_failure: dict[str, Any] | None = None
            for candidate in list(dict.fromkeys(candidates)):
                candidate_gate = (
                    gate
                    if candidate == tool_slug
                    else self.reliability_platform.before_dependency_call(
                        user_id=state["user_id"],
                        project_id=self._platform_project_id(state),
                        dependency_type="tool",
                        dependency_name=candidate,
                    )
                )
                if candidate_gate["decision"] == "BLOCK":
                    attempts.append(
                        {
                            "tool": candidate,
                            "ok": False,
                            "skipped": "circuit_open",
                        }
                    )
                    continue
                started = time.perf_counter()
                try:
                    result = self.execute_tool(
                        state["user_id"],
                        candidate,
                        action.get("arguments") or {},
                        workflow_id=state.get("workflow_id"),
                        agent_name="reliability-first-execution-engine",
                        chat_id=state.get("chat_id"),
                        return_to=state.get("return_to") or "/",
                    )
                except Exception as error:  # noqa: BLE001 - provider boundary
                    self.capture_error(
                        error,
                        category="dependency_failover",
                        user_id=state["user_id"],
                        request_id=state.get("request_id"),
                        tool_slug=candidate,
                    )
                    result = {
                        "ok": False,
                        "error": self.redact(str(error))[:500]
                        or "Dependency call failed.",
                    }
                latency_ms = (time.perf_counter() - started) * 1000
                error_text = _normalized_text(result.get("error")).lower()
                error_type = (
                    "provider_timeout"
                    if "timeout" in error_text
                    else "rate_limit"
                    if "rate" in error_text and "limit" in error_text
                    else "expired_authentication"
                    if "auth" in error_text or "credential" in error_text
                    else "invalid_json"
                    if "json" in error_text
                    else "duplicate_action"
                    if "duplicate" in error_text
                    else "provider_outage"
                )
                circuit = self.reliability_platform.record_dependency_result(
                    user_id=state["user_id"],
                    circuit_id=candidate_gate["circuit_id"],
                    success=bool(result.get("ok")),
                    latency_ms=latency_ms,
                    error_type=None if result.get("ok") else error_type,
                    selected_dependency=candidate,
                )
                attempts.append(
                    {
                        "tool": candidate,
                        "ok": bool(result.get("ok")),
                        "latency_ms": round(latency_ms, 2),
                        "circuit_state": circuit["state"],
                    }
                )
                if not result.get("ok"):
                    initial_failure = initial_failure or dict(result)
                    continue
                if candidate != tool_slug or gate["decision"] == "FALLBACK":
                    result_data = (
                        result.get("data")
                        if isinstance(result.get("data"), dict)
                        else {}
                    )
                    receipt = (
                        result.get("receipt")
                        or result.get("verification_receipt")
                        or result_data.get("receipt")
                        or result_data.get("id")
                    )
                    recovery = self.reliability_platform.verify_recovery(
                        user_id=state["user_id"],
                        project_id=self._platform_project_id(state),
                        workflow_id=self._control_workflow_id(state),
                        failure_type="provider_outage",
                        attempt=len(attempts),
                        before_state=initial_failure
                        or {"ok": False, "circuit_state": gate["circuit_state"]},
                        after_state=result,
                        independent_evidence={
                            "verified": bool(result.get("verified") or receipt),
                            "receipt": receipt,
                        },
                        expected_state={"ok": True},
                        strategy="fallback_provider",
                    )
                    if not recovery["verified"]:
                        return {
                            "ok": False,
                            "error": "Fallback completed but recovery could not be verified.",
                            "recovery": recovery,
                            "failover_attempts": attempts,
                        }
                    result = {
                        **result,
                        "fallback_used": True,
                        "selected_tool": candidate,
                        "recovery": recovery,
                    }
                return {**result, "failover_attempts": attempts}
            return {
                **(
                    initial_failure
                    or {"ok": False, "error": "All dependencies failed."}
                ),
                "ok": False,
                "failover_attempts": attempts,
                "recovery_plan": self.reliability_platform.recovery_plan(
                    "provider_outage", max(1, len(attempts))
                ),
            }
        if intent == "search_data":
            return {
                "ok": True,
                "data": self.search_memory(
                    state["user_id"],
                    state["request_text"],
                ),
                "source": "qdrant_memory",
                "message": "Verified memory search completed.",
            }
        if intent in {"answer_question", "summarize"}:
            return {
                "ok": True,
                "authorized": True,
                "message": "Request approved for response generation without external side effects.",
            }
        if intent == "create_workflow":
            return {
                "ok": True,
                "authorized": True,
                "workflow_plan": action,
                "message": "Internal workflow proposal approved.",
            }
        return {
            "ok": False,
            "error": "No verified execution tool is available for this action.",
        }

    def _post_execution_verification(
        self,
        *,
        state: dict[str, Any],
        execution_result: dict[str, Any],
    ) -> dict[str, Any]:
        plan = state["plan"]
        action = dict((plan.get("proposed_actions") or [{}])[0])
        action["intent"] = plan.get("intent")
        action.setdefault(
            "side_effect",
            plan.get("intent")
            in {
                "send_email",
                "create_calendar_event",
                "modify_database",
                "delete_data",
                "external_tool_action",
            },
        )
        action.setdefault("irreversible", plan.get("intent") == "delete_data")
        action.setdefault(
            "idempotent",
            plan.get("intent") in {"answer_question", "summarize", "search_data"},
        )
        identifiers: list[str] = []
        stack: list[Any] = [execution_result]
        while stack and len(identifiers) < 20:
            item = stack.pop()
            if isinstance(item, dict):
                for key, value in item.items():
                    normalized_key = _normalized_text(key).lower()
                    if (
                        normalized_key == "id"
                        or normalized_key.endswith("_id")
                        or normalized_key in {"identifier", "transaction", "receipt"}
                    ) and _normalized_text(value):
                        identifiers.append(_normalized_text(value)[:240])
                    elif isinstance(value, (dict, list)):
                        stack.append(value)
            elif isinstance(item, list):
                stack.extend(item[:100])
        success = bool(execution_result.get("ok"))
        tool_name = action.get("tool_slug")
        events: list[dict[str, Any]] = [
            {
                "event_type": "tool" if tool_name else "state",
                "source": "tool_execution_result"
                if tool_name
                else "internal_execution_result",
                "tool_name": tool_name,
                "status": "success" if success else "failed",
                "success": success,
                "trusted": True,
                "independent": True,
                "identifiers": identifiers,
                "expected_state": True,
                "observed_state": success,
                "token_count": int(
                    (execution_result.get("usage") or {}).get("total_tokens") or 0
                )
                if isinstance(execution_result.get("usage"), dict)
                else 0,
            }
        ]
        if not tool_name:
            events.extend(
                [
                    {
                        "event_type": "state",
                        "source": "execution_boundary_policy",
                        "status": "confirmed",
                        "success": success,
                        "trusted": True,
                        "independent": True,
                        "expected_state": True,
                        "observed_state": success,
                    },
                    {
                        "event_type": "source",
                        "source": execution_result.get("source") or "internal_service",
                        "status": "confirmed",
                        "success": success,
                        "trusted": True,
                        "independent": True,
                    },
                ]
            )
        if state.get("confirmation_status") == "confirmed":
            events.append(
                {
                    "event_type": "decision",
                    "source": "human_approval_gate",
                    "status": "approved",
                    "success": True,
                    "trusted": True,
                    "independent": True,
                    "supporting_evidence_ids": [events[0].get("event_id")]
                    if events[0].get("event_id")
                    else [],
                }
            )
        workflow_id = _normalized_text(state.get("workflow_id")) or state["request_id"]
        request_metadata = dict(state.get("metadata") or {})
        result = evaluate_verification(
            user_id=state["user_id"],
            workflow_id=workflow_id,
            step_id=state["request_id"],
            phase="post",
            action=action,
            evidence_events=events,
            workflow_state=get_workflow_risk_state(state["user_id"], workflow_id),
            metadata={
                **request_metadata,
                "original_tokens": request_metadata.get("original_tokens")
                or max(1, round(len(state.get("request_text") or "") / 4)),
                "retry_count": request_metadata.get("retry_count") or 0,
                "retry_limit": request_metadata.get("retry_limit") or 2,
                "policy_floor": request_metadata.get("verification_policy_floor"),
            },
        )
        record_verification_evaluation(user_id=state["user_id"], result=result)
        return result

    def execute(self, *, user_id: str, request_id: str) -> dict[str, Any]:
        state = self._load(request_id, user_id)
        if state is None:
            return {"ok": False, "not_found": True, "error": "AI request not found."}
        if state["status"] == "executed":
            return {
                "ok": True,
                "request_id": request_id,
                "status": "executed",
                "execution_result": state["execution_result"],
                "idempotent_replay": True,
            }
        validation = state.get("validation_result") or {}
        verification = state.get("verification_result") or {}
        if not validation.get("passed") or not verification.get("passed"):
            return {
                "ok": False,
                "blocked": True,
                "status": state["status"],
                "error": "Validation and verification must pass before execution.",
            }
        engine_decision = verification.get("risk_adaptive", {}).get("decision")
        if engine_decision in {"BLOCK", "RETRY"}:
            return {
                "ok": False,
                "blocked": True,
                "status": state["status"],
                "error": f"Risk-adaptive verification returned {engine_decision}.",
            }
        if (
            state["risk_level"] == "high_risk" or engine_decision == "REVIEW"
        ) and state.get("confirmation_status") != "confirmed":
            return {
                "ok": False,
                "blocked": True,
                "confirmation_required": True,
                "status": "awaiting_confirmation",
                "error": "Risk-adaptive verification requires explicit user confirmation.",
                "confirmation_card": self.confirmation_card(state),
            }
        if state["status"] != "ready":
            return {
                "ok": False,
                "blocked": True,
                "status": state["status"],
                "error": "Request is not ready for execution.",
            }

        if self.reliability_platform is not None:
            try:
                taint_state = self.reliability_platform.workflow_taint_state(
                    user_id=user_id,
                    workflow_id=self._control_workflow_id(state),
                )
            except Exception as error:  # noqa: BLE001 - fail closed before side effects
                self.capture_error(
                    error,
                    category="reliability_taint_check_failure",
                    user_id=user_id,
                    request_id=request_id,
                    operation="execute",
                )
                return {
                    "ok": False,
                    "blocked": True,
                    "status": "control_plane_unavailable",
                    "error": "Trusted-state verification is unavailable.",
                }
            if taint_state.get("tainted"):
                return {
                    "ok": False,
                    "blocked": True,
                    "status": "review_required",
                    "error": "Execution depends on contaminated evidence.",
                    "taint_state": taint_state,
                }

        workflow_id = self._control_workflow_id(state)
        idempotency_key = f"ai-execution:{user_id}:{request_id}"
        try:
            lease: ExecutionLease = self.control_plane.begin_execution(
                user_id=user_id,
                workflow_id=workflow_id,
                step_id=request_id,
                idempotency_key=idempotency_key,
                request={
                    "intent": state.get("intent"),
                    "plan": state.get("plan") or {},
                    "confirmation_status": state.get("confirmation_status"),
                },
                owner=self.worker_id,
                lease_seconds=120,
            )
        except (IdempotencyConflict, LeaseConflict) as error:
            return {
                "ok": False,
                "blocked": True,
                "status": "already_executing",
                "error": str(error),
            }
        except ExecutionCancelled as error:
            return {
                "ok": False,
                "blocked": True,
                "status": "cancelled",
                "error": str(error),
            }
        except ControlPlaneError as error:
            self.capture_error(
                error,
                category="execution_control_failure",
                user_id=user_id,
                request_id=request_id,
                workflow_id=workflow_id,
                operation="begin_execution",
            )
            return {
                "ok": False,
                "blocked": True,
                "status": "control_plane_unavailable",
                "error": "Durable execution authorization is unavailable.",
            }
        if lease.replay:
            replay = self._safe(lease.response or {})
            return {
                "ok": bool(replay.get("ok")),
                "request_id": request_id,
                "status": "executed" if replay.get("ok") else "failed",
                "execution_result": replay,
                "idempotent_replay": True,
            }

        self._audit(state, "execution", "started", {"intent": state["intent"]})
        self._platform_observe(
            state,
            observation_type="tool_execution",
            status="started",
            payload={"intent": state["intent"]},
        )
        try:
            result = self._execute_action(state)
        except Exception as error:  # noqa: BLE001 - tool adapters may raise any provider error
            self.capture_error(
                error,
                category="ai_execution_failure",
                user_id=user_id,
                request_id=request_id,
                workflow_id=state.get("workflow_id"),
                agent_name="reliability-first-execution-engine",
                operation="execute",
            )
            result = {"ok": False, "error": self.redact(str(error))}

        if result.get("connection_required"):
            try:
                self.control_plane.fail_execution(
                    user_id=user_id,
                    lease=lease,
                    error="External integration connection is required.",
                )
            except ControlPlaneError:
                pass
            state["status"] = "awaiting_connection"
            state["execution_result"] = self._safe(result)
            self._persist(state)
            self._audit(
                state,
                "execution",
                "awaiting_connection",
                {"execution_result": result},
            )
            return {
                "ok": False,
                "request_id": request_id,
                "status": state["status"],
                **self._safe(result),
            }

        post_verification = self._post_execution_verification(
            state=state,
            execution_result=result,
        )
        result = {
            **result,
            "risk_adaptive_verification": post_verification,
        }
        success = bool(result.get("ok")) and post_verification["decision"] == "ALLOW"
        action = dict((state.get("plan", {}).get("proposed_actions") or [{}])[0])
        provider = _normalized_text(action.get("target_app")) or "internal"
        result_data = result.get("data")
        provider_action_id = (
            _normalized_text(
                result.get("provider_action_id")
                or result.get("id")
                or (result_data.get("id") if isinstance(result_data, dict) else None)
            )
            or None
        )
        try:
            control_result = self.control_plane.finalize_execution(
                user_id=user_id,
                lease=lease,
                result=self._safe(result),
                verified=success,
                provider=provider,
                provider_action_id=provider_action_id,
                evidence_ids=post_verification.get("evidence_ids") or [],
            )
            result["action_receipt_id"] = control_result["receipt_id"]
            result["execution_control_state"] = control_result["state"]
        except (ExecutionCancelled, StaleFence, ControlPlaneError) as error:
            success = False
            result = {
                **result,
                "ok": False,
                "error": "Execution result was rejected by durable control checks.",
                "control_error": self.redact(str(error)),
            }
            self.capture_error(
                error,
                category="execution_control_failure",
                user_id=user_id,
                request_id=request_id,
                workflow_id=workflow_id,
                operation="finalize_execution",
            )
        state["status"] = (
            "executed"
            if success
            else "review_required"
            if result.get("ok") and post_verification["decision"] == "REVIEW"
            else "failed"
        )
        state["execution_result"] = self._safe(result)
        self._persist(state)
        self._audit(
            state,
            "execution",
            "completed" if success else "failed",
            {"execution_result": result},
        )
        self._platform_observe(
            state,
            observation_type="execution_result",
            status="completed" if success else "failed",
            payload={
                "provider": provider,
                "provider_action_id": provider_action_id,
                "decision": post_verification.get("decision"),
            },
        )
        if success and self.reliability_platform is not None:
            try:
                evidence = self.reliability_platform.record_evidence(
                    user_id=user_id,
                    project_id=self._platform_project_id(state),
                    workflow_id=workflow_id,
                    evidence={
                        "evidence_type": "tool_receipt",
                        "producer_type": "tool",
                        "producer_id": provider,
                        "verification_status": "verified",
                        "trust_level": "trusted",
                        "payload": {
                            "receipt_id": result.get("action_receipt_id"),
                            "provider_action_id": provider_action_id,
                        },
                    },
                )
                self.reliability_platform.create_checkpoint(
                    user_id=user_id,
                    project_id=self._platform_project_id(state),
                    workflow_id=workflow_id,
                    checkpoint={
                        "state": {"status": state["status"], "intent": state["intent"]},
                        "completed_steps": [request_id],
                        "verified_evidence_ids": [evidence["evidence_id"]],
                        "external_side_effects": [
                            {
                                "provider": provider,
                                "provider_action_id": provider_action_id,
                                "receipt_id": result.get("action_receipt_id"),
                            }
                        ],
                        "verified": True,
                    },
                )
            except Exception as error:  # noqa: BLE001 - receipt already durable
                self.capture_error(
                    error,
                    category="reliability_checkpoint_failure",
                    user_id=user_id,
                    request_id=request_id,
                    operation="checkpoint",
                )
        if not success:
            self.capture_error(
                result.get("error") or "AI execution failed.",
                category="ai_execution_failure",
                user_id=user_id,
                request_id=request_id,
                workflow_id=state.get("workflow_id"),
                agent_name="reliability-first-execution-engine",
                operation="execute",
            )
        return {
            "ok": success,
            "request_id": request_id,
            "status": state["status"],
            "execution_result": self._safe(result),
        }

    def audit(self, *, user_id: str, request_id: str) -> dict[str, Any] | None:
        result = get_audit(request_id, user_id)
        if result is None:
            return None
        state = self._load(request_id, user_id)
        if state is not None:
            try:
                result["execution_control"] = self.control_plane.snapshot(
                    user_id=user_id,
                    workflow_id=self._control_workflow_id(state),
                    step_id=request_id,
                )
            except ControlPlaneError:
                result["execution_control"] = {"available": False}
        return result

    def evaluate_risk(
        self,
        *,
        user_id: str,
        workflow_id: str,
        step_id: str,
        phase: str,
        action: dict[str, Any],
        evidence: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_action = self._safe(action)
        safe_evidence = self._safe(evidence)
        raw_metadata = dict(metadata or {})
        safe_metadata = self._safe(raw_metadata)
        for key in (
            "original_tokens",
            "retry_count",
            "retry_limit",
            "retry_cost",
            "audit_base_rate",
        ):
            if isinstance(raw_metadata.get(key), (int, float)):
                safe_metadata[key] = raw_metadata[key]
        raw_budget = raw_metadata.get("token_budget")
        if isinstance(raw_budget, dict):
            safe_metadata["token_budget"] = {
                key: value
                for key, value in raw_budget.items()
                if key
                in {
                    "original_tokens",
                    "verification_budget",
                    "verification_tokens_spent",
                    "small_model_cost",
                    "frontier_model_cost",
                    "retry_cost",
                }
                and isinstance(value, (int, float))
            }
        result = evaluate_verification(
            user_id=user_id,
            workflow_id=workflow_id,
            step_id=step_id,
            phase=phase,
            action=safe_action,
            evidence_events=safe_evidence,
            workflow_state=get_workflow_risk_state(user_id, workflow_id),
            metadata=safe_metadata,
        )
        record_verification_evaluation(user_id=user_id, result=result)
        return result

    def verification_workflow(
        self,
        *,
        user_id: str,
        workflow_id: str,
        evidence_limit: int = 200,
        decision_limit: int = 100,
    ) -> dict[str, Any]:
        return {
            "workflow_id": workflow_id,
            "state": get_workflow_risk_state(user_id, workflow_id),
            "evidence": list_workflow_evidence(
                user_id=user_id,
                workflow_id=workflow_id,
                limit=evidence_limit,
            ),
            "decisions": list_workflow_decisions(
                user_id=user_id,
                workflow_id=workflow_id,
                limit=decision_limit,
            ),
        }

    def verification_metrics(self, *, user_id: str) -> dict[str, Any]:
        return verification_metrics(user_id=user_id)

    def pending_verification_audits(
        self,
        *,
        user_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return pending_semantic_audits(user_id=user_id, limit=limit)

    def submit_semantic_audit(
        self,
        *,
        user_id: str,
        decision_id: str,
        outcome: str,
        verifier: str,
        tokens_used: int = 0,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return record_semantic_audit(
            user_id=user_id,
            decision_id=decision_id,
            outcome=outcome,
            verifier=verifier,
            tokens_used=tokens_used,
            notes=self.redact(notes) if notes else None,
        )
