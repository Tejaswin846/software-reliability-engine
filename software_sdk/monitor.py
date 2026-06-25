from __future__ import annotations

import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .client import SoftwareClient, SoftwareClientError


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class BufferedRequest:
    method_name: str
    payload: Dict[str, Any]
    error: str


class ReliabilityMonitor:
    def __init__(
        self,
        project_name: str,
        api_url: str,
        api_key: str = "dev-key",
        timeout: float = 10.0,
        raise_on_error: bool = False,
    ) -> None:
        self.project_name = project_name
        self.client = SoftwareClient(api_url=api_url, api_key=api_key, timeout=timeout)
        self.raise_on_error = raise_on_error
        self.buffer: List[BufferedRequest] = []

    def track_workflow(
        self,
        workflow_name: str,
        workflow_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "WorkflowMonitor":
        return WorkflowMonitor(
            monitor=self,
            workflow_name=workflow_name,
            workflow_id=workflow_id or f"wf_{uuid.uuid4().hex}",
            metadata=metadata or {},
        )

    def track_stage(self, workflow_id: str, stage_name: str, **kwargs: Any) -> Dict[str, Any]:
        return self._send(
            "track_stage",
            {
                "workflow_id": workflow_id,
                "stage_name": stage_name,
                **kwargs,
            },
        )

    def log_model_call(self, workflow_id: str, model: str, success: bool, latency_ms: int, **kwargs: Any) -> Dict[str, Any]:
        return self._send(
            "log_model_call",
            {
                "workflow_id": workflow_id,
                "model": model,
                "success": success,
                "latency_ms": latency_ms,
                **kwargs,
            },
        )

    def log_tool_call(self, workflow_id: str, tool_name: str, success: bool, latency_ms: int, **kwargs: Any) -> Dict[str, Any]:
        return self._send(
            "log_tool_call",
            {
                "workflow_id": workflow_id,
                "tool_name": tool_name,
                "success": success,
                "latency_ms": latency_ms,
                **kwargs,
            },
        )

    def log_error(self, workflow_id: str, error_message: str, error_type: str = "error", **kwargs: Any) -> Dict[str, Any]:
        return self._send(
            "log_error",
            {
                "workflow_id": workflow_id,
                "error_type": error_type,
                "error_message": error_message,
                **kwargs,
            },
        )

    def get_tools(self, refresh: bool = False) -> Dict[str, Any]:
        return self.client.refresh_tools() if refresh else self.client.get_tools()

    def execute_tool(
        self,
        workflow_id: str,
        tool_slug: str,
        arguments: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self._send(
            "execute_tool",
            {
                "workflow_id": workflow_id,
                "tool_slug": tool_slug,
                "arguments": arguments or {},
                **kwargs,
            },
        )

    def predict_failure(self, workflow_id: str) -> Dict[str, Any]:
        return self._send("predict_failure", {"workflow_id": workflow_id})

    def apply_guardrail(self, workflow_id: str) -> Dict[str, Any]:
        prediction = self.predict_failure(workflow_id)
        return prediction.get("guardrail", {"action": "continue", "should_continue": True})

    def recover_workflow(self, workflow_id: str, auto_apply: bool = True) -> Dict[str, Any]:
        return self._send(
            "recover_workflow",
            {
                "workflow_id": workflow_id,
                "auto_apply": auto_apply,
            },
        )

    def complete_workflow(
        self,
        workflow_id: str,
        success: bool,
        confidence: float,
        total_latency_ms: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "workflow_id": workflow_id,
            "success": success,
            "confidence": confidence,
            "metadata": metadata or {},
        }
        if total_latency_ms is not None:
            payload["total_latency_ms"] = total_latency_ms
        return self._send("complete_workflow", payload)

    def flush(self) -> Dict[str, Any]:
        pending = list(self.buffer)
        self.buffer.clear()
        sent = 0
        failed = 0
        for item in pending:
            try:
                if item.method_name == "predict_failure":
                    self.client.predict_failure(item.payload["workflow_id"])
                elif item.method_name == "recover_workflow":
                    self.client.recover_workflow(item.payload)
                elif item.method_name == "execute_tool":
                    failed += 1
                    continue
                else:
                    getattr(self.client, item.method_name)(item.payload)
                sent += 1
            except SoftwareClientError as error:
                failed += 1
                self.buffer.append(BufferedRequest(item.method_name, item.payload, str(error)))
                if self.raise_on_error:
                    raise
        return {
            "sent": sent,
            "failed": failed,
            "remaining": len(self.buffer),
        }

    def _send(self, method_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if method_name == "predict_failure":
                return self.client.predict_failure(payload["workflow_id"])
            if method_name == "recover_workflow":
                return self.client.recover_workflow(payload)
            if method_name == "execute_tool":
                return self.client.execute_tool(payload)
            return getattr(self.client, method_name)(payload)
        except SoftwareClientError as error:
            if method_name == "execute_tool":
                return {
                    "ok": False,
                    "buffered": False,
                    "error": str(error),
                }
            self.buffer.append(BufferedRequest(method_name, payload, str(error)))
            if self.raise_on_error:
                raise
            return {
                "ok": False,
                "buffered": True,
                "error": str(error),
            }


@dataclass
class WorkflowMonitor:
    monitor: ReliabilityMonitor
    workflow_name: str
    workflow_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    current_stage: Optional[str] = None
    started_ms: int = field(default_factory=_now_ms)
    completed: bool = False
    available_tools: List[Dict[str, Any]] = field(default_factory=list)

    def __enter__(self) -> "WorkflowMonitor":
        response = self.monitor._send(
            "start_workflow",
            {
                "project_name": self.monitor.project_name,
                "workflow_name": self.workflow_name,
                "workflow_id": self.workflow_id,
                "metadata": self.metadata,
            },
        )
        if response.get("workflow_id"):
            self.workflow_id = response["workflow_id"]
        self.available_tools = list(response.get("agent_tools") or [])
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc is not None:
            self.log_error(
                "exception",
                "".join(traceback.format_exception_only(exc_type, exc)).strip(),
                fatal=True,
            )
            self.complete(success=False, confidence=0.0)
            return False
        if not self.completed:
            self.complete(success=True, confidence=1.0)
        return False

    def track_stage(
        self,
        stage_name: str,
        status: str = "started",
        success: Optional[bool] = None,
        latency_ms: Optional[int] = None,
        confidence: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.current_stage = stage_name
        payload: Dict[str, Any] = {
            "workflow_id": self.workflow_id,
            "stage_name": stage_name,
            "status": status,
            "metadata": metadata or {},
        }
        if success is not None:
            payload["success"] = success
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms
        if confidence is not None:
            payload["confidence"] = confidence
        return self.monitor._send("track_stage", payload)

    def log_model_call(
        self,
        model: str,
        success: bool,
        latency_ms: int,
        confidence: Optional[float] = None,
        stage_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "workflow_id": self.workflow_id,
            "model": model,
            "success": success,
            "latency_ms": latency_ms,
            "stage_name": stage_name or self.current_stage,
            "metadata": metadata or {},
        }
        if confidence is not None:
            payload["confidence"] = confidence
        return self.monitor._send("log_model_call", payload)

    def log_tool_call(
        self,
        tool_name: str,
        success: bool,
        latency_ms: int,
        result_count: Optional[int] = None,
        confidence: Optional[float] = None,
        stage_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "workflow_id": self.workflow_id,
            "tool_name": tool_name,
            "success": success,
            "latency_ms": latency_ms,
            "stage_name": stage_name or self.current_stage,
            "metadata": metadata or {},
        }
        if result_count is not None:
            payload["result_count"] = result_count
        if confidence is not None:
            payload["confidence"] = confidence
        return self.monitor._send("log_tool_call", payload)

    def log_error(
        self,
        error_type: str,
        error_message: str,
        fatal: bool = False,
        stage_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.monitor._send(
            "log_error",
            {
                "workflow_id": self.workflow_id,
                "error_type": error_type,
                "error_message": error_message,
                "stage_name": stage_name or self.current_stage,
                "fatal": fatal,
                "metadata": metadata or {},
            },
        )

    def predict_failure(self) -> Dict[str, Any]:
        return self.monitor.predict_failure(self.workflow_id)

    def apply_guardrail(self) -> Dict[str, Any]:
        return self.monitor.apply_guardrail(self.workflow_id)

    def recover(self, auto_apply: bool = True) -> Dict[str, Any]:
        return self.monitor.recover_workflow(self.workflow_id, auto_apply=auto_apply)

    def execute_tool(
        self,
        tool_slug: str,
        arguments: Optional[Dict[str, Any]] = None,
        account: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if account is not None:
            payload["account"] = account
        if agent_name is not None:
            payload["agent_name"] = agent_name
        return self.monitor.execute_tool(
            self.workflow_id,
            tool_slug,
            arguments,
            **payload,
        )

    def complete(
        self,
        success: bool,
        confidence: float,
        total_latency_ms: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.completed = True
        return self.monitor.complete_workflow(
            self.workflow_id,
            success=success,
            confidence=confidence,
            total_latency_ms=total_latency_ms,
            metadata=metadata or {},
        )
