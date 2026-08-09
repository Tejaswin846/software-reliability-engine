from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from . import storage

DECISION_ORDER = {"ALLOW": 0, "RETRY": 1, "REVIEW": 2, "BLOCK": 3}
EVALUATORS = {
    "schema",
    "tool_selection",
    "tool_arguments",
    "tool_result",
    "state_transition",
    "task_completion",
    "trajectory",
    "groundedness",
    "false_success",
    "policy",
    "security",
    "user_friction",
    "efficiency",
    "retry_quality",
    "recovery_quality",
    "cumulative_risk",
}
FRAMEWORKS = {
    "openai-agents",
    "langgraph",
    "langchain",
    "crewai",
    "google-adk",
    "microsoft-agent-framework",
    "anthropic-agent-sdk",
    "pydantic-ai",
    "llamaindex",
    "mastra",
    "strands",
    "mcp",
    "temporal",
}


class ReliabilityPlatformError(RuntimeError):
    pass


class AdmissionRejected(ReliabilityPlatformError):
    pass


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _clamp(value: Any, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = minimum
    return max(minimum, min(maximum, numeric))


def _json_record(record: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    result = dict(record)
    for field in fields:
        if field in result:
            result[field.removesuffix("_json")] = storage.loads(result.pop(field), {})
    return result


def _get_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _matches(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "exists":
        return actual is not None
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "in":
        return actual in (expected or [])
    if operator == "contains":
        return (
            expected in actual if isinstance(actual, (str, list, tuple, set)) else False
        )
    try:
        if operator == "gt":
            return actual > expected
        if operator == "gte":
            return actual >= expected
        if operator == "lt":
            return actual < expected
        if operator == "lte":
            return actual <= expected
    except TypeError:
        return False
    return False


class ReliabilityPlatform:
    def __init__(self, *, scrub: Callable[[Any], Any] | None = None) -> None:
        self.scrub = scrub or (lambda value: value)
        storage.initialize()

    def _redact(
        self,
        value: Any,
        *,
        actions: dict[str, str] | None = None,
        path: str = "",
    ) -> Any:
        actions = actions or {}
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                item_path = f"{path}.{key}".strip(".")
                normalized = key.lower()
                action = actions.get(item_path) or actions.get(key)
                if action is None and any(
                    part in normalized
                    for part in (
                        "password",
                        "secret",
                        "token",
                        "authorization",
                        "api_key",
                    )
                ):
                    action = "drop"
                if action == "drop":
                    continue
                if action == "hash":
                    result[key] = _hash(item)
                elif action == "tokenize":
                    result[key] = f"tok_{_hash(item)[:20]}"
                elif action == "mask" or (
                    action is None
                    and any(
                        part in normalized for part in ("email", "phone", "address")
                    )
                ):
                    text = str(item)
                    result[key] = f"***{text[-4:]}" if len(text) > 4 else "***"
                else:
                    result[key] = self._redact(item, actions=actions, path=item_path)
            return self.scrub(result)
        if isinstance(value, list):
            return [
                self._redact(item, actions=actions, path=f"{path}[{index}]")
                for index, item in enumerate(value)
            ]
        if isinstance(value, str):
            value = re.sub(
                r"(?i)\b(api[-_ ]?key|password|secret|token)\s*[=:]\s*[^\s,;]+",
                r"\1=[REDACTED]",
                value,
            )
        return self.scrub(value)

    @staticmethod
    def adaptive_sample_rate(observation: dict[str, Any]) -> float:
        status = str(observation.get("status") or "").lower()
        decision = str(observation.get("decision") or "").upper()
        risk = _clamp(observation.get("risk_score"))
        if (
            status in {"error", "failed", "blocked"}
            or decision in {"BLOCK", "REVIEW"}
            or observation.get("error_type")
            or observation.get("unknown_tool")
            or observation.get("false_success")
        ):
            return 1.0
        if risk >= 0.7:
            return 1.0
        if risk >= 0.4:
            return 0.5
        return 0.1

    def admit(
        self,
        *,
        user_id: str,
        project_id: str | None,
        risk_score: float = 0,
        queue_depth: int = 0,
        tokens: int = 0,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        window = now.replace(second=0, microsecond=0).isoformat()
        project_key = project_id or ""
        with storage.transaction(immediate=True) as db:
            controls = db.execute(
                """
                SELECT * FROM reliability_tenant_controls
                WHERE user_id = ? AND COALESCE(project_id, '') = ?
                """,
                (user_id, project_key),
            ).fetchone()
            limits = (
                dict(controls)
                if controls
                else {
                    "max_requests_per_minute": 600,
                    "max_active_workflows": 100,
                    "max_queue_depth": 10000,
                    "max_monthly_tokens": 10000000,
                }
            )
            if queue_depth >= int(limits["max_queue_depth"]):
                raise AdmissionRejected("Tenant queue-depth limit reached.")
            row = db.execute(
                """
                SELECT * FROM reliability_admission_windows
                WHERE user_id = ? AND COALESCE(project_id, '') = ? AND window_start = ?
                """,
                (user_id, project_key, window),
            ).fetchone()
            request_count = int(row["request_count"] if row else 0)
            token_count = int(row["token_count"] if row else 0)
            if request_count >= int(limits["max_requests_per_minute"]):
                raise AdmissionRejected("Tenant request rate exceeded.")
            if token_count + max(0, tokens) > int(limits["max_monthly_tokens"]):
                raise AdmissionRejected("Tenant token budget exceeded.")
            db.execute(
                """
                INSERT INTO reliability_admission_windows (
                    user_id, project_id, window_start, request_count,
                    active_workflows, token_count, updated_at
                ) VALUES (?, ?, ?, 1, 0, ?, ?)
                ON CONFLICT(user_id, project_id, window_start) DO UPDATE SET
                    request_count = request_count + 1,
                    token_count = token_count + excluded.token_count,
                    updated_at = excluded.updated_at
                """,
                (user_id, project_id, window, max(0, tokens), storage.now_iso()),
            )
        return {
            "admitted": True,
            "risk_score": _clamp(risk_score),
            "window_start": window,
            "request_count": request_count + 1,
        }

    def ingest_observation(
        self,
        *,
        user_id: str,
        project_id: str | None,
        observation: dict[str, Any],
        source: str = "matrixs-sdk",
        framework: str | None = None,
        redaction_actions: dict[str, str] | None = None,
        force_sample: bool = False,
    ) -> dict[str, Any]:
        safe = self._redact(observation, actions=redaction_actions)
        trace_id = str(safe.get("trace_id") or _id("trace"))[:180]
        span_id = str(safe.get("span_id") or _id("span"))[:180]
        observation_id = str(safe.get("observation_id") or _id("obs"))[:180]
        sample_rate = self.adaptive_sample_rate(safe)
        sample_value = int(_hash(observation_id)[:8], 16) / 0xFFFFFFFF
        sampled = force_sample or sample_value <= sample_rate
        if not sampled:
            return {
                "observation_id": observation_id,
                "trace_id": trace_id,
                "span_id": span_id,
                "sampled": False,
                "sample_rate": sample_rate,
            }
        metadata = dict(safe.get("metadata") or {})
        metadata["sample_rate"] = sample_rate
        metadata["sdk_version"] = safe.get("sdk_version")
        now = storage.now_iso()
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_observations (
                    observation_id, user_id, project_id, trace_id, span_id,
                    parent_span_id, workflow_id, agent_id, observation_type,
                    name, tool_name, model, provider, status, risk_score,
                    evidence_strength, decision, error_type, latency_ms,
                    token_cost, input_ref, output_ref, source, framework,
                    sampled, metadata_json, started_at, ended_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    user_id,
                    project_id,
                    trace_id,
                    span_id,
                    safe.get("parent_span_id"),
                    safe.get("workflow_id"),
                    safe.get("agent_id"),
                    str(safe.get("type") or safe.get("observation_type") or "event")[
                        :80
                    ],
                    str(safe.get("name") or "unnamed-observation")[:300],
                    safe.get("tool_name"),
                    safe.get("model"),
                    safe.get("provider"),
                    str(safe.get("status") or "unknown")[:80],
                    _clamp(safe.get("risk_score")),
                    _clamp(safe.get("evidence_strength")),
                    safe.get("decision"),
                    safe.get("error_type"),
                    max(0.0, float(safe.get("latency_ms") or 0)),
                    max(0, int(safe.get("token_cost") or 0)),
                    safe.get("input_ref"),
                    safe.get("output_ref"),
                    source[:120],
                    framework[:120] if framework else None,
                    storage.dumps(metadata),
                    str(safe.get("started_at") or now),
                    safe.get("ended_at"),
                    now,
                ),
            )
        if str(safe.get("status") or "").lower() in {"error", "failed"}:
            self.cluster_failure(
                user_id=user_id,
                project_id=project_id,
                workflow_id=str(safe.get("workflow_id") or trace_id),
                observation_id=observation_id,
                failure_type=str(safe.get("error_type") or "unknown"),
                provider=safe.get("provider"),
                tool_name=safe.get("tool_name"),
                model=safe.get("model"),
            )
        return {
            "observation_id": observation_id,
            "trace_id": trace_id,
            "span_id": span_id,
            "sampled": True,
            "sample_rate": sample_rate,
        }

    def query_observations(
        self,
        *,
        user_id: str,
        project_id: str | None = None,
        trace_id: str | None = None,
        workflow_id: str | None = None,
        tool_name: str | None = None,
        status: str | None = None,
        decision: str | None = None,
        minimum_risk: float | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        for column, value in (
            ("project_id", project_id),
            ("trace_id", trace_id),
            ("workflow_id", workflow_id),
            ("tool_name", tool_name),
            ("status", status),
            ("decision", decision),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if minimum_risk is not None:
            clauses.append("risk_score >= ?")
            params.append(_clamp(minimum_risk))
        params.append(max(1, min(1000, limit)))
        records = storage.rows(
            f"""
            SELECT * FROM reliability_observations
            WHERE {" AND ".join(clauses)}
            ORDER BY started_at DESC LIMIT ?
            """,
            tuple(params),
        )
        return [_json_record(record, ("metadata_json",)) for record in records]

    def register_tool_contract(
        self,
        *,
        user_id: str,
        project_id: str | None,
        contract: dict[str, Any],
    ) -> dict[str, Any]:
        tool_name = str(contract.get("tool_name") or "").strip()
        if not tool_name:
            raise ReliabilityPlatformError("tool_name is required.")
        with storage.transaction(immediate=True) as db:
            current = db.execute(
                """
                SELECT COALESCE(MAX(version), 0) AS version
                FROM reliability_tool_contracts
                WHERE user_id = ? AND COALESCE(project_id, '') = ? AND tool_name = ?
                """,
                (user_id, project_id or "", tool_name),
            ).fetchone()
            version = int(contract.get("version") or int(current["version"]) + 1)
            db.execute(
                """
                UPDATE reliability_tool_contracts SET active = 0
                WHERE user_id = ? AND COALESCE(project_id, '') = ? AND tool_name = ?
                """,
                (user_id, project_id or "", tool_name),
            )
            contract_id = _id("toolc")
            db.execute(
                """
                INSERT INTO reliability_tool_contracts (
                    contract_id, user_id, project_id, tool_name, version,
                    input_schema_json, output_schema_json, permissions_json,
                    risk_level, side_effect, reversible, idempotent,
                    expected_side_effects_json, expected_state_changes_json,
                    evidence_contract_json, max_retries, risk_floor,
                    human_confirmation_required, compensation_tool, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    contract_id,
                    user_id,
                    project_id,
                    tool_name,
                    version,
                    storage.dumps(contract.get("input_schema") or {}),
                    storage.dumps(contract.get("output_schema") or {}),
                    storage.dumps(contract.get("permissions") or []),
                    str(contract.get("risk_level") or "medium").lower(),
                    str(contract.get("side_effect") or "none"),
                    int(bool(contract.get("reversible"))),
                    int(bool(contract.get("idempotent"))),
                    storage.dumps(contract.get("expected_side_effects") or []),
                    storage.dumps(contract.get("expected_state_changes") or []),
                    storage.dumps(contract.get("evidence_contract") or {}),
                    max(0, int(contract.get("max_retries") or 0)),
                    _clamp(contract.get("risk_floor")),
                    int(bool(contract.get("human_confirmation_required"))),
                    contract.get("compensation_tool"),
                    storage.now_iso(),
                ),
            )
        return self.get_tool_contract(
            user_id=user_id,
            project_id=project_id,
            tool_name=tool_name,
            version=version,
        )

    def get_tool_contract(
        self,
        *,
        user_id: str,
        project_id: str | None,
        tool_name: str,
        version: int | None = None,
    ) -> dict[str, Any]:
        query = """
            SELECT * FROM reliability_tool_contracts
            WHERE user_id = ? AND COALESCE(project_id, '') = ? AND tool_name = ?
        """
        params: list[Any] = [user_id, project_id or "", tool_name]
        if version is None:
            query += " AND active = 1 ORDER BY version DESC LIMIT 1"
        else:
            query += " AND version = ? LIMIT 1"
            params.append(version)
        record = storage.row(query, tuple(params))
        if record is None:
            raise ReliabilityPlatformError("Tool contract was not found.")
        return _json_record(
            record,
            (
                "input_schema_json",
                "output_schema_json",
                "permissions_json",
                "expected_side_effects_json",
                "expected_state_changes_json",
                "evidence_contract_json",
            ),
        )

    @staticmethod
    def _validate_schema(payload: Any, schema: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if schema.get("type") == "object" and not isinstance(payload, dict):
            return ["Payload must be an object."]
        if not isinstance(payload, dict):
            return errors
        for field in schema.get("required") or []:
            if field not in payload:
                errors.append(f"Missing required field: {field}.")
        expected_types = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        for field, definition in (schema.get("properties") or {}).items():
            if field not in payload or "type" not in definition:
                continue
            expected = expected_types.get(definition["type"])
            if expected and not isinstance(payload[field], expected):
                errors.append(f"Field {field} must be {definition['type']}.")
        return errors

    def validate_tool_action(
        self,
        *,
        user_id: str,
        project_id: str | None,
        tool_name: str,
        arguments: dict[str, Any],
        permissions: list[str] | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        contract = self.get_tool_contract(
            user_id=user_id, project_id=project_id, tool_name=tool_name
        )
        errors = self._validate_schema(arguments, contract["input_schema"])
        required_permissions = set(contract["permissions"])
        available_permissions = set(permissions or [])
        missing = sorted(required_permissions - available_permissions)
        if missing:
            errors.append(f"Missing permissions: {', '.join(missing)}.")
        if contract["human_confirmation_required"] and not confirmed:
            errors.append("Human confirmation is required.")
        return {
            "passed": not errors,
            "errors": errors,
            "contract_id": contract["contract_id"],
            "contract_version": contract["version"],
            "risk_level": contract["risk_level"],
            "idempotent": bool(contract["idempotent"]),
            "max_retries": contract["max_retries"],
        }

    def verify_postcondition(
        self,
        *,
        user_id: str,
        project_id: str | None,
        tool_name: str,
        observed_result: dict[str, Any],
        independent_readback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        contract = self.get_tool_contract(
            user_id=user_id, project_id=project_id, tool_name=tool_name
        )
        errors = self._validate_schema(observed_result, contract["output_schema"])
        checks = []
        for expected in contract["expected_state_changes"]:
            path = str(expected.get("path") or "")
            source = (
                independent_readback
                if expected.get("independent", True)
                else observed_result
            )
            actual = _get_path(source or {}, path)
            passed = _matches(
                actual, expected.get("operator") or "eq", expected.get("value")
            )
            checks.append({"path": path, "passed": passed, "actual": actual})
            if not passed:
                errors.append(f"Post-condition failed at {path}.")
        if independent_readback is None and contract["side_effect"] != "none":
            return {
                "status": "UNKNOWN_SUCCESS",
                "passed": False,
                "errors": [*errors, "Independent state read-back is required."],
                "checks": checks,
            }
        return {
            "status": "VERIFIED_SUCCESS" if not errors else "FAILED",
            "passed": not errors,
            "errors": errors,
            "checks": checks,
        }

    def record_evidence(
        self,
        *,
        user_id: str,
        project_id: str | None,
        workflow_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self._redact(evidence.get("payload") or {})
        evidence_id = str(evidence.get("evidence_id") or _id("evid"))
        derived = list(evidence.get("derived_from") or [])
        taint = str(evidence.get("taint_status") or "trusted")
        if derived:
            placeholders = ",".join("?" for _ in derived)
            parents = storage.rows(
                f"SELECT evidence_id, taint_status FROM reliability_evidence WHERE evidence_id IN ({placeholders})",
                tuple(derived),
            )
            if any(
                parent["taint_status"] in {"untrusted", "tainted"} for parent in parents
            ):
                taint = "tainted"
        now = storage.now_iso()
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_evidence (
                    evidence_id, user_id, project_id, workflow_id, step_id,
                    source, source_type, provider_request_id, provider_response_id,
                    content_hash, trust_level, independence_group, derived_from_json,
                    verified_by_json, taint_status, freshness_at, expires_at,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    user_id,
                    project_id,
                    workflow_id,
                    evidence.get("step_id"),
                    str(evidence.get("source") or "unknown"),
                    str(evidence.get("source_type") or "agent_claim"),
                    evidence.get("provider_request_id"),
                    evidence.get("provider_response_id"),
                    _hash(payload),
                    str(evidence.get("trust_level") or "unknown"),
                    evidence.get("independence_group"),
                    storage.dumps(derived),
                    storage.dumps(evidence.get("verified_by") or []),
                    taint,
                    str(evidence.get("freshness_at") or now),
                    evidence.get("expires_at"),
                    storage.dumps(payload),
                    now,
                ),
            )
            for parent_id in derived:
                db.execute(
                    """
                    INSERT OR IGNORE INTO reliability_evidence_edges (
                        edge_id, user_id, workflow_id, parent_evidence_id,
                        child_evidence_id, relation, contaminated, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'derived_from', ?, ?)
                    """,
                    (
                        _id("edge"),
                        user_id,
                        workflow_id,
                        parent_id,
                        evidence_id,
                        int(taint == "tainted"),
                        now,
                    ),
                )
        return self.get_evidence(user_id=user_id, evidence_id=evidence_id)

    def get_evidence(self, *, user_id: str, evidence_id: str) -> dict[str, Any]:
        record = storage.row(
            "SELECT * FROM reliability_evidence WHERE user_id = ? AND evidence_id = ?",
            (user_id, evidence_id),
        )
        if record is None:
            raise ReliabilityPlatformError("Evidence was not found.")
        return _json_record(
            record,
            ("derived_from_json", "verified_by_json", "payload_json"),
        )

    def reverify_evidence(
        self,
        *,
        user_id: str,
        evidence_id: str,
        verifier: str,
        independent: bool,
        passed: bool,
    ) -> dict[str, Any]:
        evidence = self.get_evidence(user_id=user_id, evidence_id=evidence_id)
        verifiers = list(evidence["verified_by"])
        verifiers.append(
            {"verifier": verifier, "independent": independent, "passed": passed}
        )
        status = "reverified" if passed and independent else "tainted"
        with storage.transaction(immediate=True) as db:
            db.execute(
                """
                UPDATE reliability_evidence SET verified_by_json = ?, taint_status = ?
                WHERE user_id = ? AND evidence_id = ?
                """,
                (storage.dumps(verifiers), status, user_id, evidence_id),
            )
            if status == "tainted":
                self._propagate_taint(db, evidence_id)
        return self.get_evidence(user_id=user_id, evidence_id=evidence_id)

    def _propagate_taint(self, db: Any, root_evidence_id: str) -> list[str]:
        queue = [root_evidence_id]
        seen = {root_evidence_id}
        while queue:
            parent = queue.pop(0)
            children = db.execute(
                "SELECT child_evidence_id FROM reliability_evidence_edges WHERE parent_evidence_id = ?",
                (parent,),
            ).fetchall()
            for child in children:
                child_id = child["child_evidence_id"]
                if child_id in seen:
                    continue
                seen.add(child_id)
                queue.append(child_id)
                db.execute(
                    "UPDATE reliability_evidence SET taint_status = 'tainted' WHERE evidence_id = ?",
                    (child_id,),
                )
                db.execute(
                    "UPDATE reliability_evidence_edges SET contaminated = 1 WHERE parent_evidence_id = ? AND child_evidence_id = ?",
                    (parent, child_id),
                )
        return sorted(seen)

    def workflow_taint_state(self, *, user_id: str, workflow_id: str) -> dict[str, Any]:
        records = storage.rows(
            """
            SELECT evidence_id, taint_status FROM reliability_evidence
            WHERE user_id = ? AND workflow_id = ?
            """,
            (user_id, workflow_id),
        )
        tainted = [
            item["evidence_id"] for item in records if item["taint_status"] == "tainted"
        ]
        return {
            "workflow_id": workflow_id,
            "tainted": bool(tainted),
            "tainted_evidence_ids": tainted,
            "required_decision": "REVIEW" if tainted else "ALLOW",
        }

    def create_checkpoint(
        self,
        *,
        user_id: str,
        project_id: str | None,
        workflow_id: str,
        checkpoint: dict[str, Any],
    ) -> dict[str, Any]:
        with storage.transaction(immediate=True) as db:
            current = db.execute(
                """SELECT COALESCE(MAX(sequence), 0) AS sequence
                   FROM reliability_checkpoints WHERE user_id = ? AND workflow_id = ?""",
                (user_id, workflow_id),
            ).fetchone()
            sequence = int(current["sequence"]) + 1
            checkpoint_id = _id("ckpt")
            db.execute(
                """
                INSERT INTO reliability_checkpoints (
                    checkpoint_id, user_id, project_id, workflow_id, sequence,
                    workflow_state_json, verified_facts_json, pending_actions_json,
                    completed_side_effects_json, compensation_actions_json,
                    risk_score, budget_json, tool_permissions_json, evidence_ids_json,
                    goal_hash, cancellation_epoch, verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    user_id,
                    project_id,
                    workflow_id,
                    sequence,
                    storage.dumps(self._redact(checkpoint.get("workflow_state") or {})),
                    storage.dumps(checkpoint.get("verified_facts") or []),
                    storage.dumps(checkpoint.get("pending_actions") or []),
                    storage.dumps(checkpoint.get("completed_side_effects") or []),
                    storage.dumps(checkpoint.get("compensation_actions") or []),
                    _clamp(checkpoint.get("risk_score")),
                    storage.dumps(checkpoint.get("budget") or {}),
                    storage.dumps(checkpoint.get("tool_permissions") or []),
                    storage.dumps(checkpoint.get("evidence_ids") or []),
                    checkpoint.get("goal_hash"),
                    max(0, int(checkpoint.get("cancellation_epoch") or 0)),
                    int(bool(checkpoint.get("verified", True))),
                    storage.now_iso(),
                ),
            )
        return self.restore_checkpoint(user_id=user_id, workflow_id=workflow_id)

    def restore_checkpoint(self, *, user_id: str, workflow_id: str) -> dict[str, Any]:
        record = storage.row(
            """
            SELECT * FROM reliability_checkpoints
            WHERE user_id = ? AND workflow_id = ? AND verified = 1
            ORDER BY sequence DESC LIMIT 1
            """,
            (user_id, workflow_id),
        )
        if record is None:
            raise ReliabilityPlatformError("No verified checkpoint is available.")
        return _json_record(
            record,
            (
                "workflow_state_json",
                "verified_facts_json",
                "pending_actions_json",
                "completed_side_effects_json",
                "compensation_actions_json",
                "budget_json",
                "tool_permissions_json",
                "evidence_ids_json",
            ),
        )

    @staticmethod
    def recovery_plan(failure_type: str, attempt: int = 1) -> dict[str, Any]:
        normalized = failure_type.strip().lower().replace(" ", "_")
        strategies = {
            "provider_timeout": ("safe_retry", True),
            "rate_limit": ("exponential_delay", True),
            "invalid_arguments": ("repair_arguments", False),
            "expired_authentication": ("reconnect", False),
            "wrong_tool": ("replan", False),
            "stale_state": ("refresh_state", False),
            "duplicate_action": ("block", False),
            "partial_side_effect": ("verify_first", False),
            "irreversible_unknown_state": ("human_review", False),
            "semantic_failure": ("stronger_verifier", False),
            "downstream_contamination": ("rollback_checkpoint", False),
            "policy_violation": ("block", False),
        }
        strategy, retryable = strategies.get(normalized, ("human_review", False))
        bounded_attempt = max(1, attempt)
        return {
            "failure_type": normalized,
            "strategy": strategy,
            "retryable": retryable,
            "attempt": bounded_attempt,
            "delay_seconds": min(300, 2 ** (bounded_attempt - 1))
            if strategy == "exponential_delay"
            else 0,
            "requires_idempotency": retryable,
            "decision": "RETRY"
            if retryable
            else "BLOCK"
            if strategy == "block"
            else "REVIEW",
        }

    def create_saga(
        self,
        *,
        user_id: str,
        project_id: str | None,
        workflow_id: str,
        steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        saga_id = _id("saga")
        now = storage.now_iso()
        with storage.transaction() as db:
            db.execute(
                """INSERT INTO reliability_sagas (
                    saga_id, user_id, project_id, workflow_id, status,
                    cancellation_epoch, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'running', 0, ?, ?)""",
                (saga_id, user_id, project_id, workflow_id, now, now),
            )
            for sequence, step in enumerate(steps, start=1):
                db.execute(
                    """
                    INSERT INTO reliability_saga_steps (
                        step_id, saga_id, sequence, action, compensation_action,
                        reversible, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        _id("sstep"),
                        saga_id,
                        sequence,
                        str(step.get("action") or step.get("name") or "unknown"),
                        storage.dumps(
                            step.get("compensation_action") or step.get("compensation")
                        )
                        if isinstance(
                            step.get("compensation_action") or step.get("compensation"),
                            (dict, list),
                        )
                        else step.get("compensation_action")
                        or step.get("compensation"),
                        int(
                            bool(
                                step.get("reversible")
                                or step.get("compensation_action")
                                or step.get("compensation")
                            )
                        ),
                        now,
                        now,
                    ),
                )
        return self.saga_status(user_id=user_id, saga_id=saga_id)

    def complete_saga_step(
        self,
        *,
        user_id: str,
        saga_id: str,
        sequence: int,
        receipt: dict[str, Any],
        success: bool,
    ) -> dict[str, Any]:
        with storage.transaction(immediate=True) as db:
            saga = db.execute(
                "SELECT * FROM reliability_sagas WHERE saga_id = ? AND user_id = ?",
                (saga_id, user_id),
            ).fetchone()
            if saga is None or saga["status"] != "running":
                raise ReliabilityPlatformError("Saga is not running.")
            db.execute(
                """
                UPDATE reliability_saga_steps SET status = ?, action_receipt_json = ?, updated_at = ?
                WHERE saga_id = ? AND sequence = ?
                """,
                (
                    "completed" if success else "failed",
                    storage.dumps(receipt),
                    storage.now_iso(),
                    saga_id,
                    sequence,
                ),
            )
            if not success:
                db.execute(
                    "UPDATE reliability_sagas SET status = 'compensating', updated_at = ? WHERE saga_id = ?",
                    (storage.now_iso(), saga_id),
                )
            remaining = db.execute(
                "SELECT COUNT(*) AS count FROM reliability_saga_steps WHERE saga_id = ? AND status = 'pending'",
                (saga_id,),
            ).fetchone()
            if success and int(remaining["count"]) == 0:
                db.execute(
                    "UPDATE reliability_sagas SET status = 'completed', updated_at = ? WHERE saga_id = ?",
                    (storage.now_iso(), saga_id),
                )
        return self.saga_status(user_id=user_id, saga_id=saga_id)

    def compensation_plan(self, *, user_id: str, saga_id: str) -> dict[str, Any]:
        saga = self.saga_status(user_id=user_id, saga_id=saga_id)
        compensations = [
            {
                "sequence": step["sequence"],
                "action": storage.loads(
                    step["compensation_action"], step["compensation_action"]
                ),
                "source_action": step["action"],
            }
            for step in reversed(saga["steps"])
            if step["status"] == "completed"
            and step["reversible"]
            and step["compensation_action"]
        ]
        return {
            "saga_id": saga_id,
            "compensations": compensations,
            "count": len(compensations),
        }

    def saga_status(self, *, user_id: str, saga_id: str) -> dict[str, Any]:
        saga = storage.row(
            "SELECT * FROM reliability_sagas WHERE saga_id = ? AND user_id = ?",
            (saga_id, user_id),
        )
        if saga is None:
            raise ReliabilityPlatformError("Saga was not found.")
        steps = storage.rows(
            "SELECT * FROM reliability_saga_steps WHERE saga_id = ? ORDER BY sequence",
            (saga_id,),
        )
        saga["steps"] = [
            _json_record(step, ("action_receipt_json", "compensation_receipt_json"))
            for step in steps
        ]
        return saga

    def create_dataset(
        self,
        *,
        user_id: str,
        project_id: str | None,
        name: str,
        description: str | None = None,
        protected: bool = True,
    ) -> dict[str, Any]:
        with storage.transaction(immediate=True) as db:
            current = db.execute(
                """SELECT COALESCE(MAX(version), 0) AS version FROM reliability_datasets
                   WHERE user_id = ? AND COALESCE(project_id, '') = ? AND name = ?""",
                (user_id, project_id or "", name),
            ).fetchone()
            version = int(current["version"]) + 1
            dataset_id = _id("data")
            db.execute(
                """
                INSERT INTO reliability_datasets (
                    dataset_id, user_id, project_id, name, version,
                    protected, description, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    user_id,
                    project_id,
                    name,
                    version,
                    int(protected),
                    description,
                    storage.now_iso(),
                ),
            )
        return (
            storage.row(
                "SELECT * FROM reliability_datasets WHERE dataset_id = ?", (dataset_id,)
            )
            or {}
        )

    def add_dataset_case(
        self,
        *,
        user_id: str,
        dataset_id: str,
        case: dict[str, Any],
    ) -> dict[str, Any]:
        dataset = storage.row(
            "SELECT * FROM reliability_datasets WHERE dataset_id = ? AND user_id = ?",
            (dataset_id, user_id),
        )
        if dataset is None:
            raise ReliabilityPlatformError("Dataset was not found.")
        case_id = _id("case")
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_dataset_cases (
                    case_id, dataset_id, input_json, initial_state_json,
                    expected_state_json, tool_availability_json,
                    expected_tool_sequence_json, expected_output_json,
                    expected_failure_type, risk_score, correct_decision,
                    source_failure_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    dataset_id,
                    storage.dumps(self._redact(case.get("input") or {})),
                    storage.dumps(case.get("initial_state") or {}),
                    storage.dumps(case.get("expected_state") or {}),
                    storage.dumps(case.get("tool_availability") or []),
                    storage.dumps(case.get("expected_tool_sequence") or []),
                    storage.dumps(case.get("expected_output") or {}),
                    case.get("expected_failure_type"),
                    _clamp(case.get("risk_score")),
                    str(case.get("correct_decision") or "ALLOW").upper(),
                    case.get("source_failure_id"),
                    storage.now_iso(),
                ),
            )
        return _json_record(
            storage.row(
                "SELECT * FROM reliability_dataset_cases WHERE case_id = ?", (case_id,)
            )
            or {},
            (
                "input_json",
                "initial_state_json",
                "expected_state_json",
                "tool_availability_json",
                "expected_tool_sequence_json",
                "expected_output_json",
            ),
        )

    @staticmethod
    def evaluate(
        evaluator: str, actual: dict[str, Any], expected: dict[str, Any]
    ) -> dict[str, Any]:
        if evaluator not in EVALUATORS:
            raise ReliabilityPlatformError("Unknown evaluator.")
        details: dict[str, Any] = {}
        if evaluator == "schema":
            required = expected.get("required") or []
            passed = isinstance(actual, dict) and all(key in actual for key in required)
        elif evaluator in {
            "tool_selection",
            "tool_arguments",
            "tool_result",
            "state_transition",
            "task_completion",
        }:
            key = {
                "tool_selection": "tool_name",
                "tool_arguments": "arguments",
                "tool_result": "result",
                "state_transition": "state",
                "task_completion": "completed",
            }[evaluator]
            passed = actual.get(key) == expected.get(key)
            details = {"actual": actual.get(key), "expected": expected.get(key)}
        elif evaluator == "trajectory":
            actual_steps = actual.get("steps") or []
            expected_steps = expected.get("steps") or []
            overlap = len([step for step in actual_steps if step in expected_steps])
            score = overlap / max(1, len(expected_steps))
            return {
                "evaluator": evaluator,
                "score": round(score, 4),
                "passed": score >= 0.8,
                "details": {},
            }
        elif evaluator == "groundedness":
            evidence_ids = set(actual.get("evidence_ids") or [])
            claims = actual.get("claims") or []
            supported = sum(
                1
                for claim in claims
                if set(claim.get("evidence_ids") or []) & evidence_ids
            )
            score = supported / max(1, len(claims))
            return {
                "evaluator": evaluator,
                "score": round(score, 4),
                "passed": score >= 0.9,
                "details": {},
            }
        elif evaluator == "false_success":
            passed = not bool(actual.get("claimed_success")) or bool(
                actual.get("postcondition_verified")
            )
        elif evaluator == "policy":
            passed = not bool(actual.get("policy_violation"))
        elif evaluator == "security":
            passed = not bool(
                actual.get("unsafe_action") or actual.get("secret_exposure")
            )
        elif evaluator == "user_friction":
            passed = int(actual.get("loops") or 0) <= int(
                expected.get("max_loops") or 3
            )
        elif evaluator == "efficiency":
            passed = int(actual.get("steps") or 0) <= int(
                expected.get("max_steps") or 20
            )
        elif evaluator == "retry_quality":
            passed = not actual.get("retried") or bool(actual.get("retry_justified"))
        elif evaluator == "recovery_quality":
            passed = not actual.get("failed") or bool(actual.get("recovered_safely"))
        else:
            passed = float(actual.get("cumulative_risk") or 0) <= float(
                expected.get("max_risk") or 0.7
            )
        return {
            "evaluator": evaluator,
            "score": 1.0 if passed else 0.0,
            "passed": passed,
            "details": details,
        }

    def run_experiment(
        self,
        *,
        user_id: str,
        project_id: str | None,
        name: str,
        dataset_id: str,
        control: dict[str, Any],
        candidate: dict[str, Any],
        evaluators: list[str],
    ) -> dict[str, Any]:
        dataset = storage.row(
            "SELECT * FROM reliability_datasets WHERE dataset_id = ? AND user_id = ?",
            (dataset_id, user_id),
        )
        if dataset is None:
            raise ReliabilityPlatformError("Dataset was not found.")
        cases = storage.rows(
            "SELECT * FROM reliability_dataset_cases WHERE dataset_id = ? ORDER BY created_at",
            (dataset_id,),
        )
        experiment_id = _id("exp")
        now = storage.now_iso()
        metrics: dict[str, Any] = {}
        results: list[tuple[Any, ...]] = []
        variant_scores: dict[str, list[float]] = defaultdict(list)
        for case in cases:
            expected_output = storage.loads(case["expected_output_json"], {})
            for variant_name, variant in (
                ("control", control),
                ("candidate", candidate),
            ):
                actual = dict(
                    variant.get("case_results", {}).get(case["case_id"])
                    or variant.get("default_result")
                    or {}
                )
                for evaluator in evaluators:
                    evaluated = self.evaluate(evaluator, actual, expected_output)
                    variant_scores[variant_name].append(evaluated["score"])
                    results.append(
                        (
                            _id("result"),
                            experiment_id,
                            case["case_id"],
                            variant_name,
                            evaluator,
                            str(variant.get("evaluator_version") or "1"),
                            evaluated["score"],
                            int(evaluated["passed"]),
                            float(actual.get("latency_ms") or 0),
                            int(actual.get("token_cost") or 0),
                            storage.dumps(evaluated["details"]),
                            now,
                        )
                    )
        for variant, scores in variant_scores.items():
            metrics[variant] = {
                "score": round(sum(scores) / max(1, len(scores)), 4),
                "evaluations": len(scores),
            }
        metrics["candidate_delta"] = round(
            metrics.get("candidate", {}).get("score", 0)
            - metrics.get("control", {}).get("score", 0),
            4,
        )
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_experiments (
                    experiment_id, user_id, project_id, name, dataset_id,
                    control_json, candidate_json, status, metrics_json,
                    created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?)
                """,
                (
                    experiment_id,
                    user_id,
                    project_id,
                    name,
                    dataset_id,
                    storage.dumps(control),
                    storage.dumps(candidate),
                    storage.dumps(metrics),
                    now,
                    now,
                ),
            )
            db.executemany(
                """
                INSERT INTO reliability_experiment_results (
                    result_id, experiment_id, case_id, variant, evaluator,
                    evaluator_version, score, passed, latency_ms, token_cost,
                    details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                results,
            )
        return {
            "experiment_id": experiment_id,
            "status": "completed",
            "metrics": metrics,
        }

    @staticmethod
    def ci_gate(
        metrics: dict[str, Any], thresholds: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        thresholds = thresholds or {
            "false_negative_rate_max": 0.005,
            "critical_actions_verified_min": 1.0,
            "reliability_regression_max": 0.02,
            "p95_verification_ms_max": 150,
            "duplicate_executions_max": 0,
        }
        checks = []
        for name, threshold in thresholds.items():
            if name.endswith("_max"):
                metric = name.removesuffix("_max")
                actual = float(metrics.get(metric) or 0)
                passed = actual <= float(threshold)
            else:
                metric = name.removesuffix("_min")
                actual = float(metrics.get(metric) or 0)
                passed = actual >= float(threshold)
            checks.append(
                {
                    "metric": metric,
                    "actual": actual,
                    "threshold": threshold,
                    "passed": passed,
                }
            )
        return {"passed": all(check["passed"] for check in checks), "checks": checks}

    def enqueue_annotation(
        self,
        *,
        user_id: str,
        project_id: str | None,
        reason: str,
        workflow_id: str | None = None,
        observation_id: str | None = None,
        decision_id: str | None = None,
    ) -> dict[str, Any]:
        annotation_id = _id("ann")
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_annotations (
                    annotation_id, user_id, project_id, workflow_id,
                    observation_id, decision_id, queue_reason, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    annotation_id,
                    user_id,
                    project_id,
                    workflow_id,
                    observation_id,
                    decision_id,
                    reason,
                    storage.now_iso(),
                ),
            )
        return (
            storage.row(
                "SELECT * FROM reliability_annotations WHERE annotation_id = ?",
                (annotation_id,),
            )
            or {}
        )

    def complete_annotation(
        self,
        *,
        user_id: str,
        annotation_id: str,
        reviewer: str,
        label: str,
        confidence: float,
        notes: str | None = None,
    ) -> dict[str, Any]:
        with storage.transaction(immediate=True) as db:
            cursor = db.execute(
                """
                UPDATE reliability_annotations
                SET status = 'completed', assigned_to = ?, label = ?, notes = ?,
                    reviewer_confidence = ?, completed_at = ?
                WHERE annotation_id = ? AND user_id = ? AND status <> 'completed'
                """,
                (
                    reviewer,
                    label,
                    notes,
                    _clamp(confidence),
                    storage.now_iso(),
                    annotation_id,
                    user_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ReliabilityPlatformError(
                    "Annotation is unavailable or already completed."
                )
        return (
            storage.row(
                "SELECT * FROM reliability_annotations WHERE annotation_id = ?",
                (annotation_id,),
            )
            or {}
        )

    def list_annotations(
        self,
        *,
        user_id: str,
        project_id: str | None,
        status: str = "pending",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return storage.rows(
            """
            SELECT * FROM reliability_annotations
            WHERE user_id = ? AND COALESCE(project_id, '') = ? AND status = ?
            ORDER BY created_at LIMIT ?
            """,
            (user_id, project_id or "", status, max(1, min(500, limit))),
        )

    def cluster_failure(
        self,
        *,
        user_id: str,
        project_id: str | None,
        workflow_id: str,
        observation_id: str | None,
        failure_type: str,
        provider: str | None,
        tool_name: str | None,
        model: str | None,
    ) -> dict[str, Any]:
        signature = _hash(
            {
                "failure_type": failure_type,
                "provider": provider,
                "tool_name": tool_name,
                "model": model,
            }
        )[:32]
        now = storage.now_iso()
        with storage.transaction(immediate=True) as db:
            existing = db.execute(
                """
                SELECT * FROM reliability_failure_clusters
                WHERE user_id = ? AND COALESCE(project_id, '') = ? AND signature = ?
                """,
                (user_id, project_id or "", signature),
            ).fetchone()
            cluster_id = existing["cluster_id"] if existing else _id("cluster")
            if existing:
                db.execute(
                    """UPDATE reliability_failure_clusters
                       SET workflow_count = workflow_count + 1, last_seen_at = ?
                       WHERE cluster_id = ?""",
                    (now, cluster_id),
                )
            else:
                db.execute(
                    """
                    INSERT INTO reliability_failure_clusters (
                        cluster_id, user_id, project_id, signature, failure_type,
                        provider, tool_name, model, workflow_count,
                        first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        cluster_id,
                        user_id,
                        project_id,
                        signature,
                        failure_type,
                        provider,
                        tool_name,
                        model,
                        now,
                        now,
                    ),
                )
            db.execute(
                """
                INSERT OR IGNORE INTO reliability_failure_members (
                    member_id, cluster_id, workflow_id, observation_id, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (_id("fmem"), cluster_id, workflow_id, observation_id, now),
            )
        cluster = (
            storage.row(
                "SELECT * FROM reliability_failure_clusters WHERE cluster_id = ?",
                (cluster_id,),
            )
            or {}
        )
        if int(cluster.get("workflow_count") or 0) >= 3:
            self.create_incident_from_cluster(user_id=user_id, cluster_id=cluster_id)
        return cluster

    def detect_drift(
        self,
        *,
        user_id: str,
        project_id: str | None,
        component_type: str,
        component_name: str,
        baseline: dict[str, float],
        current: dict[str, float],
    ) -> dict[str, Any]:
        signals: dict[str, float] = {}
        for key in sorted(set(baseline) | set(current)):
            base = float(baseline.get(key) or 0)
            present = float(current.get(key) or 0)
            signals[key] = round(abs(present - base) / max(abs(base), 0.01), 4)
        drift_score = min(1.0, sum(signals.values()) / max(1, len(signals)))
        severity = (
            "critical"
            if drift_score >= 0.75
            else "high"
            if drift_score >= 0.5
            else "medium"
            if drift_score >= 0.25
            else "low"
        )
        report_id = _id("drift")
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_drift_reports (
                    report_id, user_id, project_id, component_type,
                    component_name, baseline_window_json, current_window_json,
                    drift_score, signals_json, severity, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    user_id,
                    project_id,
                    component_type,
                    component_name,
                    storage.dumps(baseline),
                    storage.dumps(current),
                    drift_score,
                    storage.dumps(signals),
                    severity,
                    storage.now_iso(),
                ),
            )
        return {
            "report_id": report_id,
            "drift_score": round(drift_score, 4),
            "severity": severity,
            "signals": signals,
        }

    def record_causal_edge(
        self,
        *,
        user_id: str,
        project_id: str | None,
        root_failure_id: str,
        cause_id: str,
        effect_id: str,
        relation: str,
        confidence: float,
        contaminated_outputs: list[str] | None = None,
        external_side_effects: list[str] | None = None,
    ) -> dict[str, Any]:
        edge_id = _id("cause")
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_causal_edges (
                    edge_id, user_id, project_id, root_failure_id, cause_id,
                    effect_id, relation, confidence, blast_radius,
                    contaminated_outputs_json, external_side_effects_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge_id,
                    user_id,
                    project_id,
                    root_failure_id,
                    cause_id,
                    effect_id,
                    relation,
                    _clamp(confidence),
                    len(
                        set(contaminated_outputs or [])
                        | set(external_side_effects or [])
                    ),
                    storage.dumps(contaminated_outputs or []),
                    storage.dumps(external_side_effects or []),
                    storage.now_iso(),
                ),
            )
        return (
            storage.row(
                "SELECT * FROM reliability_causal_edges WHERE edge_id = ?", (edge_id,)
            )
            or {}
        )

    def root_cause_graph(self, *, user_id: str, root_failure_id: str) -> dict[str, Any]:
        records = storage.rows(
            """SELECT * FROM reliability_causal_edges
               WHERE user_id = ? AND root_failure_id = ? ORDER BY created_at""",
            (user_id, root_failure_id),
        )
        nodes = sorted(
            {item for edge in records for item in (edge["cause_id"], edge["effect_id"])}
        )
        return {
            "root_failure_id": root_failure_id,
            "nodes": nodes,
            "edges": [
                _json_record(
                    edge, ("contaminated_outputs_json", "external_side_effects_json")
                )
                for edge in records
            ],
            "blast_radius": sum(int(edge["blast_radius"]) for edge in records),
        }

    def create_policy(
        self,
        *,
        user_id: str,
        project_id: str | None,
        name: str,
        mode: str,
        rollout_percent: float,
        rules: list[dict[str, Any]],
        tenant_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if mode not in {"shadow", "partial", "enforce"}:
            raise ReliabilityPlatformError(
                "Policy mode must be shadow, partial, or enforce."
            )
        with storage.transaction(immediate=True) as db:
            current = db.execute(
                """SELECT COALESCE(MAX(version), 0) AS version FROM reliability_policies
                   WHERE user_id = ? AND COALESCE(project_id, '') = ? AND name = ?""",
                (user_id, project_id or "", name),
            ).fetchone()
            version = int(current["version"]) + 1
            db.execute(
                "UPDATE reliability_policies SET active = 0 WHERE user_id = ? AND COALESCE(project_id, '') = ? AND name = ?",
                (user_id, project_id or "", name),
            )
            policy_id = _id("policy")
            db.execute(
                """
                INSERT INTO reliability_policies (
                    policy_id, user_id, project_id, name, version, mode,
                    rollout_percent, rules_json, tenant_overrides_json,
                    active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    policy_id,
                    user_id,
                    project_id,
                    name,
                    version,
                    mode,
                    max(0.0, min(100.0, rollout_percent)),
                    storage.dumps(rules),
                    storage.dumps(tenant_overrides or {}),
                    storage.now_iso(),
                ),
            )
        return _json_record(
            storage.row(
                "SELECT * FROM reliability_policies WHERE policy_id = ?", (policy_id,)
            )
            or {},
            ("rules_json", "tenant_overrides_json"),
        )

    def evaluate_policy(
        self,
        *,
        user_id: str,
        project_id: str | None,
        policy_name: str,
        context: dict[str, Any],
        versions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        record = storage.row(
            """
            SELECT * FROM reliability_policies
            WHERE user_id = ? AND COALESCE(project_id, '') = ?
              AND name = ? AND active = 1 ORDER BY version DESC LIMIT 1
            """,
            (user_id, project_id or "", policy_name),
        )
        if record is None:
            raise ReliabilityPlatformError("Active policy was not found.")
        policy = _json_record(record, ("rules_json", "tenant_overrides_json"))
        matches = []
        predicted = "ALLOW"
        for rule in policy["rules"]:
            if _matches(
                _get_path(context, str(rule.get("field") or "")),
                str(rule.get("operator") or "eq"),
                rule.get("value"),
            ):
                decision = str(rule.get("decision") or "REVIEW").upper()
                matches.append({**rule, "decision": decision})
                if DECISION_ORDER.get(decision, 0) > DECISION_ORDER.get(predicted, 0):
                    predicted = decision
        workflow_id = str(context.get("workflow_id") or "")
        bucket = (
            int(_hash(f"{policy['policy_id']}:{workflow_id}")[:8], 16) % 10000 / 100
        )
        in_rollout = bucket < float(policy["rollout_percent"])
        if policy["mode"] == "shadow" or (
            policy["mode"] == "partial" and not in_rollout
        ):
            enforced = "ALLOW"
        else:
            enforced = predicted
        sample_rate = self.adaptive_sample_rate({**context, "decision": predicted})
        decision_id = _id("pdec")
        recorded_versions = {
            "policy_version": str(policy["version"]),
            "verifier_version": "risk-adaptive-v2",
            "model_version": context.get("model_version"),
            "tool_schema_version": context.get("tool_schema_version"),
            "sdk_version": context.get("sdk_version"),
            **(versions or {}),
        }
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_policy_decisions (
                    decision_id, policy_id, user_id, project_id, workflow_id,
                    mode, predicted_decision, enforced_decision, matched_rules_json,
                    risk_score, sample_rate, versions_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    policy["policy_id"],
                    user_id,
                    project_id,
                    workflow_id or None,
                    policy["mode"],
                    predicted,
                    enforced,
                    storage.dumps(matches),
                    _clamp(context.get("risk_score")),
                    sample_rate,
                    storage.dumps(recorded_versions),
                    storage.now_iso(),
                ),
            )
        return {
            "decision_id": decision_id,
            "mode": policy["mode"],
            "predicted_decision": predicted,
            "enforced_decision": enforced,
            "matched_rules": matches,
            "in_rollout": in_rollout,
            "sample_rate": sample_rate,
            "versions": recorded_versions,
        }

    def create_alert_rule(
        self,
        *,
        user_id: str,
        project_id: str | None,
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        rule_id = _id("alert_rule")
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_alert_rules (
                    rule_id, user_id, project_id, name, signal, operator,
                    threshold, severity, destinations_json, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    rule_id,
                    user_id,
                    project_id,
                    str(
                        rule.get("name")
                        or rule.get("signal")
                        or rule.get("metric")
                        or "alert"
                    ),
                    str(rule.get("signal") or rule.get("metric") or "unknown"),
                    str(rule.get("operator") or "gte"),
                    float(rule.get("threshold") or 0),
                    str(rule.get("severity") or "medium"),
                    storage.dumps(rule.get("destinations") or []),
                    storage.now_iso(),
                ),
            )
        return _json_record(
            storage.row(
                "SELECT * FROM reliability_alert_rules WHERE rule_id = ?", (rule_id,)
            )
            or {},
            ("destinations_json",),
        )

    def evaluate_alerts(
        self,
        *,
        user_id: str,
        project_id: str | None,
        signals: dict[str, float],
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        rules = storage.rows(
            """
            SELECT * FROM reliability_alert_rules
            WHERE user_id = ? AND COALESCE(project_id, '') = ? AND active = 1
            """,
            (user_id, project_id or ""),
        )
        created = []
        with storage.transaction() as db:
            for rule in rules:
                if rule["signal"] not in signals:
                    continue
                value = float(signals[rule["signal"]])
                if not _matches(value, rule["operator"], float(rule["threshold"])):
                    continue
                alert_id = _id("alert")
                db.execute(
                    """
                    INSERT INTO reliability_alerts (
                        alert_id, rule_id, user_id, project_id, signal,
                        observed_value, severity, status, context_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                    """,
                    (
                        alert_id,
                        rule["rule_id"],
                        user_id,
                        project_id,
                        rule["signal"],
                        value,
                        rule["severity"],
                        storage.dumps(self._redact(context or {})),
                        storage.now_iso(),
                    ),
                )
                created.append(
                    {
                        "alert_id": alert_id,
                        "signal": rule["signal"],
                        "severity": rule["severity"],
                    }
                )
        return created

    def create_incident_from_cluster(
        self, *, user_id: str, cluster_id: str
    ) -> dict[str, Any]:
        cluster = storage.row(
            "SELECT * FROM reliability_failure_clusters WHERE cluster_id = ? AND user_id = ?",
            (cluster_id, user_id),
        )
        if cluster is None:
            raise ReliabilityPlatformError("Failure cluster was not found.")
        existing = storage.row(
            """SELECT * FROM reliability_incidents
               WHERE user_id = ? AND root_signal = ? AND status <> 'resolved'""",
            (user_id, cluster["signature"]),
        )
        now = storage.now_iso()
        with storage.transaction(immediate=True) as db:
            if existing:
                incident_id = existing["incident_id"]
                db.execute(
                    """UPDATE reliability_incidents SET affected_workflows = ?,
                       last_seen_at = ? WHERE incident_id = ?""",
                    (cluster["workflow_count"], now, incident_id),
                )
            else:
                incident_id = _id("incident")
                db.execute(
                    """
                    INSERT INTO reliability_incidents (
                        incident_id, user_id, project_id, title, root_signal,
                        likely_cause, severity, status, affected_workflows,
                        affected_customers, first_seen_at, last_seen_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, 1, ?, ?, ?)
                    """,
                    (
                        incident_id,
                        user_id,
                        cluster["project_id"],
                        f"Repeated {cluster['failure_type']} failures",
                        cluster["signature"],
                        f"{cluster['provider'] or 'unknown provider'} / {cluster['tool_name'] or 'unknown tool'}",
                        "high" if int(cluster["workflow_count"]) >= 10 else "medium",
                        cluster["workflow_count"],
                        cluster["first_seen_at"],
                        now,
                        storage.dumps({"cluster_id": cluster_id}),
                    ),
                )
        return _json_record(
            storage.row(
                "SELECT * FROM reliability_incidents WHERE incident_id = ?",
                (incident_id,),
            )
            or {},
            ("metadata_json",),
        )

    def replay_trace(
        self,
        *,
        user_id: str,
        project_id: str | None,
        trace_id: str,
        versions: dict[str, str],
    ) -> dict[str, Any]:
        observations = self.query_observations(
            user_id=user_id, trace_id=trace_id, limit=1000
        )
        if not observations:
            raise ReliabilityPlatformError("Trace was not found.")
        result = {
            "events": len(observations),
            "failures": sum(
                item["status"] in {"error", "failed"} for item in observations
            ),
            "decisions": Counter(
                item.get("decision") or "NONE" for item in observations
            ),
            "external_effects_executed": 0,
            "simulation_mode": True,
        }
        replay_id = _id("replay")
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_replay_runs (
                    replay_id, user_id, project_id, source_trace_id,
                    model_version, prompt_version, policy_version,
                    verifier_version, tool_schema_version, simulation_only,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    replay_id,
                    user_id,
                    project_id,
                    trace_id,
                    versions.get("model"),
                    versions.get("prompt"),
                    versions.get("policy"),
                    versions.get("verifier"),
                    versions.get("tool_schema"),
                    storage.dumps(result),
                    storage.now_iso(),
                ),
            )
        return {"replay_id": replay_id, **result}

    def calibrate_components(
        self, *, user_id: str, project_id: str | None, component_type: str
    ) -> list[dict[str, Any]]:
        column = {
            "tool": "tool_name",
            "model": "model",
            "provider": "provider",
            "agent": "agent_id",
        }.get(component_type)
        if column is None:
            raise ReliabilityPlatformError("Unsupported component type.")
        records = storage.rows(
            f"""
            SELECT {column} AS component_name,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status IN ('ok', 'success', 'completed') THEN 1 ELSE 0 END) AS successes,
                   SUM(CASE WHEN status IN ('error', 'failed') THEN 1 ELSE 0 END) AS failures
            FROM reliability_observations
            WHERE user_id = ? AND COALESCE(project_id, '') = ? AND {column} IS NOT NULL
            GROUP BY {column}
            """,
            (user_id, project_id or ""),
        )
        output = []
        with storage.transaction() as db:
            for item in records:
                total = int(item["total"])
                successes = int(item["successes"] or 0)
                failures = int(item["failures"] or 0)
                reliability = (successes + 1) / (total + 2)
                confidence = 1 - math.exp(-total / 20)
                calibration_id = _id("cal")
                db.execute(
                    """
                    INSERT INTO reliability_component_calibration (
                        calibration_id, user_id, project_id, component_type,
                        component_name, total_events, successes, failures,
                        false_positives, false_negatives, reliability,
                        confidence, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
                    """,
                    (
                        calibration_id,
                        user_id,
                        project_id,
                        component_type,
                        item["component_name"],
                        total,
                        successes,
                        failures,
                        reliability,
                        confidence,
                        storage.now_iso(),
                    ),
                )
                output.append(
                    {
                        "component_name": item["component_name"],
                        "reliability": round(reliability, 4),
                        "confidence": round(confidence, 4),
                        "total_events": total,
                    }
                )
        return output

    def upsert_goal(
        self,
        *,
        user_id: str,
        project_id: str | None,
        workflow_id: str,
        original_goal: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        goal_hash = _hash(original_goal)
        current_goal = str(state.get("current_goal") or original_goal)
        original_tokens = set(re.findall(r"\w+", original_goal.lower()))
        current_tokens = set(re.findall(r"\w+", current_goal.lower()))
        overlap = len(original_tokens & current_tokens) / max(
            1, len(original_tokens | current_tokens)
        )
        drift = round(1 - overlap, 4)
        status = "blocked" if drift >= 0.75 else "review" if drift >= 0.5 else "active"
        now = storage.now_iso()
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_workflow_goals (
                    goal_id, user_id, project_id, workflow_id, original_goal,
                    goal_hash, current_plan_json, completed_milestones_json,
                    verified_milestones_json, remaining_milestones_json,
                    context_degradation, goal_drift_score, budget_json,
                    cumulative_risk, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, workflow_id) DO UPDATE SET
                    current_plan_json = excluded.current_plan_json,
                    completed_milestones_json = excluded.completed_milestones_json,
                    verified_milestones_json = excluded.verified_milestones_json,
                    remaining_milestones_json = excluded.remaining_milestones_json,
                    context_degradation = excluded.context_degradation,
                    goal_drift_score = excluded.goal_drift_score,
                    budget_json = excluded.budget_json,
                    cumulative_risk = excluded.cumulative_risk,
                    status = excluded.status, updated_at = excluded.updated_at
                """,
                (
                    _id("goal"),
                    user_id,
                    project_id,
                    workflow_id,
                    original_goal,
                    goal_hash,
                    storage.dumps(state.get("current_plan") or {}),
                    storage.dumps(state.get("completed_milestones") or []),
                    storage.dumps(state.get("verified_milestones") or []),
                    storage.dumps(state.get("remaining_milestones") or []),
                    _clamp(state.get("context_degradation")),
                    drift,
                    storage.dumps(state.get("budget") or {}),
                    _clamp(state.get("cumulative_risk")),
                    status,
                    now,
                    now,
                ),
            )
        record = (
            storage.row(
                "SELECT * FROM reliability_workflow_goals WHERE user_id = ? AND workflow_id = ?",
                (user_id, workflow_id),
            )
            or {}
        )
        return _json_record(
            record,
            (
                "current_plan_json",
                "completed_milestones_json",
                "verified_milestones_json",
                "remaining_milestones_json",
                "budget_json",
            ),
        )

    def record_subagent(
        self,
        *,
        user_id: str,
        workflow_id: str,
        agent_id: str,
        parent_agent_id: str | None,
        depth: int,
        token_cost: int,
        risk_score: float,
        cancellation_epoch: int,
        status: str,
    ) -> dict[str, Any]:
        now = storage.now_iso()
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_subagent_links (
                    link_id, user_id, workflow_id, parent_agent_id, agent_id,
                    depth, token_cost, risk_score, cancellation_epoch,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, workflow_id, agent_id) DO UPDATE SET
                    parent_agent_id = excluded.parent_agent_id,
                    depth = excluded.depth, token_cost = excluded.token_cost,
                    risk_score = excluded.risk_score,
                    cancellation_epoch = excluded.cancellation_epoch,
                    status = excluded.status, updated_at = excluded.updated_at
                """,
                (
                    _id("agentlink"),
                    user_id,
                    workflow_id,
                    parent_agent_id,
                    agent_id,
                    max(0, depth),
                    max(0, token_cost),
                    _clamp(risk_score),
                    max(0, cancellation_epoch),
                    status,
                    now,
                    now,
                ),
            )
        return self.subagent_tree(user_id=user_id, workflow_id=workflow_id)

    def subagent_tree(self, *, user_id: str, workflow_id: str) -> dict[str, Any]:
        links = storage.rows(
            """SELECT * FROM reliability_subagent_links
               WHERE user_id = ? AND workflow_id = ? ORDER BY depth, created_at""",
            (user_id, workflow_id),
        )
        return {
            "workflow_id": workflow_id,
            "agents": links,
            "total_agents": len(links),
            "total_token_cost": sum(int(link["token_cost"]) for link in links),
            "maximum_depth": max((int(link["depth"]) for link in links), default=0),
            "cumulative_risk": round(
                sum(float(link["risk_score"]) for link in links), 4
            ),
            "cancellation_epoch": max(
                (int(link["cancellation_epoch"]) for link in links), default=0
            ),
        }

    def run_protected_benchmark(
        self,
        *,
        user_id: str,
        project_id: str | None,
        name: str,
        baseline: dict[str, float],
        protected: dict[str, float],
    ) -> dict[str, Any]:
        lower_is_better = {
            "catastrophic_continuation_rate",
            "false_success_rate",
            "duplicate_execution_rate",
            "cost_per_verified_completion",
            "verification_latency_ms",
            "human_interventions",
        }
        higher_is_better = {
            "task_success_rate",
            "safe_recovery_rate",
            "verified_completion_rate",
        }
        metrics = sorted(set(baseline) | set(protected))
        deltas: dict[str, dict[str, Any]] = {}
        for metric in metrics:
            before = float(baseline.get(metric) or 0)
            after = float(protected.get(metric) or 0)
            if metric in lower_is_better:
                improvement = before - after
                passed = after <= before
            elif metric in higher_is_better:
                improvement = after - before
                passed = after >= before
            else:
                improvement = after - before
                passed = True
            deltas[metric] = {
                "baseline": before,
                "protected": after,
                "improvement": round(improvement, 6),
                "passed": passed,
            }
        passed = all(
            item["passed"]
            for metric, item in deltas.items()
            if metric in lower_is_better | higher_is_better
        )
        benchmark_id = _id("bench")
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_protected_benchmarks (
                    benchmark_id, user_id, project_id, name, baseline_json,
                    protected_json, deltas_json, passed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    benchmark_id,
                    user_id,
                    project_id,
                    name,
                    storage.dumps(baseline),
                    storage.dumps(protected),
                    storage.dumps(deltas),
                    int(passed),
                    storage.now_iso(),
                ),
            )
        return {
            "benchmark_id": benchmark_id,
            "name": name,
            "passed": passed,
            "deltas": deltas,
        }

    def promote_cluster_to_dataset(
        self,
        *,
        user_id: str,
        cluster_id: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        cluster = storage.row(
            "SELECT * FROM reliability_failure_clusters WHERE cluster_id = ? AND user_id = ?",
            (cluster_id, user_id),
        )
        if cluster is None:
            raise ReliabilityPlatformError("Failure cluster was not found.")
        dataset = self.create_dataset(
            user_id=user_id,
            project_id=cluster["project_id"],
            name=name or f"Failure regression: {cluster['failure_type']}",
            description="Automatically promoted from a production failure cluster.",
            protected=True,
        )
        members = storage.rows(
            "SELECT * FROM reliability_failure_members WHERE cluster_id = ?",
            (cluster_id,),
        )
        cases = []
        for member in members:
            cases.append(
                self.add_dataset_case(
                    user_id=user_id,
                    dataset_id=dataset["dataset_id"],
                    case={
                        "input": {"workflow_id": member["workflow_id"]},
                        "expected_failure_type": cluster["failure_type"],
                        "risk_score": 1,
                        "correct_decision": "BLOCK",
                        "source_failure_id": member.get("observation_id") or cluster_id,
                    },
                )
            )
        return {"dataset": dataset, "case_count": len(cases), "cases": cases}

    def infer_root_cause(
        self,
        *,
        user_id: str,
        project_id: str | None,
        trace_id: str,
    ) -> dict[str, Any]:
        observations = list(
            reversed(
                self.query_observations(
                    user_id=user_id,
                    project_id=project_id,
                    trace_id=trace_id,
                    limit=1000,
                )
            )
        )
        failures = [
            item
            for item in observations
            if item.get("status") in {"error", "failed", "blocked"}
            or item.get("error_type")
        ]
        if not failures:
            raise ReliabilityPlatformError("Trace has no failure evidence.")
        root = failures[0]
        root_id = str(root["observation_id"])
        created = []
        for index, item in enumerate(observations):
            if item["observation_id"] != root_id:
                continue
            if index > 0:
                prior = observations[index - 1]
                created.append(
                    self.record_causal_edge(
                        user_id=user_id,
                        project_id=project_id,
                        root_failure_id=root_id,
                        cause_id=str(prior["observation_id"]),
                        effect_id=root_id,
                        relation="preceded_and_contributed_to",
                        confidence=0.75,
                        contaminated_outputs=[str(root.get("output_ref") or "")]
                        if root.get("output_ref")
                        else [],
                        external_side_effects=[],
                    )
                )
            for downstream in observations[index + 1 :]:
                created.append(
                    self.record_causal_edge(
                        user_id=user_id,
                        project_id=project_id,
                        root_failure_id=root_id,
                        cause_id=root_id,
                        effect_id=str(downstream["observation_id"]),
                        relation="contaminated_downstream",
                        confidence=0.9,
                        contaminated_outputs=[
                            str(
                                downstream.get("output_ref")
                                or downstream["observation_id"]
                            )
                        ],
                        external_side_effects=[str(downstream["tool_name"])]
                        if downstream.get("tool_name")
                        else [],
                    )
                )
            break
        graph = self.root_cause_graph(user_id=user_id, root_failure_id=root_id)
        graph["inferred"] = True
        graph["source_trace_id"] = trace_id
        graph["created_edges"] = len(created)
        return graph

    def create_service_account(
        self,
        *,
        user_id: str,
        project_id: str | None,
        name: str,
        scopes: list[str],
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_scopes = sorted({str(scope).strip() for scope in scopes if scope})
        if not normalized_scopes:
            raise ReliabilityPlatformError("At least one scope is required.")
        account_id = _id("svc")
        now = storage.now_iso()
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_service_accounts (
                    account_id, user_id, project_id, name, scopes_json,
                    active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    account_id,
                    user_id,
                    project_id,
                    name,
                    storage.dumps(normalized_scopes),
                    now,
                    now,
                ),
            )
        return self.rotate_service_account_key(
            user_id=user_id, account_id=account_id, expires_at=expires_at
        )

    def rotate_service_account_key(
        self,
        *,
        user_id: str,
        account_id: str,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        account = storage.row(
            "SELECT * FROM reliability_service_accounts WHERE account_id = ? AND user_id = ? AND active = 1",
            (account_id, user_id),
        )
        if account is None:
            raise ReliabilityPlatformError("Active service account was not found.")
        raw_key = f"mtrx_sa_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        key_id = _id("skey")
        with storage.transaction(immediate=True) as db:
            db.execute(
                "UPDATE reliability_service_account_keys SET active = 0 WHERE account_id = ?",
                (account_id,),
            )
            db.execute(
                """
                INSERT INTO reliability_service_account_keys (
                    key_id, account_id, key_hash, key_prefix, scopes_json,
                    expires_at, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    key_id,
                    account_id,
                    key_hash,
                    raw_key[:16],
                    account["scopes_json"],
                    expires_at,
                    storage.now_iso(),
                ),
            )
        return {
            "account_id": account_id,
            "key_id": key_id,
            "name": account["name"],
            "project_id": account["project_id"],
            "scopes": storage.loads(account["scopes_json"], []),
            "api_key": raw_key,
            "key_prefix": raw_key[:16],
            "expires_at": expires_at,
            "message": "Copy this key now. It is stored only as a hash.",
        }

    def authenticate_service_key(
        self, *, raw_key: str, required_scope: str
    ) -> dict[str, Any]:
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        record = storage.row(
            """
            SELECT k.*, a.user_id, a.project_id, a.name
            FROM reliability_service_account_keys AS k
            JOIN reliability_service_accounts AS a ON a.account_id = k.account_id
            WHERE k.key_hash = ? AND k.active = 1 AND a.active = 1
              AND (k.expires_at IS NULL OR k.expires_at > ?)
            """,
            (key_hash, storage.now_iso()),
        )
        if record is None:
            raise ReliabilityPlatformError("Invalid or expired service-account key.")
        scopes = storage.loads(record["scopes_json"], [])
        if required_scope not in scopes and "*" not in scopes:
            raise ReliabilityPlatformError(
                f"Service account lacks required scope: {required_scope}."
            )
        with storage.transaction() as db:
            db.execute(
                "UPDATE reliability_service_account_keys SET last_used_at = ? WHERE key_id = ?",
                (storage.now_iso(), record["key_id"]),
            )
        return {
            "api_key_id": record["key_id"],
            "service_account_id": record["account_id"],
            "user_id": record["user_id"],
            "project_id": record["project_id"],
            "project_name": record["name"],
            "scopes": scopes,
        }

    def delete_tenant_data(
        self,
        *,
        user_id: str,
        project_id: str | None,
        confirmation: str,
    ) -> dict[str, Any]:
        if confirmation != "DELETE":
            raise ReliabilityPlatformError("Deletion confirmation must equal DELETE.")
        direct_tables = (
            "reliability_observations",
            "reliability_tool_contracts",
            "reliability_evidence",
            "reliability_checkpoints",
            "reliability_sagas",
            "reliability_datasets",
            "reliability_experiments",
            "reliability_annotations",
            "reliability_failure_clusters",
            "reliability_drift_reports",
            "reliability_causal_edges",
            "reliability_policies",
            "reliability_policy_decisions",
            "reliability_alert_rules",
            "reliability_alerts",
            "reliability_incidents",
            "reliability_component_calibration",
            "reliability_replay_runs",
            "reliability_workflow_goals",
            "reliability_protected_benchmarks",
            "reliability_service_accounts",
            "reliability_tenant_controls",
            "reliability_admission_windows",
        )
        deleted: dict[str, int] = {}
        with storage.transaction(immediate=True) as db:
            for table in direct_tables:
                if project_id is None:
                    cursor = db.execute(
                        f"DELETE FROM {table} WHERE user_id = ?", (user_id,)
                    )
                else:
                    cursor = db.execute(
                        f"DELETE FROM {table} WHERE user_id = ? AND COALESCE(project_id, '') = ?",
                        (user_id, project_id),
                    )
                deleted[table] = max(0, int(cursor.rowcount or 0))
            deletion_id = _id("delete")
            db.execute(
                """
                INSERT INTO reliability_deletion_audit (
                    deletion_id, subject_hash, project_hash,
                    deleted_counts_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    deletion_id,
                    _hash(user_id),
                    _hash(project_id) if project_id else None,
                    storage.dumps(deleted),
                    storage.now_iso(),
                ),
            )
        return {"deletion_id": deletion_id, "deleted": deleted, "irreversible": True}

    def set_tenant_controls(
        self,
        *,
        user_id: str,
        project_id: str | None,
        controls: dict[str, Any],
    ) -> dict[str, Any]:
        with storage.transaction() as db:
            db.execute(
                """
                INSERT INTO reliability_tenant_controls (
                    user_id, project_id, max_requests_per_minute,
                    max_active_workflows, max_queue_depth, max_monthly_tokens,
                    retention_days, region, encryption_key_ref, sso_config_json,
                    backup_verified_at, metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, project_id) DO UPDATE SET
                    max_requests_per_minute = excluded.max_requests_per_minute,
                    max_active_workflows = excluded.max_active_workflows,
                    max_queue_depth = excluded.max_queue_depth,
                    max_monthly_tokens = excluded.max_monthly_tokens,
                    retention_days = excluded.retention_days,
                    region = excluded.region,
                    encryption_key_ref = excluded.encryption_key_ref,
                    sso_config_json = excluded.sso_config_json,
                    backup_verified_at = excluded.backup_verified_at,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    project_id,
                    max(1, int(controls.get("max_requests_per_minute") or 600)),
                    max(1, int(controls.get("max_active_workflows") or 100)),
                    max(1, int(controls.get("max_queue_depth") or 10000)),
                    max(1, int(controls.get("max_monthly_tokens") or 10000000)),
                    max(1, int(controls.get("retention_days") or 90)),
                    str(controls.get("region") or "auto"),
                    controls.get("encryption_key_ref"),
                    storage.dumps(controls.get("sso_config") or {}),
                    controls.get("backup_verified_at"),
                    storage.dumps(self._redact(controls.get("metadata") or {})),
                    storage.now_iso(),
                ),
            )
        return _json_record(
            storage.row(
                """SELECT * FROM reliability_tenant_controls
                   WHERE user_id = ? AND COALESCE(project_id, '') = ?""",
                (user_id, project_id or ""),
            )
            or {},
            ("sso_config_json", "metadata_json"),
        )

    def retention_cleanup(
        self, *, user_id: str, project_id: str | None
    ) -> dict[str, Any]:
        controls = storage.row(
            """SELECT * FROM reliability_tenant_controls
               WHERE user_id = ? AND COALESCE(project_id, '') = ?""",
            (user_id, project_id or ""),
        )
        days = int(controls["retention_days"] if controls else 90)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        deleted: dict[str, int] = {}
        with storage.transaction(immediate=True) as db:
            for table, timestamp in (
                ("reliability_observations", "created_at"),
                ("reliability_alerts", "created_at"),
                ("reliability_replay_runs", "created_at"),
                ("reliability_drift_reports", "created_at"),
            ):
                cursor = db.execute(
                    f"""DELETE FROM {table} WHERE user_id = ?
                        AND COALESCE(project_id, '') = ? AND {timestamp} < ?""",
                    (user_id, project_id or "", cutoff),
                )
                deleted[table] = cursor.rowcount
        return {"retention_days": days, "cutoff": cutoff, "deleted": deleted}

    def audit_export(self, *, user_id: str, project_id: str | None) -> dict[str, Any]:
        observations = self.query_observations(
            user_id=user_id, project_id=project_id, limit=1000
        )
        decisions = storage.rows(
            """SELECT * FROM reliability_policy_decisions
               WHERE user_id = ? AND COALESCE(project_id, '') = ?
               ORDER BY created_at DESC LIMIT 1000""",
            (user_id, project_id or ""),
        )
        incidents = storage.rows(
            """SELECT * FROM reliability_incidents
               WHERE user_id = ? AND COALESCE(project_id, '') = ?
               ORDER BY last_seen_at DESC LIMIT 1000""",
            (user_id, project_id or ""),
        )
        export = {
            "exported_at": storage.now_iso(),
            "user_id": user_id,
            "project_id": project_id,
            "observations": observations,
            "policy_decisions": [
                _json_record(item, ("matched_rules_json", "versions_json"))
                for item in decisions
            ],
            "incidents": [_json_record(item, ("metadata_json",)) for item in incidents],
        }
        export["sha256"] = _hash(export)
        return export


__all__ = [
    "EVALUATORS",
    "FRAMEWORKS",
    "AdmissionRejected",
    "ReliabilityPlatform",
    "ReliabilityPlatformError",
]
