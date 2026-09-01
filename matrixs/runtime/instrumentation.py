from __future__ import annotations

import atexit
import os
import platform
import socket
import time
import uuid
from typing import Optional

from matrixs.config import resolve_matrixs_api_url
from matrixs.monitor import ReliabilityMonitor, WorkflowMonitor


_SESSION: Optional[WorkflowMonitor] = None
_STARTED_AT = 0.0
_RUNTIME_SESSION_ID = f"session_{uuid.uuid4().hex}"


def _runtime_metadata() -> dict[str, object]:
    return {
        "source": "matrixs_runtime",
        "installation_id": os.getenv("MATRIXS_INSTALLATION_ID", ""),
        "device_label": socket.gethostname() or "Matrixs-connected device",
        "operating_system": platform.platform(),
        "runtime": f"Python {platform.python_version()}",
        "environment": os.getenv("MATRIXS_ENVIRONMENT", "development"),
        "session_id": _RUNTIME_SESSION_ID,
    }


def _complete_session() -> None:
    global _SESSION
    if _SESSION is None:
        return
    elapsed_ms = int((time.perf_counter() - _STARTED_AT) * 1000)
    try:
        _SESSION.complete(
            success=True,
            confidence=1.0,
            total_latency_ms=max(0, elapsed_ms),
            metadata=_runtime_metadata(),
        )
    except Exception:
        pass
    _SESSION = None


def activate_from_environment() -> bool:
    global _SESSION, _STARTED_AT
    if _SESSION is not None or os.getenv("MATRIXS_RUNTIME_ACTIVE") == "1":
        return False
    api_key = os.getenv("MATRIXS_API_KEY", "").strip()
    api_url = resolve_matrixs_api_url()
    project_name = os.getenv("MATRIXS_PROJECT_NAME", "").strip()
    if not api_key or not project_name:
        return False
    os.environ["MATRIXS_RUNTIME_ACTIVE"] = "1"
    monitor = ReliabilityMonitor(
        project_name=project_name,
        api_url=api_url,
        api_key=api_key,
        timeout=2.0,
        raise_on_error=False,
    )
    session = monitor.track_workflow(
        "matrixs-runtime-session",
        metadata={**_runtime_metadata(), "auto_instrument": True},
    )
    try:
        session.__enter__()
        session.track_stage(
            "runtime_attached",
            status="completed",
            success=True,
            confidence=1.0,
            metadata={"adapters": os.getenv("MATRIXS_ADAPTERS", "")},
        )
    except Exception:
        return False
    _SESSION = session
    _STARTED_AT = time.perf_counter()
    atexit.register(_complete_session)
    return True
