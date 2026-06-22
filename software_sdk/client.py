from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class SoftwareClientError(RuntimeError):
    pass


class SoftwareClient:
    def __init__(self, api_url: str, api_key: str, timeout: float = 10.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_url}{path}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Software-API-Key": self.api_key,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise SoftwareClientError(f"Software API returned {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise SoftwareClientError(f"Software API is unreachable: {error}") from error

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise SoftwareClientError(f"Software API returned invalid JSON: {raw[:200]}") from error
        if not parsed.get("ok", False):
            raise SoftwareClientError(f"Software API rejected request: {parsed}")
        return parsed

    def start_workflow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/api/sdk/workflows/start", payload)

    def track_stage(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/api/sdk/workflows/stage", payload)

    def log_model_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/api/sdk/workflows/model-call", payload)

    def log_tool_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/api/sdk/workflows/tool-call", payload)

    def log_error(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/api/sdk/workflows/error", payload)

    def complete_workflow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/api/sdk/workflows/complete", payload)

    def predict_failure(self, workflow_id: str) -> Dict[str, Any]:
        return self.post("/api/sdk/workflows/predict", {"workflow_id": workflow_id})

    def recover_workflow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/api/sdk/workflows/recover", payload)
