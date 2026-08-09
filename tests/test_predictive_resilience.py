from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ai_execution.service import AIExecutionService, create_plan
from reliability_platform import storage
from reliability_platform.core import ReliabilityPlatform, ReliabilityPlatformError
from reliability_platform.notifications import ReliabilityNotificationDispatcher


@pytest.fixture()
def platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ReliabilityPlatform:
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "predictive-resilience.db")
    storage._INITIALIZED.clear()
    return ReliabilityPlatform(notifier=ReliabilityNotificationDispatcher())


def test_legacy_schema_is_migrated_and_connection_is_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as db:
        db.executescript(
            """
            CREATE TABLE reliability_alerts (
                alert_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                project_id TEXT, status TEXT, severity TEXT, created_at TEXT
            );
            CREATE TABLE reliability_incidents (
                incident_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                project_id TEXT, status TEXT, last_seen_at TEXT
            );
            CREATE TABLE reliability_annotations (
                annotation_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                project_id TEXT, status TEXT, queue_reason TEXT, created_at TEXT
            );
            """
        )
    monkeypatch.setattr(storage, "DB_PATH", database)
    storage._INITIALIZED.clear()
    storage.initialize()
    expected = {
        "reliability_alerts": {"repeat_count", "acknowledged_at", "resolution"},
        "reliability_incidents": {
            "acknowledged_at",
            "resolution",
            "regression_dataset_id",
        },
        "reliability_annotations": {
            "evidence_bundle_json",
            "permissions_json",
            "action_taken",
        },
    }
    db = storage.connect()
    try:
        for table, wanted in expected.items():
            columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
            assert wanted <= columns
    finally:
        db.close()


def _failure(
    platform: ReliabilityPlatform,
    index: int,
    *,
    provider: str = "provider-a",
    project_id: str = "project-1",
) -> None:
    platform.ingest_observation(
        user_id="user-1",
        project_id=project_id,
        force_sample=True,
        observation={
            "observation_id": f"failure-{provider}-{index}",
            "trace_id": f"trace-{index}",
            "span_id": f"span-{index}",
            "workflow_id": f"workflow-{index}",
            "status": "failed",
            "error_type": "provider_timeout",
            "provider": provider,
            "tool_name": "send",
            "latency_ms": 1700,
            "token_cost": 900,
            "evidence_strength": 0.1,
            "metadata": {
                "retry_count": 2,
                "queue_delay_ms": 800,
                "fallback_used": index % 2 == 0,
            },
        },
    )


def test_predictive_health_opens_circuit_and_slo_reports_burn(
    platform: ReliabilityPlatform,
) -> None:
    platform.create_alert_rule(
        user_id="user-1",
        project_id="project-1",
        rule={
            "name": "predicted failure",
            "signal": "failure_probability",
            "operator": "gte",
            "threshold": 0.7,
            "severity": "critical",
            "destinations": ["dashboard"],
        },
    )
    for index in range(8):
        _failure(platform, index)

    health = platform.predict_health(
        user_id="user-1",
        project_id="project-1",
        component_type="provider",
        component_name="provider-a",
        window_minutes=10,
    )
    assert health["health_state"] == "critical"
    assert health["failure_probability"] >= 0.75
    assert health["preventative_action"]["action"] == "opened"
    assert health["alerts"][0]["deliveries"][0]["status"] == "delivered"

    platform.create_slo(
        user_id="user-1",
        project_id="project-1",
        name="false-success escape rate",
        metric="false_success_rate",
        operator="lt",
        target=0.001,
        window_minutes=60,
        severity="critical",
    )
    result = platform.evaluate_slos(
        user_id="user-1",
        project_id="project-1",
        metrics={"false_success_rate": 0.01},
    )
    assert result["health_state"] == "critical"
    assert result["evaluations"][0]["burn_rate"] == 10


def test_circuit_breaker_fallback_probe_and_close(
    platform: ReliabilityPlatform,
) -> None:
    circuit = platform.configure_circuit(
        user_id="user-1",
        project_id="project-1",
        dependency_type="provider",
        dependency_name="provider-primary",
        config={
            "minimum_calls": 2,
            "consecutive_failure_limit": 2,
            "failure_threshold": 0.5,
            "cooldown_seconds": 5,
            "fallback_chain": ["provider-backup"],
        },
    )
    for _ in range(2):
        circuit = platform.record_dependency_result(
            user_id="user-1",
            circuit_id=circuit["circuit_id"],
            success=False,
            error_type="provider_timeout",
        )
    assert circuit["state"] == "open"
    routing = platform.before_dependency_call(
        user_id="user-1",
        project_id="project-1",
        dependency_type="provider",
        dependency_name="provider-primary",
    )
    assert routing["decision"] == "FALLBACK"
    assert routing["selected_dependency"] == "provider-backup"

    with storage.transaction() as db:
        db.execute(
            "UPDATE reliability_circuit_breakers SET probe_after = ? WHERE circuit_id = ?",
            ("2000-01-01T00:00:00+00:00", circuit["circuit_id"]),
        )
    probe = platform.before_dependency_call(
        user_id="user-1",
        project_id="project-1",
        dependency_type="provider",
        dependency_name="provider-primary",
    )
    assert probe["decision"] == "PROBE"
    concurrent = platform.before_dependency_call(
        user_id="user-1",
        project_id="project-1",
        dependency_type="provider",
        dependency_name="provider-primary",
    )
    assert concurrent["decision"] == "FALLBACK"
    assert concurrent["circuit_state"] == "half_open"
    closed = platform.record_dependency_result(
        user_id="user-1",
        circuit_id=circuit["circuit_id"],
        success=True,
        latency_ms=40,
    )
    assert closed["state"] == "closed"


def test_verified_recovery_and_human_review_permissions(
    platform: ReliabilityPlatform,
) -> None:
    recovery = platform.verify_recovery(
        user_id="user-1",
        project_id="project-1",
        workflow_id="workflow-1",
        failure_type="provider_outage",
        attempt=1,
        strategy="fallback_provider",
        before_state={"ok": False, "provider": "a"},
        after_state={"ok": True, "provider": "b", "tainted": False},
        independent_evidence={"verified": True, "receipt": "receipt-1"},
        expected_state={"ok": True},
    )
    assert recovery["verified"] is True
    assert recovery["decision"] == "ALLOW"
    exhausted = platform.recovery_plan("provider_timeout", attempt=4)
    assert exhausted["retryable"] is False
    assert exhausted["exhausted"] is True
    assert exhausted["decision"] == "REVIEW"

    review = platform.enqueue_human_review(
        user_id="user-1",
        project_id="project-1",
        workflow_id="refund-agent",
        reason="Transaction may have succeeded.",
        evidence_bundle={
            "agent_claim": "refund failed",
            "external_evidence": "transaction unknown",
            "risk": "S4 critical",
        },
        permissions=["confirm_state", "approve_compensation", "terminate"],
        recommended_action="confirm_state",
    )
    with pytest.raises(ReliabilityPlatformError):
        platform.decide_human_review(
            user_id="user-1",
            review_id=review["annotation_id"],
            reviewer="reviewer-1",
            action="resume",
        )
    decided = platform.decide_human_review(
        user_id="user-1",
        review_id=review["annotation_id"],
        reviewer="reviewer-1",
        action="terminate",
        notes="External state remains unknown.",
    )
    assert decided["status"] == "completed"
    assert decided["action_taken"] == "terminate"
    assert decided["workflow_directive"]["terminate"] is True


def test_incident_lifecycle_notifications_and_automatic_regression(
    platform: ReliabilityPlatform,
) -> None:
    for index in range(3):
        _failure(platform, index, provider="provider-incident")
    incident = storage.row(
        "SELECT * FROM reliability_incidents WHERE user_id = ?", ("user-1",)
    )
    assert incident is not None
    details = platform.get_incident(
        user_id="user-1", incident_id=incident["incident_id"]
    )
    assert details["regression_dataset_id"]
    assert len(details["members"]) == 3
    assert details["deliveries"][0]["status"] == "delivered"

    for index in range(3, 6):
        _failure(
            platform,
            index,
            provider="provider-incident",
            project_id="project-2",
        )
    incidents = storage.rows(
        "SELECT * FROM reliability_incidents WHERE user_id = ?",
        ("user-1",),
    )
    assert len(incidents) == 2

    acknowledged = platform.transition_incident(
        user_id="user-1",
        incident_id=incident["incident_id"],
        action="acknowledge",
        actor="on-call",
    )
    assert acknowledged["status"] == "investigating"
    resolved = platform.transition_incident(
        user_id="user-1",
        incident_id=incident["incident_id"],
        action="resolve",
        actor="on-call",
        resolution="Provider credentials rotated and verified.",
    )
    assert resolved["status"] == "resolved"
    cases = storage.rows(
        "SELECT * FROM reliability_dataset_cases WHERE dataset_id = ?",
        (resolved["regression_dataset_id"],),
    )
    assert len(cases) == 3


def test_alert_deduplication_acknowledgement_and_resolution(
    platform: ReliabilityPlatform,
) -> None:
    platform.create_alert_rule(
        user_id="user-1",
        project_id="project-1",
        rule={
            "name": "timeouts",
            "metric": "timeout_rate",
            "operator": "gte",
            "threshold": 0.2,
            "severity": "high",
            "destinations": ["dashboard"],
        },
    )
    first = platform.evaluate_alerts(
        user_id="user-1",
        project_id="project-1",
        signals={"timeout_rate": 0.4},
    )[0]
    second = platform.evaluate_alerts(
        user_id="user-1",
        project_id="project-1",
        signals={"timeout_rate": 0.5},
    )[0]
    assert second["alert_id"] == first["alert_id"]
    assert second["repeat_count"] == 2
    acknowledged = platform.transition_alert(
        user_id="user-1",
        alert_id=first["alert_id"],
        action="acknowledge",
        actor="on-call",
    )
    assert acknowledged["status"] == "acknowledged"
    repeated = platform.evaluate_alerts(
        user_id="user-1",
        project_id="project-1",
        signals={"timeout_rate": 0.6},
    )[0]
    assert repeated["alert_id"] == first["alert_id"]
    assert repeated["repeat_count"] == 3
    resolved = platform.transition_alert(
        user_id="user-1",
        alert_id=first["alert_id"],
        action="resolve",
        actor="on-call",
        resolution="Provider recovered.",
    )
    assert resolved["status"] == "resolved"


def test_execution_engine_uses_only_explicit_safe_fallbacks(
    platform: ReliabilityPlatform,
) -> None:
    calls: list[str] = []

    def execute_tool(_user_id: str, tool: str, *_args, **_kwargs):
        calls.append(tool)
        if tool == "PRIMARY_TOOL":
            raise TimeoutError("provider timeout")
        return {"ok": True, "data": {"receipt": "backup-1"}}

    service = AIExecutionService(
        get_integrations=lambda _user_id: {},
        get_tool_context=lambda _user_id: {},
        execute_tool=execute_tool,
        search_memory=lambda _user_id, _query: [],
        supabase_health=lambda: {"ok": True},
        redis_health=lambda: {"ok": True},
        set_temporary_state=lambda *_args: True,
        get_temporary_state=lambda *_args: None,
        capture_error=lambda *_args, **_kwargs: None,
        redact=lambda value: value,
        scrub=lambda value: value,
        control_plane=object(),
        reliability_platform=platform,
    )
    plan = create_plan(
        "Run the external action",
        {
            "intent": "external_tool_action",
            "target_app": "provider",
            "tool_slug": "PRIMARY_TOOL",
            "fallback_tools": ["BACKUP_TOOL"],
            "fallback_safe": True,
            "idempotent": True,
        },
    )
    assert plan["proposed_actions"][0]["fallback_tools"] == ["BACKUP_TOOL"]
    result = service._execute_action(
        {
            "user_id": "user-1",
            "request_id": "request-1",
            "workflow_id": "workflow-1",
            "request_text": "Run the external action",
            "plan": plan,
            "metadata": {"project_id": "project-1"},
        }
    )
    assert calls == ["PRIMARY_TOOL", "BACKUP_TOOL"]
    assert result["ok"] is True
    assert result["fallback_used"] is True
    assert result["selected_tool"] == "BACKUP_TOOL"
    assert result["recovery"]["verified"] is True


def test_notification_delivery_disables_redirects_and_records_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Response:
        status_code = 202

    def post(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setenv(
        "SOFTWARE_ALERT_SLACK_WEBHOOK_URL", "https://hooks.example.com/incident"
    )
    monkeypatch.setattr(
        ReliabilityNotificationDispatcher,
        "_safe_endpoint",
        staticmethod(lambda _url: True),
    )
    monkeypatch.setattr("reliability_platform.notifications.requests.post", post)
    dispatcher = ReliabilityNotificationDispatcher()
    deliveries = dispatcher.deliver(
        ["slack"],
        {"summary": "Provider degraded", "incident_id": "incident-1"},
    )
    assert deliveries[0]["status"] == "delivered"
    assert deliveries[0]["response_code"] == 202
    assert captured["allow_redirects"] is False
    assert captured["timeout"] == 5
