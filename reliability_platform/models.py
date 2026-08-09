from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ObservationRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    observation: dict[str, Any]
    source: str = Field("matrixs-sdk", max_length=120)
    framework: str | None = Field(None, max_length=120)
    redaction_actions: dict[
        str, Literal["drop", "mask", "hash", "tokenize", "allow"]
    ] = Field(default_factory=dict)
    force_sample: bool = False


class TelemetryRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    payload: dict[str, Any]
    redaction_actions: dict[
        str, Literal["drop", "mask", "hash", "tokenize", "allow"]
    ] = Field(default_factory=dict)


class ToolContractRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    contract: dict[str, Any]


class ToolValidationRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    tool_name: str = Field(..., min_length=1, max_length=300)
    arguments: dict[str, Any] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list, max_length=200)
    confirmed: bool = False


class PostconditionRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    tool_name: str = Field(..., min_length=1, max_length=300)
    observed_result: dict[str, Any]
    independent_readback: dict[str, Any] | None = None


class EvidenceRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    workflow_id: str = Field(..., min_length=1, max_length=180)
    evidence: dict[str, Any]


class ReverifyRequest(BaseModel):
    verifier: str = Field(..., min_length=1, max_length=180)
    independent: bool = True
    passed: bool


class CheckpointRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    workflow_id: str = Field(..., min_length=1, max_length=180)
    checkpoint: dict[str, Any]


class RecoveryRequest(BaseModel):
    failure_type: str = Field(..., min_length=1, max_length=180)
    attempt: int = Field(1, ge=1, le=20)


class SagaRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    workflow_id: str = Field(..., min_length=1, max_length=180)
    steps: list[dict[str, Any]] = Field(..., min_length=1, max_length=1000)


class SagaStepRequest(BaseModel):
    sequence: int = Field(..., ge=1)
    receipt: dict[str, Any] = Field(default_factory=dict)
    success: bool


class DatasetRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    name: str = Field(..., min_length=1, max_length=300)
    description: str | None = Field(None, max_length=4000)
    protected: bool = True


class DatasetCaseRequest(BaseModel):
    case: dict[str, Any]


class ExperimentRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    name: str = Field(..., min_length=1, max_length=300)
    dataset_id: str = Field(..., min_length=1, max_length=180)
    control: dict[str, Any]
    candidate: dict[str, Any]
    evaluators: list[str] = Field(..., min_length=1, max_length=30)


class CIGateRequest(BaseModel):
    metrics: dict[str, Any]
    thresholds: dict[str, Any] | None = None


class AnnotationRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    reason: str = Field(..., min_length=1, max_length=180)
    workflow_id: str | None = Field(None, max_length=180)
    observation_id: str | None = Field(None, max_length=180)
    decision_id: str | None = Field(None, max_length=180)


class AnnotationCompleteRequest(BaseModel):
    reviewer: str = Field(..., min_length=1, max_length=180)
    label: str = Field(..., min_length=1, max_length=180)
    confidence: float = Field(..., ge=0, le=1)
    notes: str | None = Field(None, max_length=4000)


class DriftRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    component_type: str = Field(..., min_length=1, max_length=80)
    component_name: str = Field(..., min_length=1, max_length=300)
    baseline: dict[str, float]
    current: dict[str, float]


class CausalEdgeRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    root_failure_id: str = Field(..., min_length=1, max_length=180)
    cause_id: str = Field(..., min_length=1, max_length=180)
    effect_id: str = Field(..., min_length=1, max_length=180)
    relation: str = Field(..., min_length=1, max_length=180)
    confidence: float = Field(..., ge=0, le=1)
    contaminated_outputs: list[str] = Field(default_factory=list, max_length=1000)
    external_side_effects: list[str] = Field(default_factory=list, max_length=1000)


class PolicyRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    name: str = Field(..., min_length=1, max_length=300)
    mode: Literal["shadow", "partial", "enforce"]
    rollout_percent: float = Field(0, ge=0, le=100)
    rules: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    tenant_overrides: dict[str, Any] = Field(default_factory=dict)


class PolicyEvaluateRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    policy_name: str = Field(..., min_length=1, max_length=300)
    context: dict[str, Any]
    versions: dict[str, str] = Field(default_factory=dict)


class AlertRuleRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    rule: dict[str, Any]


class AlertEvaluateRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    signals: dict[str, float]
    context: dict[str, Any] = Field(default_factory=dict)


class ReplayRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    trace_id: str = Field(..., min_length=1, max_length=180)
    versions: dict[str, str] = Field(default_factory=dict)


class CalibrationRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    component_type: Literal["tool", "model", "provider", "agent"]


class GoalRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    workflow_id: str = Field(..., min_length=1, max_length=180)
    original_goal: str = Field(..., min_length=1, max_length=20000)
    state: dict[str, Any] = Field(default_factory=dict)


class SubagentRequest(BaseModel):
    workflow_id: str = Field(..., min_length=1, max_length=180)
    agent_id: str = Field(..., min_length=1, max_length=180)
    parent_agent_id: str | None = Field(None, max_length=180)
    depth: int = Field(0, ge=0, le=100)
    token_cost: int = Field(0, ge=0)
    risk_score: float = Field(0, ge=0, le=1)
    cancellation_epoch: int = Field(0, ge=0)
    status: str = Field("running", max_length=80)


class TenantControlsRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    controls: dict[str, Any]


class ProtectedBenchmarkRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    name: str = Field(..., min_length=1, max_length=300)
    baseline: dict[str, float]
    protected: dict[str, float]


class PromoteClusterRequest(BaseModel):
    name: str | None = Field(None, max_length=300)


class RootCauseRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    trace_id: str = Field(..., min_length=1, max_length=180)


class ServiceAccountRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    name: str = Field(..., min_length=1, max_length=300)
    scopes: list[str] = Field(..., min_length=1, max_length=100)
    expires_at: str | None = Field(None, max_length=80)


class ServiceAccountRotationRequest(BaseModel):
    expires_at: str | None = Field(None, max_length=80)


class TenantDeletionRequest(BaseModel):
    project_id: str | None = Field(None, max_length=180)
    confirmation: str = Field(..., min_length=6, max_length=6)
