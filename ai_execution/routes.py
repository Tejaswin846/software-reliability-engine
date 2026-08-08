from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse

from .models import (
    ConfirmationRequest,
    PlanRequest,
    RequestReference,
    SemanticAuditRequest,
    VerificationEvaluateRequest,
)
from .service import AIExecutionService
from .storage import initialize_storage


UI_DIR = Path(__file__).resolve().parent / "ui"


def _response(result: Dict[str, Any], *, failure_status: int = 400):
    if result.get("ok"):
        return result
    if result.get("not_found"):
        return JSONResponse(status_code=404, content=result)
    return JSONResponse(status_code=failure_status, content=result)


def create_ai_execution_router(
    *,
    service: AIExecutionService,
    current_user: Callable[..., Dict[str, Any]],
    distributed_lock: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()
    initialize_storage()

    @router.get("/ai_confirmation.js", include_in_schema=False)
    def confirmation_script() -> FileResponse:
        return FileResponse(UI_DIR / "confirmation.js")

    @router.post("/api/ai/plan")
    def plan(
        payload: PlanRequest,
        user: Dict[str, Any] = Depends(current_user),
    ):
        result = service.plan(
            user_id=user["id"],
            request_text=payload.request,
            action=payload.action,
            chat_id=payload.chat_id,
            workflow_id=payload.workflow_id,
            return_to=payload.return_to,
            metadata=payload.metadata,
        )
        return _response(result)

    @router.post("/api/ai/validate")
    def validate(
        payload: RequestReference,
        user: Dict[str, Any] = Depends(current_user),
    ):
        result = service.validate(
            user_id=user["id"],
            request_id=payload.request_id,
        )
        return _response(result, failure_status=422)

    @router.post("/api/ai/confirm")
    def confirm(
        payload: ConfirmationRequest,
        user: Dict[str, Any] = Depends(current_user),
    ):
        result = service.confirm(
            user_id=user["id"],
            request_id=payload.request_id,
            decision=payload.decision,
            reason=payload.reason,
        )
        return _response(result, failure_status=409)

    @router.post("/api/ai/execute")
    def execute(
        payload: RequestReference,
        user: Dict[str, Any] = Depends(current_user),
    ):
        resource = f"ai-execution:{user['id']}:{payload.request_id}"
        with distributed_lock(
            resource,
            ttl_seconds=120,
            wait_seconds=0.25,
        ) as lock:
            if not lock["acquired"]:
                return JSONResponse(
                    status_code=409,
                    content={
                        "ok": False,
                        "blocked": True,
                        "request_id": payload.request_id,
                        "error": "This AI request is already executing.",
                    },
                )
            result = service.execute(
                user_id=user["id"],
                request_id=payload.request_id,
            )
        return _response(result, failure_status=409)

    @router.get("/api/ai/audit/{request_id}")
    def audit(
        request_id: str,
        user: Dict[str, Any] = Depends(current_user),
    ):
        result = service.audit(user_id=user["id"], request_id=request_id)
        if result is None:
            return JSONResponse(
                status_code=404,
                content={"ok": False, "error": "AI request not found."},
            )
        return {"ok": True, **result}

    @router.post("/api/ai/verification/evaluate")
    def evaluate_verification(
        payload: VerificationEvaluateRequest,
        user: Dict[str, Any] = Depends(current_user),
    ):
        result = service.evaluate_risk(
            user_id=user["id"],
            workflow_id=payload.workflow_id,
            step_id=payload.step_id,
            phase=payload.phase,
            action=payload.action,
            evidence=payload.evidence,
            metadata=payload.metadata,
        )
        return {"ok": True, "verification": result}

    @router.get("/api/ai/verification/workflows/{workflow_id}")
    def verification_workflow(
        workflow_id: str,
        evidence_limit: int = Query(200, ge=1, le=1000),
        decision_limit: int = Query(100, ge=1, le=500),
        user: Dict[str, Any] = Depends(current_user),
    ):
        result = service.verification_workflow(
            user_id=user["id"],
            workflow_id=workflow_id,
            evidence_limit=evidence_limit,
            decision_limit=decision_limit,
        )
        return {"ok": True, **result}

    @router.get("/api/ai/verification/metrics")
    def risk_verification_metrics(
        user: Dict[str, Any] = Depends(current_user),
    ):
        return {"ok": True, "metrics": service.verification_metrics(user_id=user["id"])}

    @router.get("/api/ai/verification/audits/pending")
    def pending_verification_audits(
        limit: int = Query(100, ge=1, le=500),
        user: Dict[str, Any] = Depends(current_user),
    ):
        return {
            "ok": True,
            "audits": service.pending_verification_audits(
                user_id=user["id"],
                limit=limit,
            ),
        }

    @router.post("/api/ai/verification/audits")
    def submit_semantic_audit(
        payload: SemanticAuditRequest,
        user: Dict[str, Any] = Depends(current_user),
    ):
        try:
            result = service.submit_semantic_audit(
                user_id=user["id"],
                decision_id=payload.decision_id,
                outcome=payload.outcome,
                verifier=payload.verifier,
                tokens_used=payload.tokens_used,
                notes=payload.notes,
            )
        except LookupError as error:
            return JSONResponse(status_code=404, content={"ok": False, "error": str(error)})
        return {"ok": True, "audit": result}

    return router
