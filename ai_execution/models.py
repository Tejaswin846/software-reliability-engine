from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    request: str = Field(..., min_length=1, max_length=50000)
    action: Dict[str, Any] = Field(default_factory=dict)
    chat_id: Optional[str] = Field(None, max_length=180)
    workflow_id: Optional[str] = Field(None, max_length=180)
    return_to: str = Field("/", min_length=1, max_length=1000)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RequestReference(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=180)


class ConfirmationRequest(RequestReference):
    decision: Literal["confirm", "cancel"]
    reason: Optional[str] = Field(None, max_length=1200)


class VerificationEvaluateRequest(BaseModel):
    workflow_id: str = Field(..., min_length=1, max_length=180)
    step_id: str = Field(..., min_length=1, max_length=180)
    phase: Literal["pre", "post"] = "pre"
    action: Dict[str, Any]
    evidence: List[Dict[str, Any]] = Field(default_factory=list, max_length=500)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SemanticAuditRequest(BaseModel):
    decision_id: str = Field(..., min_length=1, max_length=180)
    outcome: Literal["passed", "hidden_error", "false_positive", "false_negative"]
    verifier: str = Field("semantic-auditor", min_length=1, max_length=160)
    tokens_used: int = Field(0, ge=0, le=10000000)
    notes: Optional[str] = Field(None, max_length=4000)
