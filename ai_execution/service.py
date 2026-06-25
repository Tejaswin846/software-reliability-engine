from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .storage import append_audit_event, get_audit, get_request, save_request


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
    re.compile(
        r"(?i)\b(api[-_ ]?key|password|secret|token)\s*[=:]\s*[^\s,;]+"
    ),
)

EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
DATE_PATTERN = re.compile(
    r"\b(?:20\d{2}-\d{2}-\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?\b"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def classify_intent(request_text: str, action: Optional[Dict[str, Any]] = None) -> str:
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
    action: Optional[Dict[str, Any]] = None,
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


def _extract_recipient(request_text: str, action: Dict[str, Any]) -> Optional[str]:
    for key in ("recipient", "to", "email"):
        value = _normalized_text(action.get(key))
        if value:
            return value
    match = EMAIL_PATTERN.search(request_text)
    return match.group(0) if match else None


def _extract_date_time(request_text: str, action: Dict[str, Any]) -> Optional[str]:
    for key in ("date_time", "datetime", "start_time", "start", "date"):
        value = _normalized_text(action.get(key))
        if value:
            return value
    match = DATE_PATTERN.search(request_text)
    return match.group(0) if match else None


def _target_app(intent: str, request_text: str, action: Dict[str, Any]) -> Optional[str]:
    explicit = _normalized_text(action.get("app_id") or action.get("target_app")).lower()
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


def _default_tool_slug(intent: str, target_app: Optional[str]) -> Optional[str]:
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
    action: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    details = dict(action or {})
    intent = classify_intent(request_text, details)
    risk_level = detect_risk_level(intent, request_text, details)
    target_app = _target_app(intent, request_text, details)
    recipient = _extract_recipient(request_text, details)
    date_time = _extract_date_time(request_text, details)
    tool_slug = _normalized_text(details.get("tool_slug")).upper() or _default_tool_slug(
        intent, target_app
    )
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
    missing_info: List[str] = []
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


def _find_secrets(value: Any, path: str = "request") -> List[str]:
    findings: List[str] = []
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
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in SECRET_PATTERNS):
            findings.append(path)
    return sorted(set(findings))


def _check(name: str, passed: bool, detail: str) -> Dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


class AIExecutionService:
    def __init__(
        self,
        *,
        get_integrations: Callable[[str], Dict[str, Any]],
        get_tool_context: Callable[[str], Dict[str, Any]],
        execute_tool: Callable[..., Dict[str, Any]],
        search_memory: Callable[[str, str], List[Dict[str, Any]]],
        supabase_health: Callable[[], Dict[str, Any]],
        redis_health: Callable[[], Dict[str, Any]],
        set_temporary_state: Callable[[str, str, Dict[str, Any]], bool],
        get_temporary_state: Callable[[str, str], Optional[Dict[str, Any]]],
        capture_error: Callable[..., Any],
        redact: Callable[[str], str],
        scrub: Callable[[Any], Any],
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

    def _safe(self, value: Any) -> Any:
        return self.scrub(value)

    def _persist(self, state: Dict[str, Any]) -> None:
        state["updated_at"] = _now_iso()
        save_request(self._safe(state))
        self.set_temporary_state(
            state["user_id"],
            state["request_id"],
            self._safe(state),
        )

    def _audit(
        self,
        state: Dict[str, Any],
        stage: str,
        status: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        return append_audit_event(
            state["request_id"],
            state["user_id"],
            stage,
            status,
            self._safe(payload),
        )

    def _load(self, request_id: str, user_id: str) -> Optional[Dict[str, Any]]:
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
        action: Optional[Dict[str, Any]] = None,
        chat_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        return_to: str = "/",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
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
        self._persist(state)
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
        return {
            "ok": True,
            "request_id": request_id,
            "plan": plan,
            "status": state["status"],
            "next_step": "validate",
        }

    def _validation(
        self,
        state: Dict[str, Any],
        integrations: Dict[str, Any],
        tool_context: Dict[str, Any],
    ) -> Dict[str, Any]:
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
            "errors": [
                check["detail"] for check in checks if not check["passed"]
            ],
        }

    def _verification(
        self,
        state: Dict[str, Any],
        integrations: Dict[str, Any],
        tool_context: Dict[str, Any],
    ) -> Dict[str, Any]:
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
        connected_database = target_app in {"supabase", "postgresql"} and target_app in connected_apps
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
            "errors": [
                check["detail"] for check in checks if not check["passed"]
            ],
        }

    def confirmation_card(self, state: Dict[str, Any]) -> Dict[str, Any]:
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

    def validate(self, *, user_id: str, request_id: str) -> Dict[str, Any]:
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
        except Exception as error:
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
        state["verification_result"] = verification
        passed = bool(validation["passed"] and verification["passed"])
        if not passed:
            state["status"] = "rejected"
            state["confirmation_status"] = "blocked"
        elif state["risk_level"] == "high_risk":
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
        self._audit(
            state,
            "verification",
            "passed" if verification["passed"] else "failed",
            {"verification_result": verification},
        )
        confirmation_required = passed and state["risk_level"] == "high_risk"
        return {
            "ok": passed,
            "request_id": request_id,
            "status": state["status"],
            "validation_result": validation,
            "verification_result": verification,
            "confirmation_required": confirmation_required,
            "confirmation_card": (
                self.confirmation_card(state) if confirmation_required else None
            ),
            "next_step": "confirm" if confirmation_required else "execute" if passed else None,
        }

    def confirm(
        self,
        *,
        user_id: str,
        request_id: str,
        decision: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        state = self._load(request_id, user_id)
        if state is None:
            return {"ok": False, "not_found": True, "error": "AI request not found."}
        if state["risk_level"] != "high_risk":
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

    def _execute_action(self, state: Dict[str, Any]) -> Dict[str, Any]:
        plan = state["plan"]
        action = (plan.get("proposed_actions") or [{}])[0]
        intent = plan["intent"]
        tool_slug = _normalized_text(action.get("tool_slug")).upper()
        if tool_slug:
            return self.execute_tool(
                state["user_id"],
                tool_slug,
                action.get("arguments") or {},
                workflow_id=state.get("workflow_id"),
                agent_name="reliability-first-execution-engine",
                chat_id=state.get("chat_id"),
                return_to=state.get("return_to") or "/",
            )
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

    def execute(self, *, user_id: str, request_id: str) -> Dict[str, Any]:
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
        if (
            state["risk_level"] == "high_risk"
            and state.get("confirmation_status") != "confirmed"
        ):
            return {
                "ok": False,
                "blocked": True,
                "confirmation_required": True,
                "status": "awaiting_confirmation",
                "error": "High-risk action requires explicit user confirmation.",
                "confirmation_card": self.confirmation_card(state),
            }
        if state["status"] != "ready":
            return {
                "ok": False,
                "blocked": True,
                "status": state["status"],
                "error": "Request is not ready for execution.",
            }

        self._audit(state, "execution", "started", {"intent": state["intent"]})
        try:
            result = self._execute_action(state)
        except Exception as error:
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

        success = bool(result.get("ok"))
        state["status"] = "executed" if success else "failed"
        state["execution_result"] = self._safe(result)
        self._persist(state)
        self._audit(
            state,
            "execution",
            "completed" if success else "failed",
            {"execution_result": result},
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

    def audit(self, *, user_id: str, request_id: str) -> Optional[Dict[str, Any]]:
        return get_audit(request_id, user_id)
