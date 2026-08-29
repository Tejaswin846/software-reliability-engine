from __future__ import annotations

import platform
import socket
from typing import Any, Dict

from matrixs.client import MatrixsClient

from .models import Credentials


def verify_connection(credentials: Credentials, timeout: float = 10.0) -> Dict[str, Any]:
    client = MatrixsClient(
        api_url=credentials.api_url,
        api_key=credentials.api_key,
        timeout=timeout,
    )
    status = client.status()
    remote_project = status.get("project") or {}
    remote_project_id = str(remote_project.get("id") or "")
    if remote_project_id and remote_project_id != credentials.project_id:
        raise RuntimeError(
            "The Matrixs API key belongs to project "
            f"{remote_project_id}, not {credentials.project_id}."
        )
    test_event = client.post(
        "/api/sdk/test-workflow",
        {
            "project_name": credentials.project_name,
            "workflow_name": "matrixs-connection-test",
            "metadata": {
                "source": "matrixs_connect",
                "installation_id": credentials.installation_id,
                "device_label": socket.gethostname() or "Matrixs-connected device",
                "operating_system": platform.platform(),
                "runtime": f"Python {platform.python_version()}",
                "python_version": platform.python_version(),
                "platform": platform.platform(),
            },
        },
    )
    return {"status": status, "test_event": test_event}
