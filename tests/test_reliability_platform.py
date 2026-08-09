from __future__ import annotations

from pathlib import Path

import pytest

from reliability_platform import storage
from reliability_platform.adapters import (
    normalize_framework_event,
    normalize_openinference,
    normalize_otlp,
)
from reliability_platform.core import AdmissionRejected, ReliabilityPlatform


@pytest.fixture()
def platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ReliabilityPlatform:
    database = tmp_path / "reliability-platform.db"
    monkeypatch.setattr(storage, "DB_PATH", database)
    storage._INITIALIZED.clear()
    return ReliabilityPlatform()


def test_observation_redaction_sampling_search_and_incident(
    platform: ReliabilityPlatform,
) -> None:
    base = {
        "trace_id": "trace-1",
        "workflow_id": "workflow-1",
        "status": "failed",
        "risk_score": 0.9,
        "error_type": "timeout",
        "provider": "demo",
        "tool_name": "send",
        "metadata": {"api_key": "secret", "email": "person@example.com"},
    }
    for index in range(3):
        result = platform.ingest_observation(
            user_id="user-1",
            project_id="project-1",
            observation={**base, "observation_id": f"obs-{index}"},
        )
        assert result["sampled"] is True

    observations = platform.query_observations(user_id="user-1", trace_id="trace-1")
    assert len(observations) == 3
    assert "api_key" not in observations[0]["metadata"]
    assert observations[0]["metadata"]["email"].startswith("***")
    incident = storage.row(
        "SELECT * FROM reliability_incidents WHERE user_id = ?", ("user-1",)
    )
    assert incident is not None


def test_telemetry_and_framework_normalizers() -> None:
    otlp = normalize_otlp(
        {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "t1",
                                    "spanId": "s1",
                                    "name": "agent.run",
                                    "status": {"code": 2},
                                    "attributes": [
                                        {
                                            "key": "gen_ai.request.model",
                                            "value": {"stringValue": "m1"},
                                        }
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    )
    assert otlp[0]["trace_id"] == "t1"
    assert otlp[0]["model"] == "m1"
    assert otlp[0]["status"] == "error"

    oi = normalize_openinference(
        {"trace_id": "t2", "span_id": "s2", "span_kind": "TOOL", "status": "OK"}
    )
    assert oi[0]["type"] == "TOOL"
    framework = normalize_framework_event(
        "langchain",
        {"run_id": "r1", "event": "on_tool_end", "name": "search"},
    )
    assert framework["framework"] == "langchain"
    assert framework["type"] == "on_tool_end"
    assert framework["name"] == "search"


def test_tool_contract_postcondition_and_taint(platform: ReliabilityPlatform) -> None:
    contract = platform.register_tool_contract(
        user_id="user-1",
        project_id="project-1",
        contract={
            "tool_name": "send_email",
            "input_schema": {
                "type": "object",
                "required": ["to"],
                "properties": {"to": {"type": "string"}},
            },
            "output_schema": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "string"}},
            },
            "permissions": ["email.send"],
            "human_confirmation_required": True,
            "expected_state_changes": [
                {"path": "id", "operator": "eq", "value": "message-1"}
            ],
        },
    )
    assert contract["version"] == 1
    denied = platform.validate_tool_action(
        user_id="user-1",
        project_id="project-1",
        tool_name="send_email",
        arguments={},
        permissions=[],
    )
    assert denied["passed"] is False
    allowed = platform.validate_tool_action(
        user_id="user-1",
        project_id="project-1",
        tool_name="send_email",
        arguments={"to": "person@example.com"},
        permissions=["email.send"],
        confirmed=True,
    )
    assert allowed["passed"] is True
    verified = platform.verify_postcondition(
        user_id="user-1",
        project_id="project-1",
        tool_name="send_email",
        observed_result={"id": "message-1"},
        independent_readback={"id": "message-1"},
    )
    assert verified["passed"] is True

    root = platform.record_evidence(
        user_id="user-1",
        project_id="project-1",
        workflow_id="workflow-1",
        evidence={"payload": {"value": 1}, "taint_status": "tainted"},
    )
    child = platform.record_evidence(
        user_id="user-1",
        project_id="project-1",
        workflow_id="workflow-1",
        evidence={"payload": {"value": 2}, "derived_from": [root["evidence_id"]]},
    )
    assert child["taint_status"] == "tainted"
    assert (
        platform.workflow_taint_state(user_id="user-1", workflow_id="workflow-1")[
            "tainted"
        ]
        is True
    )
    platform.reverify_evidence(
        user_id="user-1",
        evidence_id=root["evidence_id"],
        verifier="independent-verifier",
        independent=True,
        passed=True,
    )


def test_checkpoints_recovery_and_saga(platform: ReliabilityPlatform) -> None:
    evidence = platform.record_evidence(
        user_id="user-1",
        project_id=None,
        workflow_id="workflow-1",
        evidence={"payload": {"receipt": "r1"}, "trust_level": "trusted"},
    )
    checkpoint = platform.create_checkpoint(
        user_id="user-1",
        project_id=None,
        workflow_id="workflow-1",
        checkpoint={
            "state": {"step": 1},
            "verified": True,
            "verified_evidence_ids": [evidence["evidence_id"]],
        },
    )
    restored = platform.restore_checkpoint(user_id="user-1", workflow_id="workflow-1")
    assert restored["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert platform.recovery_plan("rate_limit", 2)["strategy"] == "exponential_delay"

    saga = platform.create_saga(
        user_id="user-1",
        project_id=None,
        workflow_id="workflow-1",
        steps=[
            {"name": "reserve", "compensation": {"tool": "release"}},
            {"name": "charge", "compensation": {"tool": "refund"}},
        ],
    )
    platform.complete_saga_step(
        user_id="user-1",
        saga_id=saga["saga_id"],
        sequence=1,
        receipt={"id": "reservation-1"},
        success=True,
    )
    plan = platform.compensation_plan(user_id="user-1", saga_id=saga["saga_id"])
    assert plan["compensations"][0]["action"] == {"tool": "release"}


def test_datasets_experiments_ci_annotations_and_drift(
    platform: ReliabilityPlatform,
) -> None:
    dataset = platform.create_dataset(
        user_id="user-1", project_id="project-1", name="regressions"
    )
    platform.add_dataset_case(
        user_id="user-1",
        dataset_id=dataset["dataset_id"],
        case={"expected_output": {"completed": True}},
    )
    experiment = platform.run_experiment(
        user_id="user-1",
        project_id="project-1",
        name="candidate-1",
        dataset_id=dataset["dataset_id"],
        control={"default_result": {"completed": False}},
        candidate={"default_result": {"completed": True}},
        evaluators=["task_completion"],
    )
    assert experiment["metrics"]["candidate_delta"] == 1.0
    assert (
        platform.ci_gate(
            {
                "false_negative_rate": 0,
                "critical_actions_verified": 1,
                "reliability_regression": 0,
                "p95_verification_ms": 20,
                "duplicate_executions": 0,
            }
        )["passed"]
        is True
    )

    queued = platform.enqueue_annotation(
        user_id="user-1", project_id="project-1", reason="uncertain"
    )
    completed = platform.complete_annotation(
        user_id="user-1",
        annotation_id=queued["annotation_id"],
        reviewer="reviewer-1",
        label="true_positive",
        confidence=0.95,
    )
    assert completed["status"] == "completed"
    drift = platform.detect_drift(
        user_id="user-1",
        project_id="project-1",
        component_type="model",
        component_name="model-1",
        baseline={"failure_rate": 0.1},
        current={"failure_rate": 0.4},
    )
    assert drift["drift_score"] > 0


def test_policy_alert_replay_calibration_goals_and_subagents(
    platform: ReliabilityPlatform,
) -> None:
    policy = platform.create_policy(
        user_id="user-1",
        project_id="project-1",
        name="critical-actions",
        mode="enforce",
        rollout_percent=100,
        rules=[
            {
                "field": "risk_score",
                "operator": "gte",
                "value": 0.8,
                "decision": "REVIEW",
            }
        ],
        tenant_overrides={},
    )
    decision = platform.evaluate_policy(
        user_id="user-1",
        project_id="project-1",
        policy_name=policy["name"],
        context={"risk_score": 0.9, "workflow_id": "workflow-1"},
        versions={"model": "m1", "prompt": "p1"},
    )
    assert decision["enforced_decision"] == "REVIEW"

    platform.create_alert_rule(
        user_id="user-1",
        project_id="project-1",
        rule={
            "name": "failure spike",
            "metric": "failure_rate",
            "operator": "gte",
            "threshold": 0.2,
            "severity": "high",
            "destinations": ["pagerduty"],
        },
    )
    alerts = platform.evaluate_alerts(
        user_id="user-1",
        project_id="project-1",
        signals={"failure_rate": 0.4},
        context={"workflow_id": "workflow-1"},
    )
    assert len(alerts) == 1

    platform.ingest_observation(
        user_id="user-1",
        project_id="project-1",
        force_sample=True,
        observation={
            "trace_id": "trace-replay",
            "span_id": "s1",
            "status": "completed",
            "provider": "provider-1",
            "tool_name": "tool-1",
        },
    )
    replay = platform.replay_trace(
        user_id="user-1",
        project_id="project-1",
        trace_id="trace-replay",
        versions={"model": "m2"},
    )
    assert replay["simulation_mode"] is True
    assert platform.calibrate_components(
        user_id="user-1", project_id="project-1", component_type="tool"
    )

    goal = platform.upsert_goal(
        user_id="user-1",
        project_id="project-1",
        workflow_id="workflow-1",
        original_goal="Complete the workflow",
        state={"current_goal": "Complete the workflow", "cumulative_risk": 0.2},
    )
    assert goal["goal_drift_score"] == 0
    platform.record_subagent(
        user_id="user-1",
        workflow_id="workflow-1",
        agent_id="agent-root",
        parent_agent_id=None,
        depth=0,
        token_cost=10,
        risk_score=0.1,
        cancellation_epoch=0,
        status="completed",
    )
    tree = platform.subagent_tree(user_id="user-1", workflow_id="workflow-1")
    assert tree["total_token_cost"] == 10


def test_tenant_quota_retention_and_audit(platform: ReliabilityPlatform) -> None:
    platform.set_tenant_controls(
        user_id="user-1",
        project_id="project-1",
        controls={"max_requests_per_minute": 1, "retention_days": 30},
    )
    assert platform.admit(user_id="user-1", project_id="project-1")["admitted"]
    with pytest.raises(AdmissionRejected):
        platform.admit(user_id="user-1", project_id="project-1")
    export = platform.audit_export(user_id="user-1", project_id="project-1")
    assert export["user_id"] == "user-1"
    assert (
        platform.retention_cleanup(user_id="user-1", project_id="project-1")[
            "retention_days"
        ]
        == 30
    )


def test_benchmark_rca_failure_promotion_service_keys_and_deletion(
    platform: ReliabilityPlatform,
) -> None:
    benchmark = platform.run_protected_benchmark(
        user_id="user-1",
        project_id="project-1",
        name="protected-v1",
        baseline={
            "task_success_rate": 0.7,
            "false_success_rate": 0.2,
            "duplicate_execution_rate": 0.1,
        },
        protected={
            "task_success_rate": 0.9,
            "false_success_rate": 0.01,
            "duplicate_execution_rate": 0,
        },
    )
    assert benchmark["passed"] is True

    platform.ingest_observation(
        user_id="user-1",
        project_id="project-1",
        force_sample=True,
        observation={
            "observation_id": "cause",
            "trace_id": "trace-rca",
            "span_id": "s1",
            "status": "completed",
            "tool_name": "prepare",
        },
    )
    for index in range(3):
        platform.ingest_observation(
            user_id="user-1",
            project_id="project-1",
            force_sample=True,
            observation={
                "observation_id": f"failure-{index}",
                "trace_id": "trace-rca" if index == 0 else f"trace-{index}",
                "span_id": f"sf-{index}",
                "workflow_id": f"workflow-{index}",
                "status": "failed",
                "error_type": "provider_timeout",
                "provider": "provider-1",
                "tool_name": "send",
            },
        )
    platform.ingest_observation(
        user_id="user-1",
        project_id="project-1",
        force_sample=True,
        observation={
            "observation_id": "downstream",
            "trace_id": "trace-rca",
            "span_id": "s3",
            "status": "completed",
            "tool_name": "notify",
            "output_ref": "output-1",
        },
    )
    graph = platform.infer_root_cause(
        user_id="user-1", project_id="project-1", trace_id="trace-rca"
    )
    assert graph["inferred"] is True
    assert graph["created_edges"] >= 1
    cluster = storage.row(
        "SELECT * FROM reliability_failure_clusters WHERE user_id = ?",
        ("user-1",),
    )
    assert cluster is not None
    promoted = platform.promote_cluster_to_dataset(
        user_id="user-1", cluster_id=cluster["cluster_id"]
    )
    assert promoted["case_count"] == 3

    created = platform.create_service_account(
        user_id="user-1",
        project_id="project-1",
        name="telemetry-writer",
        scopes=["telemetry:write"],
    )
    first_key = created["api_key"]
    context = platform.authenticate_service_key(
        raw_key=first_key, required_scope="telemetry:write"
    )
    assert context["user_id"] == "user-1"
    rotated = platform.rotate_service_account_key(
        user_id="user-1", account_id=created["account_id"]
    )
    with pytest.raises(Exception):
        platform.authenticate_service_key(
            raw_key=first_key, required_scope="telemetry:write"
        )
    assert platform.authenticate_service_key(
        raw_key=rotated["api_key"], required_scope="telemetry:write"
    )

    deletion = platform.delete_tenant_data(
        user_id="user-1", project_id="project-1", confirmation="DELETE"
    )
    assert deletion["irreversible"] is True
    assert platform.query_observations(user_id="user-1", project_id="project-1") == []
