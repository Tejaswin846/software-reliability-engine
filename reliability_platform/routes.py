from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from .adapters import normalize_framework_event, normalize_openinference, normalize_otlp
from .core import (
    FRAMEWORKS,
    AdmissionRejected,
    ReliabilityPlatform,
    ReliabilityPlatformError,
)
from .models import (
    AlertEvaluateRequest,
    AlertRuleRequest,
    AlertTransitionRequest,
    AnnotationCompleteRequest,
    AnnotationRequest,
    CalibrationRequest,
    CausalEdgeRequest,
    CheckpointRequest,
    CIGateRequest,
    CircuitDecisionRequest,
    CircuitRequest,
    DatasetCaseRequest,
    DatasetRequest,
    DependencyResultRequest,
    DriftRequest,
    EvidenceRequest,
    ExperimentRequest,
    GoalRequest,
    HealthPredictionRequest,
    HumanReviewDecisionRequest,
    HumanReviewRequest,
    IncidentTransitionRequest,
    ObservationRequest,
    PolicyEvaluateRequest,
    PolicyRequest,
    PostconditionRequest,
    PromoteClusterRequest,
    ProtectedBenchmarkRequest,
    RecoveryRequest,
    RecoveryVerificationRequest,
    ReplayRequest,
    ReverifyRequest,
    RootCauseRequest,
    SagaRequest,
    SagaStepRequest,
    ServiceAccountRequest,
    ServiceAccountRotationRequest,
    SLOEvaluationRequest,
    SLORequest,
    SubagentRequest,
    TelemetryRequest,
    TenantControlsRequest,
    TenantDeletionRequest,
    ToolContractRequest,
    ToolValidationRequest,
)


def _run(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except AdmissionRejected as error:
        raise HTTPException(status_code=429, detail=str(error)) from error
    except ReliabilityPlatformError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def create_reliability_platform_router(
    *,
    platform: ReliabilityPlatform,
    current_user: Callable[..., dict[str, Any]],
    require_sdk_api_key: Callable[..., dict[str, Any]],
) -> APIRouter:
    router = APIRouter()

    def reliability_ingest_key(
        x_software_api_key: str | None = Header(None),
        authorization: str | None = Header(None),
    ) -> dict[str, Any]:
        try:
            return require_sdk_api_key(
                x_software_api_key=x_software_api_key,
                authorization=authorization,
            )
        except HTTPException as primary_error:
            supplied = x_software_api_key
            if not supplied and authorization:
                supplied = (
                    authorization[7:].strip()
                    if authorization.startswith("Bearer ")
                    else authorization.strip()
                )
            if not supplied or not supplied.startswith("mtrx_sa_"):
                raise primary_error
            try:
                return platform.authenticate_service_key(
                    raw_key=supplied, required_scope="telemetry:write"
                )
            except ReliabilityPlatformError as error:
                raise HTTPException(status_code=403, detail=str(error)) from error

    @router.get("/api/reliability/control/status")
    def status(user: dict[str, Any] = Depends(current_user)):
        return {
            "ok": True,
            "user_id": user["id"],
            "capabilities": {
                "observations": True,
                "otel": True,
                "openinference": True,
                "framework_adapters": sorted(FRAMEWORKS),
                "tool_contracts": True,
                "evidence_provenance": True,
                "taint_propagation": True,
                "postconditions": True,
                "checkpoints": True,
                "failure_specific_recovery": True,
                "sagas": True,
                "datasets": True,
                "experiments": True,
                "evaluators": True,
                "ci_gates": True,
                "annotations": True,
                "failure_clustering": True,
                "drift": True,
                "causal_graph": True,
                "policy_as_code": True,
                "shadow_mode": True,
                "adaptive_sampling": True,
                "alerts": True,
                "incidents": True,
                "incident_lifecycle": True,
                "notification_delivery": True,
                "predictive_health": True,
                "failure_forecasting": True,
                "slos": True,
                "circuit_breakers": True,
                "provider_failover": True,
                "verified_recovery": True,
                "human_review_queue": True,
                "incident_regression_automation": True,
                "replay": True,
                "calibration": True,
                "long_horizon_goals": True,
                "subagent_accounting": True,
                "protected_benchmarking": True,
                "automatic_root_cause": True,
                "failure_to_dataset": True,
                "scoped_service_accounts": True,
                "key_rotation": True,
                "tenant_data_deletion": True,
                "tenant_controls": True,
            },
        }

    @router.post("/api/reliability/health/predict")
    def predict_health(
        payload: HealthPredictionRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "health": _run(
                lambda: platform.predict_health(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    component_type=payload.component_type,
                    component_name=payload.component_name,
                    window_minutes=payload.window_minutes,
                    preventive_actions=payload.preventive_actions,
                )
            ),
        }

    @router.get("/api/reliability/health/history")
    def health_history(
        project_id: str | None = Query(None, max_length=180),
        limit: int = Query(100, ge=1, le=500),
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "snapshots": platform.health_history(
                user_id=user["id"], project_id=project_id, limit=limit
            ),
        }

    @router.post("/api/reliability/slos")
    def create_slo(payload: SLORequest, user: dict[str, Any] = Depends(current_user)):
        return {
            "ok": True,
            "slo": _run(
                lambda: platform.create_slo(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    name=payload.name,
                    metric=payload.metric,
                    operator=payload.operator,
                    target=payload.target,
                    window_minutes=payload.window_minutes,
                    severity=payload.severity,
                )
            ),
        }

    @router.post("/api/reliability/slos/evaluate")
    def evaluate_slos(
        payload: SLOEvaluationRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "slo_health": platform.evaluate_slos(
                user_id=user["id"],
                project_id=payload.project_id,
                metrics=payload.metrics,
            ),
        }

    @router.post("/api/reliability/circuits")
    def configure_circuit(
        payload: CircuitRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "circuit": platform.configure_circuit(
                user_id=user["id"],
                project_id=payload.project_id,
                dependency_type=payload.dependency_type,
                dependency_name=payload.dependency_name,
                config=payload.config,
            ),
        }

    @router.get("/api/reliability/circuits")
    def list_circuits(
        project_id: str | None = Query(None, max_length=180),
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "circuits": platform.list_circuits(
                user_id=user["id"], project_id=project_id
            ),
        }

    @router.post("/api/reliability/circuits/before-call")
    def before_dependency_call(
        payload: CircuitDecisionRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "routing": platform.before_dependency_call(
                user_id=user["id"],
                project_id=payload.project_id,
                dependency_type=payload.dependency_type,
                dependency_name=payload.dependency_name,
                fallback_chain=payload.fallback_chain,
            ),
        }

    @router.post("/api/reliability/circuits/result")
    def dependency_result(
        payload: DependencyResultRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "circuit": _run(
                lambda: platform.record_dependency_result(
                    user_id=user["id"],
                    circuit_id=payload.circuit_id,
                    success=payload.success,
                    latency_ms=payload.latency_ms,
                    error_type=payload.error_type,
                    selected_dependency=payload.selected_dependency,
                )
            ),
        }

    @router.post("/api/reliability/observations/ingest")
    def ingest_observation(
        payload: ObservationRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        _run(
            lambda: platform.admit(
                user_id=user["id"],
                project_id=payload.project_id,
                risk_score=payload.observation.get("risk_score") or 0,
                tokens=payload.observation.get("token_cost") or 0,
            )
        )
        result = _run(
            lambda: platform.ingest_observation(
                user_id=user["id"],
                project_id=payload.project_id,
                observation=payload.observation,
                source=payload.source,
                framework=payload.framework,
                redaction_actions=payload.redaction_actions,
                force_sample=payload.force_sample,
            )
        )
        return {"ok": True, "observation": result}

    @router.get("/api/reliability/observations")
    def query_observations(
        project_id: str | None = Query(None, max_length=180),
        trace_id: str | None = Query(None, max_length=180),
        workflow_id: str | None = Query(None, max_length=180),
        tool_name: str | None = Query(None, max_length=300),
        status_filter: str | None = Query(None, alias="status", max_length=80),
        decision: str | None = Query(None, max_length=80),
        minimum_risk: float | None = Query(None, ge=0, le=1),
        limit: int = Query(200, ge=1, le=1000),
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "observations": platform.query_observations(
                user_id=user["id"],
                project_id=project_id,
                trace_id=trace_id,
                workflow_id=workflow_id,
                tool_name=tool_name,
                status=status_filter,
                decision=decision,
                minimum_risk=minimum_risk,
                limit=limit,
            ),
        }

    def ingest_normalized(
        *,
        user_id: str,
        project_id: str | None,
        observations: list[dict[str, Any]],
        source: str,
        framework: str | None,
        redaction_actions: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        if len(observations) > 1000:
            raise HTTPException(
                status_code=413, detail="Telemetry batches are limited to 1000 spans."
            )
        _run(
            lambda: platform.admit(
                user_id=user_id,
                project_id=project_id,
                risk_score=max(
                    (float(item.get("risk_score") or 0) for item in observations),
                    default=0,
                ),
                tokens=sum(int(item.get("token_cost") or 0) for item in observations),
            )
        )
        return [
            platform.ingest_observation(
                user_id=user_id,
                project_id=project_id,
                observation=item,
                source=source,
                framework=framework or item.get("framework"),
                redaction_actions=redaction_actions,
            )
            for item in observations
        ]

    @router.post("/api/reliability/telemetry/otel")
    def ingest_otel(
        payload: TelemetryRequest, user: dict[str, Any] = Depends(current_user)
    ):
        observations = normalize_otlp(payload.payload)
        return {
            "ok": True,
            "accepted": ingest_normalized(
                user_id=user["id"],
                project_id=payload.project_id,
                observations=observations,
                source="opentelemetry",
                framework=None,
                redaction_actions=payload.redaction_actions,
            ),
        }

    @router.post("/api/reliability/telemetry/openinference")
    def ingest_openinference(
        payload: TelemetryRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        observations = normalize_openinference(payload.payload)
        return {
            "ok": True,
            "accepted": ingest_normalized(
                user_id=user["id"],
                project_id=payload.project_id,
                observations=observations,
                source="openinference",
                framework=None,
                redaction_actions=payload.redaction_actions,
            ),
        }

    @router.post("/api/reliability/adapters/{framework}/ingest")
    def ingest_framework(
        framework: str,
        payload: TelemetryRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        normalized = _run(lambda: normalize_framework_event(framework, payload.payload))
        return {
            "ok": True,
            "observation": ingest_normalized(
                user_id=user["id"],
                project_id=payload.project_id,
                observations=[normalized],
                source="framework-adapter",
                framework=framework,
                redaction_actions=payload.redaction_actions,
            )[0],
        }

    @router.post("/api/sdk/v2/observations")
    def sdk_observation(
        payload: ObservationRequest,
        context: dict[str, Any] = Depends(reliability_ingest_key),
    ):
        result = ingest_normalized(
            user_id=context["user_id"],
            project_id=context["project_id"],
            observations=[payload.observation],
            source=payload.source,
            framework=payload.framework,
            redaction_actions=payload.redaction_actions,
        )[0]
        return {"ok": True, "observation": result}

    @router.post("/api/sdk/v2/telemetry/otel")
    def sdk_otel(
        payload: TelemetryRequest,
        context: dict[str, Any] = Depends(reliability_ingest_key),
    ):
        return {
            "ok": True,
            "accepted": ingest_normalized(
                user_id=context["user_id"],
                project_id=context["project_id"],
                observations=normalize_otlp(payload.payload),
                source="opentelemetry",
                framework=None,
                redaction_actions=payload.redaction_actions,
            ),
        }

    @router.post("/api/sdk/v2/adapters/{framework}")
    def sdk_framework(
        framework: str,
        payload: TelemetryRequest,
        context: dict[str, Any] = Depends(reliability_ingest_key),
    ):
        normalized = _run(lambda: normalize_framework_event(framework, payload.payload))
        result = ingest_normalized(
            user_id=context["user_id"],
            project_id=context["project_id"],
            observations=[normalized],
            source="framework-adapter",
            framework=framework,
            redaction_actions=payload.redaction_actions,
        )[0]
        return {"ok": True, "observation": result}

    @router.post("/api/reliability/tool-contracts")
    def register_contract(
        payload: ToolContractRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "contract": _run(
                lambda: platform.register_tool_contract(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    contract=payload.contract,
                )
            ),
        }

    @router.get("/api/reliability/tool-contracts/{tool_name}")
    def get_contract(
        tool_name: str,
        project_id: str | None = Query(None, max_length=180),
        version: int | None = Query(None, ge=1),
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "contract": _run(
                lambda: platform.get_tool_contract(
                    user_id=user["id"],
                    project_id=project_id,
                    tool_name=tool_name,
                    version=version,
                )
            ),
        }

    @router.post("/api/reliability/tool-contracts/validate")
    def validate_contract(
        payload: ToolValidationRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "validation": _run(
                lambda: platform.validate_tool_action(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    tool_name=payload.tool_name,
                    arguments=payload.arguments,
                    permissions=payload.permissions,
                    confirmed=payload.confirmed,
                )
            ),
        }

    @router.post("/api/reliability/tool-contracts/postcondition")
    def verify_postcondition(
        payload: PostconditionRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "verification": _run(
                lambda: platform.verify_postcondition(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    tool_name=payload.tool_name,
                    observed_result=payload.observed_result,
                    independent_readback=payload.independent_readback,
                )
            ),
        }

    @router.post("/api/reliability/evidence")
    def record_evidence(
        payload: EvidenceRequest, user: dict[str, Any] = Depends(current_user)
    ):
        return {
            "ok": True,
            "evidence": _run(
                lambda: platform.record_evidence(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    workflow_id=payload.workflow_id,
                    evidence=payload.evidence,
                )
            ),
        }

    @router.post("/api/reliability/evidence/{evidence_id}/reverify")
    def reverify_evidence(
        evidence_id: str,
        payload: ReverifyRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "evidence": _run(
                lambda: platform.reverify_evidence(
                    user_id=user["id"],
                    evidence_id=evidence_id,
                    verifier=payload.verifier,
                    independent=payload.independent,
                    passed=payload.passed,
                )
            ),
        }

    @router.get("/api/reliability/evidence/workflows/{workflow_id}/taint")
    def taint_state(workflow_id: str, user: dict[str, Any] = Depends(current_user)):
        return {
            "ok": True,
            **platform.workflow_taint_state(
                user_id=user["id"], workflow_id=workflow_id
            ),
        }

    @router.post("/api/reliability/checkpoints")
    def checkpoint(
        payload: CheckpointRequest, user: dict[str, Any] = Depends(current_user)
    ):
        return {
            "ok": True,
            "checkpoint": _run(
                lambda: platform.create_checkpoint(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    workflow_id=payload.workflow_id,
                    checkpoint=payload.checkpoint,
                )
            ),
        }

    @router.get("/api/reliability/checkpoints/{workflow_id}/restore")
    def restore(workflow_id: str, user: dict[str, Any] = Depends(current_user)):
        return {
            "ok": True,
            "checkpoint": _run(
                lambda: platform.restore_checkpoint(
                    user_id=user["id"], workflow_id=workflow_id
                )
            ),
        }

    @router.post("/api/reliability/recovery/plan")
    def recovery(payload: RecoveryRequest, _: dict[str, Any] = Depends(current_user)):
        return {
            "ok": True,
            "recovery": platform.recovery_plan(payload.failure_type, payload.attempt),
        }

    @router.post("/api/reliability/recovery/verify")
    def verify_recovery(
        payload: RecoveryVerificationRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "recovery": platform.verify_recovery(
                user_id=user["id"],
                project_id=payload.project_id,
                workflow_id=payload.workflow_id,
                failure_type=payload.failure_type,
                attempt=payload.attempt,
                strategy=payload.strategy,
                before_state=payload.before_state,
                after_state=payload.after_state,
                independent_evidence=payload.independent_evidence,
                expected_state=payload.expected_state,
            ),
        }

    @router.post("/api/reliability/sagas")
    def create_saga(payload: SagaRequest, user: dict[str, Any] = Depends(current_user)):
        return {
            "ok": True,
            "saga": _run(
                lambda: platform.create_saga(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    workflow_id=payload.workflow_id,
                    steps=payload.steps,
                )
            ),
        }

    @router.post("/api/reliability/sagas/{saga_id}/steps")
    def complete_saga_step(
        saga_id: str,
        payload: SagaStepRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "saga": _run(
                lambda: platform.complete_saga_step(
                    user_id=user["id"],
                    saga_id=saga_id,
                    sequence=payload.sequence,
                    receipt=payload.receipt,
                    success=payload.success,
                )
            ),
        }

    @router.get("/api/reliability/sagas/{saga_id}/compensation")
    def compensation(saga_id: str, user: dict[str, Any] = Depends(current_user)):
        return {
            "ok": True,
            **_run(
                lambda: platform.compensation_plan(user_id=user["id"], saga_id=saga_id)
            ),
        }

    @router.post("/api/reliability/datasets")
    def create_dataset(
        payload: DatasetRequest, user: dict[str, Any] = Depends(current_user)
    ):
        return {
            "ok": True,
            "dataset": platform.create_dataset(
                user_id=user["id"],
                project_id=payload.project_id,
                name=payload.name,
                description=payload.description,
                protected=payload.protected,
            ),
        }

    @router.post("/api/reliability/datasets/{dataset_id}/cases")
    def add_case(
        dataset_id: str,
        payload: DatasetCaseRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "case": _run(
                lambda: platform.add_dataset_case(
                    user_id=user["id"], dataset_id=dataset_id, case=payload.case
                )
            ),
        }

    @router.post("/api/reliability/experiments/run")
    def run_experiment(
        payload: ExperimentRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "experiment": _run(
                lambda: platform.run_experiment(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    name=payload.name,
                    dataset_id=payload.dataset_id,
                    control=payload.control,
                    candidate=payload.candidate,
                    evaluators=payload.evaluators,
                )
            ),
        }

    @router.post("/api/reliability/ci-gate")
    def ci_gate(payload: CIGateRequest, _: dict[str, Any] = Depends(current_user)):
        result = platform.ci_gate(payload.metrics, payload.thresholds)
        return {"ok": result["passed"], "gate": result}

    @router.post("/api/reliability/annotations")
    def enqueue_annotation(
        payload: AnnotationRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "annotation": platform.enqueue_annotation(
                user_id=user["id"],
                project_id=payload.project_id,
                reason=payload.reason,
                workflow_id=payload.workflow_id,
                observation_id=payload.observation_id,
                decision_id=payload.decision_id,
            ),
        }

    @router.get("/api/reliability/annotations")
    def annotations(
        project_id: str | None = Query(None, max_length=180),
        status_filter: str = Query("pending", alias="status", max_length=80),
        limit: int = Query(100, ge=1, le=500),
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "annotations": platform.list_annotations(
                user_id=user["id"],
                project_id=project_id,
                status=status_filter,
                limit=limit,
            ),
        }

    @router.post("/api/reliability/annotations/{annotation_id}/complete")
    def complete_annotation(
        annotation_id: str,
        payload: AnnotationCompleteRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "annotation": _run(
                lambda: platform.complete_annotation(
                    user_id=user["id"],
                    annotation_id=annotation_id,
                    reviewer=payload.reviewer,
                    label=payload.label,
                    confidence=payload.confidence,
                    notes=payload.notes,
                )
            ),
        }

    @router.post("/api/reliability/reviews")
    def enqueue_human_review(
        payload: HumanReviewRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "review": _run(
                lambda: platform.enqueue_human_review(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    workflow_id=payload.workflow_id,
                    reason=payload.reason,
                    evidence_bundle=payload.evidence_bundle,
                    permissions=payload.permissions,
                    recommended_action=payload.recommended_action,
                    observation_id=payload.observation_id,
                    decision_id=payload.decision_id,
                )
            ),
        }

    @router.get("/api/reliability/reviews/{review_id}")
    def get_human_review(
        review_id: str,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "review": _run(
                lambda: platform.get_human_review(
                    user_id=user["id"], review_id=review_id
                )
            ),
        }

    @router.post("/api/reliability/reviews/{review_id}/decision")
    def decide_human_review(
        review_id: str,
        payload: HumanReviewDecisionRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "review": _run(
                lambda: platform.decide_human_review(
                    user_id=user["id"],
                    review_id=review_id,
                    reviewer=user["id"],
                    action=payload.action,
                    notes=payload.notes,
                    resume_payload=payload.resume_payload,
                )
            ),
        }

    @router.post("/api/reliability/drift/detect")
    def drift(payload: DriftRequest, user: dict[str, Any] = Depends(current_user)):
        return {
            "ok": True,
            "drift": platform.detect_drift(
                user_id=user["id"],
                project_id=payload.project_id,
                component_type=payload.component_type,
                component_name=payload.component_name,
                baseline=payload.baseline,
                current=payload.current,
            ),
        }

    @router.post("/api/reliability/causal-graph/edges")
    def causal_edge(
        payload: CausalEdgeRequest, user: dict[str, Any] = Depends(current_user)
    ):
        return {
            "ok": True,
            "edge": platform.record_causal_edge(
                user_id=user["id"],
                project_id=payload.project_id,
                root_failure_id=payload.root_failure_id,
                cause_id=payload.cause_id,
                effect_id=payload.effect_id,
                relation=payload.relation,
                confidence=payload.confidence,
                contaminated_outputs=payload.contaminated_outputs,
                external_side_effects=payload.external_side_effects,
            ),
        }

    @router.get("/api/reliability/causal-graph/{root_failure_id}")
    def causal_graph(
        root_failure_id: str, user: dict[str, Any] = Depends(current_user)
    ):
        return {
            "ok": True,
            "graph": platform.root_cause_graph(
                user_id=user["id"], root_failure_id=root_failure_id
            ),
        }

    @router.post("/api/reliability/policies")
    def policy(payload: PolicyRequest, user: dict[str, Any] = Depends(current_user)):
        return {
            "ok": True,
            "policy": platform.create_policy(
                user_id=user["id"],
                project_id=payload.project_id,
                name=payload.name,
                mode=payload.mode,
                rollout_percent=payload.rollout_percent,
                rules=payload.rules,
                tenant_overrides=payload.tenant_overrides,
            ),
        }

    @router.post("/api/reliability/policies/evaluate")
    def evaluate_policy(
        payload: PolicyEvaluateRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "decision": _run(
                lambda: platform.evaluate_policy(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    policy_name=payload.policy_name,
                    context=payload.context,
                    versions=payload.versions,
                )
            ),
        }

    @router.post("/api/reliability/alerts/rules")
    def alert_rule(
        payload: AlertRuleRequest, user: dict[str, Any] = Depends(current_user)
    ):
        return {
            "ok": True,
            "rule": platform.create_alert_rule(
                user_id=user["id"], project_id=payload.project_id, rule=payload.rule
            ),
        }

    @router.post("/api/reliability/alerts/evaluate")
    def alerts(
        payload: AlertEvaluateRequest, user: dict[str, Any] = Depends(current_user)
    ):
        return {
            "ok": True,
            "alerts": platform.evaluate_alerts(
                user_id=user["id"],
                project_id=payload.project_id,
                signals=payload.signals,
                context=payload.context,
            ),
        }

    @router.post("/api/reliability/alerts/{alert_id}/transition")
    def transition_alert(
        alert_id: str,
        payload: AlertTransitionRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "alert": _run(
                lambda: platform.transition_alert(
                    user_id=user["id"],
                    alert_id=alert_id,
                    action=payload.action,
                    actor=user["id"],
                    resolution=payload.resolution,
                )
            ),
        }

    @router.get("/api/reliability/incidents")
    def incidents(
        project_id: str | None = Query(None, max_length=180),
        status_filter: str | None = Query(None, alias="status", max_length=80),
        limit: int = Query(100, ge=1, le=500),
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "incidents": platform.list_incidents(
                user_id=user["id"],
                project_id=project_id,
                status=status_filter,
                limit=limit,
            ),
        }

    @router.get("/api/reliability/incidents/{incident_id}")
    def incident(
        incident_id: str,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "incident": _run(
                lambda: platform.get_incident(
                    user_id=user["id"], incident_id=incident_id
                )
            ),
        }

    @router.post("/api/reliability/incidents/{incident_id}/transition")
    def transition_incident(
        incident_id: str,
        payload: IncidentTransitionRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "incident": _run(
                lambda: platform.transition_incident(
                    user_id=user["id"],
                    incident_id=incident_id,
                    action=payload.action,
                    actor=user["id"],
                    resolution=payload.resolution,
                )
            ),
        }

    @router.post("/api/reliability/replay")
    def replay(payload: ReplayRequest, user: dict[str, Any] = Depends(current_user)):
        return {
            "ok": True,
            "replay": _run(
                lambda: platform.replay_trace(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    trace_id=payload.trace_id,
                    versions=payload.versions,
                )
            ),
        }

    @router.post("/api/reliability/calibration")
    def calibration(
        payload: CalibrationRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "components": platform.calibrate_components(
                user_id=user["id"],
                project_id=payload.project_id,
                component_type=payload.component_type,
            ),
        }

    @router.post("/api/reliability/goals")
    def goal(payload: GoalRequest, user: dict[str, Any] = Depends(current_user)):
        return {
            "ok": True,
            "goal": platform.upsert_goal(
                user_id=user["id"],
                project_id=payload.project_id,
                workflow_id=payload.workflow_id,
                original_goal=payload.original_goal,
                state=payload.state,
            ),
        }

    @router.post("/api/reliability/subagents")
    def subagent(
        payload: SubagentRequest, user: dict[str, Any] = Depends(current_user)
    ):
        return {
            "ok": True,
            "tree": platform.record_subagent(
                user_id=user["id"],
                workflow_id=payload.workflow_id,
                agent_id=payload.agent_id,
                parent_agent_id=payload.parent_agent_id,
                depth=payload.depth,
                token_cost=payload.token_cost,
                risk_score=payload.risk_score,
                cancellation_epoch=payload.cancellation_epoch,
                status=payload.status,
            ),
        }

    @router.get("/api/reliability/subagents/{workflow_id}")
    def subagent_tree(workflow_id: str, user: dict[str, Any] = Depends(current_user)):
        return {
            "ok": True,
            "tree": platform.subagent_tree(user_id=user["id"], workflow_id=workflow_id),
        }

    @router.post("/api/reliability/benchmarks/protected")
    def protected_benchmark(
        payload: ProtectedBenchmarkRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "benchmark": platform.run_protected_benchmark(
                user_id=user["id"],
                project_id=payload.project_id,
                name=payload.name,
                baseline=payload.baseline,
                protected=payload.protected,
            ),
        }

    @router.post("/api/reliability/failure-clusters/{cluster_id}/promote")
    def promote_failure_cluster(
        cluster_id: str,
        payload: PromoteClusterRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "result": _run(
                lambda: platform.promote_cluster_to_dataset(
                    user_id=user["id"], cluster_id=cluster_id, name=payload.name
                )
            ),
        }

    @router.post("/api/reliability/root-cause/infer")
    def infer_root_cause(
        payload: RootCauseRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "graph": _run(
                lambda: platform.infer_root_cause(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    trace_id=payload.trace_id,
                )
            ),
        }

    @router.post("/api/reliability/service-accounts")
    def create_service_account(
        payload: ServiceAccountRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "service_account": _run(
                lambda: platform.create_service_account(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    name=payload.name,
                    scopes=payload.scopes,
                    expires_at=payload.expires_at,
                )
            ),
        }

    @router.post("/api/reliability/service-accounts/{account_id}/rotate")
    def rotate_service_account(
        account_id: str,
        payload: ServiceAccountRotationRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "service_account": _run(
                lambda: platform.rotate_service_account_key(
                    user_id=user["id"],
                    account_id=account_id,
                    expires_at=payload.expires_at,
                )
            ),
        }

    @router.post("/api/reliability/tenant-data/delete")
    def delete_tenant_data(
        payload: TenantDeletionRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "deletion": _run(
                lambda: platform.delete_tenant_data(
                    user_id=user["id"],
                    project_id=payload.project_id,
                    confirmation=payload.confirmation,
                )
            ),
        }

    @router.post("/api/reliability/tenant-controls")
    def tenant_controls(
        payload: TenantControlsRequest,
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "controls": platform.set_tenant_controls(
                user_id=user["id"],
                project_id=payload.project_id,
                controls=payload.controls,
            ),
        }

    @router.post("/api/reliability/retention/run")
    def retention(
        project_id: str | None = Query(None, max_length=180),
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "retention": platform.retention_cleanup(
                user_id=user["id"], project_id=project_id
            ),
        }

    @router.get("/api/reliability/audit-export")
    def audit_export(
        project_id: str | None = Query(None, max_length=180),
        user: dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "export": platform.audit_export(user_id=user["id"], project_id=project_id),
        }

    return router


__all__ = ["create_reliability_platform_router"]
