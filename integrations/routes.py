from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from .composio_service import (
    begin_connection,
    create_connection_state,
    decode_connection_state,
    disconnect_app,
    get_pending_action_result,
    list_integrations,
    refresh_tools,
    resume_pending_action,
)
from .models import ConnectAppRequest, DisconnectAppRequest


UI_DIR = Path(__file__).resolve().parent / "ui"


def _safe_return_to(value: str) -> str:
    candidate = str(value or "/apps").strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/apps"
    return candidate[:1000]


def _append_query(url: str, **values: Any) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in values.items() if value is not None})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def create_integrations_router(
    *,
    current_user: Callable[..., Dict[str, Any]],
    protected_page: Callable[[Request, str], Response],
    public_base_url: str = "",
    save_memory: Optional[Callable[[str, str], Dict[str, Any]]] = None,
    record_resumed_action: Optional[
        Callable[[str, Dict[str, Any]], None]
    ] = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/apps", include_in_schema=False)
    def apps_page(request: Request) -> Response:
        return protected_page(request, str(UI_DIR / "apps.html"))

    @router.get("/apps.css", include_in_schema=False)
    def apps_styles() -> FileResponse:
        return FileResponse(UI_DIR / "apps.css")

    @router.get("/apps.js", include_in_schema=False)
    def apps_script() -> FileResponse:
        return FileResponse(UI_DIR / "apps.js")

    @router.get("/integration_prompt.js", include_in_schema=False)
    def integration_prompt_script() -> FileResponse:
        return FileResponse(UI_DIR / "integration_prompt.js")

    @router.get("/api/integrations")
    def integrations_catalog(
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return {"ok": True, **list_integrations(user["id"])}

    @router.get("/api/integrations/status")
    def integrations_status(
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return {"ok": True, **list_integrations(user["id"])}

    @router.post("/api/integrations/connect")
    def connect_integration(
        payload: ConnectAppRequest,
        request: Request,
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return_to = _safe_return_to(payload.return_to)
        state = create_connection_state(
            user["id"],
            payload.app_id,
            return_to=return_to,
            pending_action_id=payload.pending_action_id,
        )
        base_url = public_base_url or str(request.base_url).rstrip("/")
        callback_url = (
            f"{base_url}/api/integrations/callback?state={quote(state, safe='')}"
        )
        result = begin_connection(
            user["id"],
            payload.app_id,
            callback_url=callback_url,
            retry=payload.retry,
        )
        if not result.get("ok"):
            raise HTTPException(
                status_code=502,
                detail=result.get("error") or "The app could not be connected.",
            )
        return {
            "ok": True,
            "redirect_url": result.get("redirect_url") or return_to,
            "status": result.get("status"),
            "app": result.get("app"),
        }

    @router.post("/api/integrations/disconnect")
    def disconnect_integration(
        payload: DisconnectAppRequest,
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        result = disconnect_app(user["id"], payload.app_id)
        if not result.get("ok"):
            raise HTTPException(
                status_code=502,
                detail=result.get("error") or "The app could not be disconnected.",
            )
        return {"ok": True, **result}

    @router.get("/api/integrations/callback", include_in_schema=False)
    def integration_callback(
        state: str = Query(..., min_length=20),
        user: Dict[str, Any] = Depends(current_user),
    ) -> RedirectResponse:
        try:
            connection_state = decode_connection_state(state)
        except Exception:
            return RedirectResponse(
                _append_query("/apps", integration_error="invalid_connection_state"),
                status_code=303,
            )
        if str(connection_state.get("sub")) != str(user["id"]):
            raise HTTPException(status_code=403, detail="Connection belongs to another user.")

        refresh_tools(user["id"])
        pending_action_id = connection_state.get("pending_action_id")
        resume = (
            resume_pending_action(user["id"], pending_action_id)
            if pending_action_id
            else None
        )
        if resume and save_memory:
            save_memory(
                user["id"],
                (
                    f"Connected app {connection_state.get('app_id')} and resumed "
                    f"the pending action with status {resume.get('status')}."
                ),
            )
        if resume and record_resumed_action:
            record_resumed_action(user["id"], resume)
        return_to = _safe_return_to(connection_state.get("return_to") or "/apps")
        target = _append_query(
            return_to,
            integration_connected=connection_state.get("app_id"),
            integration_resumed=(
                resume.get("status") if resume else "connected"
            ),
            resume_id=pending_action_id,
        )
        return RedirectResponse(target, status_code=303)

    @router.get("/api/integrations/resume/{action_id}")
    def integration_resume_result(
        action_id: str,
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return {
            "ok": True,
            "resume": get_pending_action_result(user["id"], action_id),
        }

    return router
