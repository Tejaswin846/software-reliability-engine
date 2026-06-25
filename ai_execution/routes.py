from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from .models import ConfirmationRequest, PlanRequest, RequestReference
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

    return router
