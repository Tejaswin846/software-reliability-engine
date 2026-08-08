from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


POLICY_VERSION = "risk-adaptive-v2.0"

EVENT_TYPES = {
    "agent",
    "tool",
    "state",
    "error",
    "side_effect",
    "decision",
    "external_confirmation",
    "source",
}

ACTION_RISK = {
    "read": 10.0,
    "write": 42.0,
    "execute": 55.0,
    "unknown": 65.0,
    "send": 70.0,
    "privilege": 82.0,
    "delete": 88.0,
    "pay": 94.0,
}

ACTION_TERMS: Sequence[Tuple[str, Sequence[str]]] = (
    ("pay", ("pay", "charge", "purchase", "transfer", "refund", "invoice")),
    ("delete", ("delete", "drop", "truncate", "erase", "purge", "remove permanently")),
    (
        "privilege",
        ("permission", "privilege", "role", "admin", "credential", "authentication"),
    ),
    ("send", ("send", "email", "publish", "post", "notify", "message", "external")),
    ("write", ("write", "update", "modify", "insert", "create", "schedule", "upload")),
    ("execute", ("execute", "run", "invoke", "call tool", "workflow")),
    (
        "read",
        (
            "read",
            "get",
            "list",
            "search",
            "query",
            "retrieve",
            "summarize",
            "answer",
            "generate_response",
        ),
    ),
)

TRANSIENT_STATUSES = {
    "timeout",
    "timed_out",
    "unavailable",
    "rate_limited",
    "temporary_failure",
}
AUTH_FAILURE_STATUSES = {
    "unauthorized",
    "forbidden",
    "authentication_failed",
    "permission_denied",
}
FAILURE_STATUSES = (
    TRANSIENT_STATUSES
    | AUTH_FAILURE_STATUSES
    | {
        "error",
        "failed",
        "exception",
        "rejected",
    }
)
SUCCESS_STATUSES = {
    "ok",
    "success",
    "succeeded",
    "completed",
    "available",
    "confirmed",
    "approved",
    "allow",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _text(value).lower()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def classify_action(action: Dict[str, Any]) -> str:
    explicit = _lower(action.get("action_class"))
    if explicit in ACTION_RISK:
        return explicit
    intent = _lower(action.get("intent"))
    intent_classes = {
        "answer_question": "read",
        "summarize": "read",
        "search_data": "read",
        "create_workflow": "write",
        "send_email": "send",
        "create_calendar_event": "write",
        "modify_database": "write",
        "delete_data": "delete",
        "external_tool_action": "execute",
    }
    if intent in intent_classes:
        return intent_classes[intent]
    searchable = " ".join(
        _lower(action.get(key))
        for key in (
            "type",
            "intent",
            "action_type",
            "description",
            "tool_slug",
            "target",
        )
    )
    for action_class, terms in ACTION_TERMS:
        if any(term in searchable for term in terms):
            return action_class
    return "unknown"


def action_fingerprint(action: Dict[str, Any]) -> str:
    return _stable_hash(
        {
            "action_class": classify_action(action),
            "intent": action.get("intent"),
            "type": action.get("type") or action.get("action_type"),
            "tool_slug": action.get("tool_slug"),
            "target": action.get("target") or action.get("recipient"),
            "arguments": action.get("arguments") or {},
        }
    )


def normalize_evidence_event(
    raw: Dict[str, Any],
    *,
    workflow_id: str,
    step_id: str,
) -> Dict[str, Any]:
    event_type = _lower(raw.get("event_type") or raw.get("type"))
    if event_type not in EVENT_TYPES:
        event_type = "agent"
    status = _lower(raw.get("status")) or "observed"
    success_value = raw.get("success")
    if success_value is None:
        success: Optional[bool]
        if status in SUCCESS_STATUSES:
            success = True
        elif status in FAILURE_STATUSES:
            success = False
        else:
            success = None
    else:
        success = bool(success_value)
    event_id = (
        _text(raw.get("event_id"))
        or f"evi_{_stable_hash([workflow_id, step_id, raw])[:24]}"
    )
    source = _text(raw.get("source")) or event_type
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    identifiers = raw.get("identifiers") or payload.get("identifiers") or []
    if isinstance(identifiers, str):
        identifiers = [identifiers]
    data_classes = raw.get("data_classes") or payload.get("data_classes") or []
    if isinstance(data_classes, str):
        data_classes = [data_classes]
    return {
        "event_id": event_id[:180],
        "workflow_id": workflow_id,
        "step_id": _text(raw.get("step_id")) or step_id,
        "event_type": event_type,
        "source": source[:160],
        "status": status[:80],
        "success": success,
        "trusted": bool(raw.get("trusted", event_type != "agent")),
        "independent": bool(
            raw.get(
                "independent",
                event_type
                in {"tool", "state", "error", "external_confirmation", "source"},
            )
        ),
        "tool_name": _text(raw.get("tool_name") or payload.get("tool_name"))[:240]
        or None,
        "action_class": _lower(raw.get("action_class")) or None,
        "side_effect": bool(raw.get("side_effect", payload.get("side_effect", False))),
        "irreversible": bool(
            raw.get("irreversible", payload.get("irreversible", False))
        ),
        "data_classes": sorted({_lower(item) for item in data_classes if _text(item)}),
        "expected_state": raw.get("expected_state", payload.get("expected_state")),
        "observed_state": raw.get("observed_state", payload.get("observed_state")),
        "identifiers": [_text(item)[:240] for item in identifiers if _text(item)],
        "token_count": max(
            0, _integer(raw.get("token_count") or payload.get("token_count") or 0)
        ),
        "latency_ms": max(
            0.0, _number(raw.get("latency_ms") or payload.get("latency_ms") or 0.0)
        ),
        # Agent/model output is always retained as data, never promoted to verifier instructions.
        "untrusted_data": raw.get("untrusted_data", payload.get("untrusted_data")),
        "supporting_evidence_ids": list(raw.get("supporting_evidence_ids") or []),
        "created_at": _text(raw.get("created_at")) or _now_iso(),
        "payload": payload,
    }


def normalize_evidence(
    events: Iterable[Dict[str, Any]],
    *,
    workflow_id: str,
    step_id: str,
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in events:
        if not isinstance(raw, dict):
            continue
        event = normalize_evidence_event(raw, workflow_id=workflow_id, step_id=step_id)
        if event["event_id"] in seen:
            continue
        seen.add(event["event_id"])
        normalized.append(event)
    return normalized


def _check(
    name: str, passed: bool, detail: str, *, severity: str = "block"
) -> Dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "detail": detail,
        "severity": severity,
    }


def deterministic_checks(
    *,
    workflow_id: str,
    step_id: str,
    phase: str,
    action: Dict[str, Any],
    action_class: str,
    events: Sequence[Dict[str, Any]],
    workflow_state: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    tool_name = _text(action.get("tool_slug") or action.get("tool_name")).upper()
    known_tools = {
        _text(item).upper() for item in metadata.get("known_tools") or [] if _text(item)
    }
    inventory_complete = bool(
        metadata.get("tool_inventory_complete", bool(known_tools))
    )
    unknown_tool = bool(
        tool_name and inventory_complete and tool_name not in known_tools
    )
    unexpected_tool_events = [
        event
        for event in events
        if event["event_type"] == "tool"
        and event.get("tool_name")
        and (not tool_name or _text(event.get("tool_name")).upper() != tool_name)
    ]
    failures = [
        event
        for event in events
        if event.get("success") is False or event.get("status") in FAILURE_STATUSES
    ]
    transient_failures = [
        event for event in failures if event.get("status") in TRANSIENT_STATUSES
    ]
    auth_failures = [
        event for event in failures if event.get("status") in AUTH_FAILURE_STATUSES
    ]
    agent_success = any(
        event["event_type"] == "agent" and event.get("success") is True
        for event in events
    )
    independent_failure = any(
        event.get("independent") and event.get("success") is False for event in events
    )
    contradictions = agent_success and independent_failure
    invalid_transitions = [
        event
        for event in events
        if event.get("expected_state") is not None
        and event.get("observed_state") is not None
        and event.get("expected_state") != event.get("observed_state")
    ]
    fingerprint = action_fingerprint(action)
    previous_actions = workflow_state.get("actions") or []
    duplicate = any(
        item.get("fingerprint") == fingerprint and item.get("step_id") != step_id
        for item in previous_actions
        if isinstance(item, dict)
    )
    retries = max(
        _integer(action.get("retry_count") or metadata.get("retry_count") or 0),
        _integer(workflow_state.get("retry_count") or 0),
    )
    retry_limit = max(0, _integer(metadata.get("retry_limit", 2), 2))
    side_effect = bool(action.get("side_effect")) or action_class in {
        "write",
        "send",
        "delete",
        "pay",
        "privilege",
        "execute",
    }
    successful_independent = [
        event
        for event in events
        if event.get("independent") and event.get("success") is True
    ]
    external_confirmation = [
        event
        for event in successful_independent
        if event["event_type"] == "external_confirmation"
        or bool(event.get("identifiers"))
        or (
            event["event_type"] == "state"
            and event.get("expected_state") is not None
            and event.get("expected_state") == event.get("observed_state")
        )
    ]
    post_evidence_ok = phase != "post" or not side_effect or bool(external_confirmation)
    schema_ok = bool(
        workflow_id
        and step_id
        and action
        and (action.get("type") or action.get("intent") or action.get("action_type"))
    )
    checks = [
        _check(
            "required_fields",
            schema_ok,
            "Workflow, step, and action fields are present."
            if schema_ok
            else "Workflow, step, or action fields are missing.",
        ),
        _check(
            "tool_classified",
            not unknown_tool,
            "The requested tool is classified."
            if not unknown_tool
            else "The requested tool is unknown and defaults to elevated risk.",
            severity="escalate",
        ),
        _check(
            "tool_status",
            not failures,
            "No tool, timeout, authentication, or execution failure was observed."
            if not failures
            else f"Observed {len(failures)} independent failure event(s).",
            severity="retry" if transient_failures and not auth_failures else "block",
        ),
        _check(
            "authentication",
            not auth_failures,
            "No authentication or permission failure was observed."
            if not auth_failures
            else "Authentication or authorization failed.",
        ),
        _check(
            "unexpected_tool",
            not unexpected_tool_events,
            "Observed tool evidence matches the planned tool."
            if not unexpected_tool_events
            else "Execution evidence contains a tool that was not in the plan.",
        ),
        _check(
            "duplicate_action",
            not duplicate or bool(action.get("idempotent")),
            "No unsafe duplicate action was detected."
            if not duplicate
            else "The same non-idempotent action appeared in another workflow step.",
        ),
        _check(
            "retry_limit",
            retries <= retry_limit,
            f"Retry count {retries} is within the configured limit {retry_limit}."
            if retries <= retry_limit
            else f"Retry count {retries} exceeds the configured limit {retry_limit}.",
        ),
        _check(
            "state_transition",
            not invalid_transitions,
            "Observed state transitions match their expected state."
            if not invalid_transitions
            else "Observed state contradicts the expected transition.",
        ),
        _check(
            "required_external_evidence",
            post_evidence_ok,
            "Required independent post-action evidence is present."
            if post_evidence_ok
            else "A side effect was reported without independent confirmation or an identifier.",
        ),
        _check(
            "false_success_contradiction",
            not contradictions,
            "Agent claims do not contradict independent evidence."
            if not contradictions
            else "The agent claimed success while independent evidence reported failure.",
        ),
    ]
    hard_failures = [
        check
        for check in checks
        if not check["passed"] and check["severity"] == "block"
    ]
    retry_failures = [
        check
        for check in checks
        if not check["passed"] and check["severity"] == "retry"
    ]
    escalations = [
        check
        for check in checks
        if not check["passed"] and check["severity"] == "escalate"
    ]
    return {
        "passed": not hard_failures and not retry_failures,
        "checks": checks,
        "hard_failures": [check["name"] for check in hard_failures],
        "retry_failures": [check["name"] for check in retry_failures],
        "escalations": [check["name"] for check in escalations],
        "unknown_tool": unknown_tool,
        "contradiction": contradictions,
        "fingerprint": fingerprint,
        "retry_count": retries,
        "retry_limit": retry_limit,
    }


def _sensitive_weight(data_class: str) -> float:
    value = _lower(data_class)
    if value in {"payment", "financial", "credential", "secret", "health", "biometric"}:
        return 16.0
    if value in {"email", "address", "phone", "customer", "personal", "pii"}:
        return 8.0
    return 4.0


def _workflow_context(
    *,
    workflow_state: Dict[str, Any],
    action: Dict[str, Any],
    action_class: str,
    events: Sequence[Dict[str, Any]],
    deterministic: Dict[str, Any],
    phase: str,
) -> Tuple[Dict[str, Any], float]:
    data_classes = {
        _lower(item)
        for item in workflow_state.get("sensitive_data_classes") or []
        if _text(item)
    }
    for item in (
        action.get("sensitive_data_classes") or action.get("data_classes") or []
    ):
        if _text(item):
            data_classes.add(_lower(item))
    for event in events:
        data_classes.update(event.get("data_classes") or [])
    external_side_effects = _integer(workflow_state.get("external_side_effects") or 0)
    irreversible_actions = _integer(workflow_state.get("irreversible_actions") or 0)
    failure_count = _integer(workflow_state.get("failure_count") or 0)
    retry_count = max(
        _integer(workflow_state.get("retry_count") or 0), deterministic["retry_count"]
    )
    policy_violations = _integer(workflow_state.get("policy_violations") or 0)
    privilege_level = max(
        _integer(workflow_state.get("privilege_level") or 0),
        _integer(action.get("privilege_level") or 0),
        3 if action_class == "privilege" else 0,
    )
    financial_exposure = max(
        _number(workflow_state.get("financial_exposure") or 0.0),
        _number(action.get("financial_exposure") or action.get("amount") or 0.0),
    )
    successful_post_action = phase == "post" and any(
        event.get("independent") and event.get("success") is True for event in events
    )
    if successful_post_action and action_class in {
        "write",
        "execute",
        "send",
        "delete",
        "pay",
        "privilege",
    }:
        external_side_effects += 1
    if successful_post_action and (
        bool(action.get("irreversible")) or action_class in {"delete", "pay"}
    ):
        irreversible_actions += 1
    if any(event.get("success") is False for event in events):
        failure_count += 1
    policy_violations += len(deterministic["hard_failures"])
    context_score = 0.0
    context_score += min(28.0, sum(_sensitive_weight(item) for item in data_classes))
    context_score += min(20.0, external_side_effects * 5.0)
    context_score += min(24.0, irreversible_actions * 12.0)
    context_score += min(15.0, failure_count * 4.0 + retry_count * 2.0)
    context_score += min(12.0, privilege_level * 4.0)
    context_score += min(18.0, financial_exposure / 100.0)
    context_score += min(20.0, policy_violations * 8.0)
    context_score = min(100.0, context_score)
    state = {
        "policy_version": POLICY_VERSION,
        "sensitive_data_classes": sorted(data_classes),
        "external_side_effects": external_side_effects,
        "irreversible_actions": irreversible_actions,
        "failure_count": failure_count,
        "retry_count": retry_count,
        "privilege_level": privilege_level,
        "financial_exposure": round(financial_exposure, 2),
        "policy_violations": policy_violations,
        "cumulative_risk_score": round(context_score, 2),
        "high_watermark": round(
            max(float(workflow_state.get("high_watermark") or 0.0), context_score), 2
        ),
        "actions": list(workflow_state.get("actions") or []),
        "audit_stats": dict(workflow_state.get("audit_stats") or {}),
        "verification_tokens_spent": _integer(
            workflow_state.get("verification_tokens_spent") or 0
        ),
        "updated_at": _now_iso(),
    }
    return state, context_score


def score_risk(
    *,
    action: Dict[str, Any],
    action_class: str,
    workflow_state: Dict[str, Any],
    context_score: float,
    deterministic: Dict[str, Any],
) -> Dict[str, Any]:
    current = ACTION_RISK[action_class]
    side_effect = bool(action.get("side_effect")) or action_class in {
        "write",
        "execute",
        "send",
        "delete",
        "pay",
        "privilege",
    }
    irreversible = bool(action.get("irreversible")) or action_class in {"delete", "pay"}
    if side_effect:
        current += 4.0
    if irreversible:
        current += 6.0
    if deterministic["unknown_tool"]:
        current = max(current, 68.0)
    data_classes = (
        action.get("sensitive_data_classes") or action.get("data_classes") or []
    )
    if data_classes:
        current += min(
            12.0, sum(_sensitive_weight(item) for item in data_classes) / 2.0
        )
    current = min(100.0, current)
    # A workflow that has accumulated sensitive context can make a normally simple action dangerous.
    combined = max(current, context_score)
    if action_class == "send" and workflow_state.get("sensitive_data_classes"):
        combined = max(combined, 92.0)
    if deterministic["contradiction"]:
        combined = max(combined, 90.0)
    if combined >= 85:
        band = "critical"
    elif combined >= 65:
        band = "high"
    elif combined >= 35:
        band = "medium"
    else:
        band = "low"
    return {
        "action_class": action_class,
        "current_action_score": round(current, 2),
        "cumulative_workflow_score": round(context_score, 2),
        "combined_score": round(combined, 2),
        "band": band,
        "side_effect": side_effect,
        "irreversible": irreversible,
        "unknown_tool": deterministic["unknown_tool"],
    }


def score_evidence(
    *,
    phase: str,
    action_class: str,
    events: Sequence[Dict[str, Any]],
    deterministic: Dict[str, Any],
) -> Dict[str, Any]:
    positive = [event for event in events if event.get("success") is True]
    independent_positive = [event for event in positive if event.get("independent")]
    confirmations = [
        event
        for event in independent_positive
        if event["event_type"] == "external_confirmation"
        or bool(event.get("identifiers"))
        or (
            event["event_type"] == "state"
            and event.get("expected_state") is not None
            and event.get("expected_state") == event.get("observed_state")
        )
    ]
    sources = [
        event for event in independent_positive if event["event_type"] == "source"
    ]
    matching_states = [
        event
        for event in independent_positive
        if event.get("expected_state") is not None
        and event.get("expected_state") == event.get("observed_state")
    ]
    score = 0.12
    score += min(0.38, len(independent_positive) * 0.16)
    score += min(0.32, len(confirmations) * 0.18)
    score += min(0.16, len(sources) * 0.08)
    score += min(0.16, len(matching_states) * 0.08)
    if (
        phase == "pre"
        and action_class in {"read", "write", "execute"}
        and independent_positive
    ):
        score += 0.08
    if deterministic["contradiction"]:
        score -= 0.55
    if any(
        event.get("success") is False and event.get("independent") for event in events
    ):
        score -= 0.25
    score = _clamp(score)
    if score >= 0.72:
        strength = "strong"
    elif score >= 0.42:
        strength = "moderate"
    else:
        strength = "weak"
    semantic_action = action_class == "read" and any(
        event["event_type"] == "agent"
        and event.get("untrusted_data")
        and (phase == "post" or bool(event.get("payload", {}).get("semantic_output")))
        for event in events
    )
    uncertainty = 1.0 - score
    if semantic_action and not sources:
        uncertainty += 0.12
    if deterministic["unknown_tool"]:
        uncertainty += 0.18
    if deterministic["contradiction"]:
        uncertainty = 1.0
    uncertainty = _clamp(uncertainty)
    return {
        "strength": strength,
        "score": round(score, 4),
        "uncertainty": round(uncertainty, 4),
        "independent_signals": len(independent_positive),
        "external_confirmations": len(confirmations),
        "source_signals": len(sources),
        "agent_confidence_used_for_routing": False,
    }


def _level_rank(level: str) -> int:
    return {"A": 0, "B": 1, "C": 2, "S": 3}.get(level, 3)


def required_level(
    *,
    risk: Dict[str, Any],
    evidence: Dict[str, Any],
    deterministic: Dict[str, Any],
    policy_floor: Optional[str],
) -> Tuple[str, List[str]]:
    reasons: List[str] = []
    if risk["irreversible"] or risk["action_class"] in {"delete", "pay"}:
        level = "S"
        reasons.append(
            "Irreversible or financial actions require a pre-execution gate."
        )
    elif (
        risk["combined_score"] >= 70
        or evidence["uncertainty"] >= 0.72
        or deterministic["unknown_tool"]
    ):
        level = "C"
        reasons.append(
            "High consequence, uncertainty, or an unknown tool requires strong verification."
        )
    elif (
        risk["combined_score"] >= 35
        or evidence["uncertainty"] >= 0.45
        or evidence["strength"] == "weak"
    ):
        level = "B"
        reasons.append(
            "Limited consequence or semantic uncertainty requires targeted verification."
        )
    else:
        level = "A"
        reasons.append(
            "Risk is low and independent evidence is sufficient for deterministic verification."
        )
    # Hysteresis prevents tiny score differences from producing a cheaper path at a threshold.
    margin = 5.0
    if level == "A" and risk["combined_score"] >= 35.0 - margin:
        level = "B"
        reasons.append("The score is inside the medium-risk hysteresis margin.")
    elif level == "B" and risk["combined_score"] >= 70.0 - margin:
        level = "C"
        reasons.append("The score is inside the high-risk hysteresis margin.")
    normalized_floor = _text(policy_floor).upper()
    if normalized_floor in {"A", "B", "C", "S"} and _level_rank(
        normalized_floor
    ) > _level_rank(level):
        level = normalized_floor
        reasons.append(
            f"Customer policy raises the verification floor to Level {normalized_floor}."
        )
    return level, reasons


def build_token_budget(
    *,
    metadata: Dict[str, Any],
    workflow_state: Dict[str, Any],
    required: str,
    events: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    supplied = (
        metadata.get("token_budget")
        if isinstance(metadata.get("token_budget"), dict)
        else {}
    )
    original_tokens = max(
        1,
        _integer(
            supplied.get("original_tokens") or metadata.get("original_tokens") or 1000,
            1000,
        ),
    )
    default_budget = max(256, min(4000, original_tokens * 0.50))
    total_budget = max(
        0,
        _integer(
            supplied["verification_budget"]
            if "verification_budget" in supplied
            else default_budget,
            int(default_budget),
        ),
    )
    spent_before = max(
        _integer(workflow_state.get("verification_tokens_spent") or 0),
        _integer(supplied.get("verification_tokens_spent") or 0),
    )
    event_spend = sum(_integer(event.get("token_count") or 0) for event in events)
    spent = spent_before + event_spend
    costs = {
        "A": 0,
        "B": max(1, _integer(supplied.get("small_model_cost") or 350, 350)),
        "C": max(1, _integer(supplied.get("frontier_model_cost") or 1200, 1200)),
        "S": 0,
    }
    next_cost = costs[required]
    remaining = max(0, total_budget - spent)
    retry_cost = max(
        0,
        _integer(
            supplied.get("retry_cost") or metadata.get("retry_cost") or original_tokens,
            original_tokens,
        ),
    )
    return {
        "original_tokens": original_tokens,
        "verification_budget": total_budget,
        "verification_tokens_spent": spent,
        "current_event_tokens": event_spend,
        "remaining_tokens": remaining,
        "expected_next_verifier_tokens": next_cost,
        "expected_retry_tokens": retry_cost,
        "normal_reserve": round(total_budget * 0.40),
        "escalation_reserve": round(total_budget * 0.40),
        "emergency_reserve": total_budget - round(total_budget * 0.80),
        "can_afford_next_verifier": next_cost <= remaining,
        "cost_ceiling_reached": next_cost > remaining,
        "safety_policy_overrides_budget": True,
    }


def _verifier_approval(
    events: Sequence[Dict[str, Any]], required: str, evidence_score: float
) -> bool:
    if required == "A":
        return True
    if required == "S":
        aliases = ("human", "approval", "reviewer")
    elif required == "C":
        aliases = ("frontier", "strong_model")
    else:
        aliases = ("small_model", "cheap_model", "semantic_verifier")
    for event in events:
        source = _lower(event.get("source"))
        approved = event["event_type"] == "decision" and event.get("status") in {
            "allow",
            "approved",
        }
        human_approval = approved and any(
            alias in source for alias in ("human", "approval", "reviewer")
        )
        if human_approval:
            return True
        if not approved or not any(alias in source for alias in aliases):
            continue
        # Verifier confidence is deliberately ignored. Approval needs traceable support.
        if (
            required == "S"
            or event.get("supporting_evidence_ids")
            or evidence_score >= 0.55
        ):
            return True
    return False


def _adaptive_audit(
    *,
    workflow_id: str,
    step_id: str,
    action_class: str,
    workflow_state: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    stats = workflow_state.get("audit_stats") or {}
    completed = max(0, _integer(stats.get("completed") or 0))
    discovered = max(0, _integer(stats.get("errors_discovered") or 0))
    base_rate = _clamp(_number(metadata.get("audit_base_rate", 0.03), 0.03), 0.01, 0.25)
    discovery_rate = discovered / completed if completed else 0.0
    rate = base_rate + min(0.20, discovery_rate * 1.5)
    if action_class == "unknown":
        rate += 0.08
    rate = _clamp(rate, 0.01, 0.25)
    sample_value = (
        int(_stable_hash([POLICY_VERSION, workflow_id, step_id])[:8], 16) / 0xFFFFFFFF
    )
    sampled = sample_value < rate
    return {
        "sampled": sampled,
        "status": "pending" if sampled else "not_sampled",
        "adaptive_rate": round(rate, 4),
        "historical_audits": completed,
        "historical_errors_discovered": discovered,
        "calibration_scope": _text(metadata.get("audit_scope")) or "workflow",
        "mandatory_verification_replaced": False,
    }


def _trusted_context(
    *,
    workflow_state: Dict[str, Any],
    events: Sequence[Dict[str, Any]],
    anomaly: bool,
) -> Dict[str, Any]:
    trusted = [event for event in events if event.get("trusted")]
    raw_refs = [event["event_id"] for event in events]
    return {
        "summary": {
            "sensitive_data_classes": workflow_state.get("sensitive_data_classes")
            or [],
            "external_side_effects": workflow_state.get("external_side_effects") or 0,
            "failures": workflow_state.get("failure_count") or 0,
            "trusted_events": len(trusted),
        },
        "raw_evidence_ids": raw_refs,
        "raw_evidence_authoritative": True,
        "expanded_for_anomaly": bool(anomaly),
        "cache": {
            "version": POLICY_VERSION,
            "ttl_seconds": 300,
            "contextual_safety_decision_cached": False,
        },
    }


def evaluate_verification(
    *,
    user_id: str,
    workflow_id: str,
    step_id: str,
    phase: str,
    action: Dict[str, Any],
    evidence_events: Iterable[Dict[str, Any]],
    workflow_state: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    started = time.perf_counter()
    phase = _lower(phase) or "pre"
    if phase not in {"pre", "post"}:
        phase = "pre"
    workflow_state = dict(workflow_state or {})
    metadata = dict(metadata or {})
    action = dict(action or {})
    action_class = classify_action(action)
    events = normalize_evidence(
        evidence_events, workflow_id=workflow_id, step_id=step_id
    )
    for event in events:
        event["event_id"] = f"evi_{_stable_hash([user_id, event['event_id']])[:24]}"
    deterministic = deterministic_checks(
        workflow_id=workflow_id,
        step_id=step_id,
        phase=phase,
        action=action,
        action_class=action_class,
        events=events,
        workflow_state=workflow_state,
        metadata=metadata,
    )
    next_state, context_score = _workflow_context(
        workflow_state=workflow_state,
        action=action,
        action_class=action_class,
        events=events,
        deterministic=deterministic,
        phase=phase,
    )
    risk = score_risk(
        action=action,
        action_class=action_class,
        workflow_state=next_state,
        context_score=context_score,
        deterministic=deterministic,
    )
    next_state["high_watermark"] = round(
        max(next_state["high_watermark"], risk["combined_score"]), 2
    )
    evidence = score_evidence(
        phase=phase,
        action_class=action_class,
        events=events,
        deterministic=deterministic,
    )
    level, level_reasons = required_level(
        risk=risk,
        evidence=evidence,
        deterministic=deterministic,
        policy_floor=metadata.get("policy_floor"),
    )
    budget = build_token_budget(
        metadata=metadata,
        workflow_state=workflow_state,
        required=level,
        events=events,
    )
    verifier_names = {
        "A": "deterministic_code",
        "B": "small_semantic_model",
        "C": "frontier_model",
        "S": "human_gate",
    }
    safe_retry = bool(action.get("idempotent")) or action_class == "read"
    reason: str
    if deterministic["hard_failures"]:
        decision = "BLOCK"
        reason = "Deterministic safety checks found a blocking failure."
    elif deterministic["retry_failures"]:
        if safe_retry and deterministic["retry_count"] < deterministic["retry_limit"]:
            decision = "RETRY"
            reason = "A transient failure can be retried within the idempotency and retry policy."
        else:
            decision = "BLOCK"
            reason = "A retry is unsafe or the retry limit has been reached."
    elif level == "A":
        decision = "ALLOW"
        reason = (
            "Deterministic checks and independent evidence satisfy the Level A policy."
        )
    elif _verifier_approval(events, level, evidence["score"]):
        decision = "ALLOW"
        reason = f"Level {level} approval is backed by traceable evidence."
    else:
        decision = "REVIEW"
        if budget["cost_ceiling_reached"] and level in {"B", "C"}:
            reason = "The required verifier exceeds the cost ceiling; safety policy routes to review instead of downgrading."
        else:
            reason = (
                f"Level {level} verification is required before execution can continue."
            )
    audit = (
        _adaptive_audit(
            workflow_id=workflow_id,
            step_id=step_id,
            action_class=action_class,
            workflow_state=workflow_state,
            metadata=metadata,
        )
        if decision == "ALLOW" and level == "A"
        else {
            "sampled": False,
            "status": "not_applicable",
            "adaptive_rate": 0.0,
            "mandatory_verification_replaced": False,
        }
    )
    actions = [item for item in next_state["actions"] if isinstance(item, dict)]
    if not any(item.get("step_id") == step_id for item in actions):
        actions.append(
            {
                "step_id": step_id,
                "fingerprint": deterministic["fingerprint"],
                "action_class": action_class,
                "phase": phase,
                "decision": decision,
                "created_at": _now_iso(),
            }
        )
    next_state["actions"] = actions[-100:]
    next_state["verification_tokens_spent"] = budget["verification_tokens_spent"]
    decision_id = (
        f"rav_{_stable_hash([user_id, workflow_id, step_id, phase, _now_iso()])[:28]}"
    )
    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
    selected_verifier = "human_gate" if decision == "REVIEW" else verifier_names[level]
    return {
        "policy_version": POLICY_VERSION,
        "decision_id": decision_id,
        "user_id": user_id,
        "workflow_id": workflow_id,
        "step_id": step_id,
        "phase": phase,
        "decision": decision,
        "verification_level": level,
        "verifier": selected_verifier,
        "required_verifier": verifier_names[level],
        "reason": reason,
        "routing_reasons": level_reasons,
        "deterministic": deterministic,
        "risk": risk,
        "evidence": evidence,
        "budget": budget,
        "semantic_audit": audit,
        "trusted_context": _trusted_context(
            workflow_state=next_state,
            events=events,
            anomaly=bool(
                deterministic["contradiction"] or deterministic["hard_failures"]
            ),
        ),
        "normalized_evidence": events,
        "workflow_state": next_state,
        "decision_latency_ms": latency_ms,
        "created_at": _now_iso(),
    }
