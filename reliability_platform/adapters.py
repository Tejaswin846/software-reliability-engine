from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .core import FRAMEWORKS, ReliabilityPlatformError


def _attribute_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    for key in (
        "stringValue",
        "boolValue",
        "intValue",
        "doubleValue",
        "arrayValue",
        "kvlistValue",
        "bytesValue",
    ):
        if key in value:
            raw = value[key]
            if key == "arrayValue" and isinstance(raw, dict):
                return [_attribute_value(item) for item in raw.get("values") or []]
            if key == "kvlistValue" and isinstance(raw, dict):
                return {
                    item.get("key"): _attribute_value(item.get("value"))
                    for item in raw.get("values") or []
                }
            return raw
    return value


def _attributes(items: Any) -> dict[str, Any]:
    if isinstance(items, dict):
        return dict(items)
    result: dict[str, Any] = {}
    for item in items or []:
        if isinstance(item, dict) and item.get("key"):
            result[str(item["key"])] = _attribute_value(item.get("value"))
    return result


def _nanos_iso(value: Any) -> str | None:
    try:
        nanos = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(nanos / 1_000_000_000, tz=timezone.utc).isoformat()


def normalize_otlp(payload: dict[str, Any]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    resource_spans = payload.get("resourceSpans") or payload.get("resource_spans") or []
    if not resource_spans and payload.get("spans"):
        resource_spans = [{"scopeSpans": [{"spans": payload["spans"]}]}]
    for resource_item in resource_spans:
        resource_attrs = _attributes(
            (resource_item.get("resource") or {}).get("attributes")
        )
        scope_spans = (
            resource_item.get("scopeSpans") or resource_item.get("scope_spans") or []
        )
        for scope_item in scope_spans:
            scope = scope_item.get("scope") or {}
            framework = resource_attrs.get("service.name") or scope.get("name")
            for span in scope_item.get("spans") or []:
                attrs = {**resource_attrs, **_attributes(span.get("attributes"))}
                start_nanos = span.get("startTimeUnixNano") or span.get(
                    "start_time_unix_nano"
                )
                end_nanos = span.get("endTimeUnixNano") or span.get(
                    "end_time_unix_nano"
                )
                try:
                    latency_ms = max(
                        0.0, (int(end_nanos) - int(start_nanos)) / 1_000_000
                    )
                except (TypeError, ValueError):
                    latency_ms = float(attrs.get("latency_ms") or 0)
                status_data = span.get("status") or {}
                status_code = status_data.get("code") or status_data.get("statusCode")
                status = (
                    "error"
                    if str(status_code) in {"2", "STATUS_CODE_ERROR", "ERROR"}
                    else "ok"
                )
                observations.append(
                    {
                        "trace_id": span.get("traceId") or span.get("trace_id"),
                        "span_id": span.get("spanId") or span.get("span_id"),
                        "parent_span_id": span.get("parentSpanId")
                        or span.get("parent_span_id"),
                        "workflow_id": attrs.get("workflow.id")
                        or attrs.get("session.id"),
                        "agent_id": attrs.get("agent.id")
                        or attrs.get("gen_ai.agent.id"),
                        "type": attrs.get("openinference.span.kind")
                        or attrs.get("gen_ai.operation.name")
                        or "span",
                        "name": span.get("name") or "otel-span",
                        "tool_name": attrs.get("tool.name")
                        or attrs.get("gen_ai.tool.name"),
                        "model": attrs.get("llm.model_name")
                        or attrs.get("gen_ai.request.model")
                        or attrs.get("gen_ai.response.model"),
                        "provider": attrs.get("gen_ai.provider.name")
                        or attrs.get("llm.provider"),
                        "status": status,
                        "error_type": attrs.get("error.type")
                        if status == "error"
                        else None,
                        "latency_ms": latency_ms,
                        "token_cost": int(
                            attrs.get("llm.token_count.total")
                            or attrs.get("gen_ai.usage.total_tokens")
                            or 0
                        ),
                        "input_ref": attrs.get("input.ref"),
                        "output_ref": attrs.get("output.ref"),
                        "risk_score": attrs.get("matrixs.risk_score") or 0,
                        "evidence_strength": attrs.get("matrixs.evidence_strength")
                        or 0,
                        "decision": attrs.get("matrixs.decision"),
                        "started_at": _nanos_iso(start_nanos),
                        "ended_at": _nanos_iso(end_nanos),
                        "framework": framework,
                        "metadata": {"otel_attributes": attrs, "scope": scope},
                    }
                )
    return observations


def normalize_openinference(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("resourceSpans") or payload.get("resource_spans"):
        return normalize_otlp(payload)
    spans = payload.get("spans") or [payload]
    normalized = []
    for span in spans:
        attrs = _attributes(span.get("attributes"))
        normalized.append(
            {
                "trace_id": span.get("trace_id") or span.get("traceId"),
                "span_id": span.get("span_id") or span.get("spanId"),
                "parent_span_id": span.get("parent_span_id")
                or span.get("parentSpanId"),
                "workflow_id": attrs.get("session.id") or attrs.get("workflow.id"),
                "type": attrs.get("openinference.span.kind")
                or span.get("span_kind")
                or span.get("spanKind")
                or "span",
                "name": span.get("name")
                or attrs.get("tool.name")
                or "openinference-span",
                "tool_name": attrs.get("tool.name") or span.get("tool_name"),
                "model": attrs.get("llm.model_name"),
                "provider": attrs.get("llm.provider"),
                "status": span.get("status") or "ok",
                "error_type": attrs.get("error.type"),
                "latency_ms": span.get("latency_ms") or attrs.get("latency_ms") or 0,
                "token_cost": attrs.get("llm.token_count.total") or 0,
                "metadata": {"openinference_attributes": attrs},
            }
        )
    return normalized


def normalize_framework_event(
    framework: str, payload: dict[str, Any]
) -> dict[str, Any]:
    normalized_framework = framework.strip().lower().replace("_", "-")
    if normalized_framework not in FRAMEWORKS:
        raise ReliabilityPlatformError(f"Unsupported framework adapter: {framework}.")
    nested_event = payload.get("event")
    event = dict(nested_event) if isinstance(nested_event, dict) else dict(payload)
    event_type = str(
        event.get("type")
        or event.get("event_type")
        or event.get("kind")
        or event.get("span_kind")
        or (nested_event if isinstance(nested_event, str) else None)
        or "event"
    ).lower()
    status = str(event.get("status") or "unknown").lower()
    if event.get("error") or event.get("exception"):
        status = "error"
    return {
        "observation_id": event.get("id") or event.get("event_id"),
        "trace_id": event.get("trace_id")
        or event.get("run_id")
        or event.get("thread_id"),
        "span_id": event.get("span_id") or event.get("step_id") or event.get("node_id"),
        "parent_span_id": event.get("parent_span_id") or event.get("parent_run_id"),
        "workflow_id": event.get("workflow_id")
        or event.get("run_id")
        or event.get("thread_id"),
        "agent_id": event.get("agent_id")
        or event.get("agent_name")
        or event.get("node_name"),
        "type": event_type,
        "name": event.get("name")
        or event.get("tool_name")
        or event.get("node_name")
        or event_type,
        "tool_name": event.get("tool_name")
        or event.get("tool")
        or event.get("function_name"),
        "model": event.get("model") or event.get("model_name"),
        "provider": event.get("provider"),
        "status": status,
        "error_type": event.get("error_type")
        or (type(event.get("error")).__name__ if event.get("error") else None),
        "latency_ms": event.get("latency_ms") or event.get("duration_ms") or 0,
        "token_cost": event.get("token_cost") or event.get("total_tokens") or 0,
        "risk_score": event.get("risk_score") or 0,
        "evidence_strength": event.get("evidence_strength") or 0,
        "decision": event.get("decision"),
        "input_ref": event.get("input_ref"),
        "output_ref": event.get("output_ref"),
        "started_at": event.get("started_at") or event.get("timestamp"),
        "ended_at": event.get("ended_at"),
        "framework": normalized_framework,
        "metadata": {
            "framework_event": event,
            "subagent": event_type in {"agent", "subagent", "handoff"},
            "human_approval": event_type in {"human", "approval"},
            "side_effect": bool(event.get("side_effect")),
        },
    }


__all__ = ["normalize_framework_event", "normalize_openinference", "normalize_otlp"]
