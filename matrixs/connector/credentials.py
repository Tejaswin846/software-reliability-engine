from __future__ import annotations

import getpass
import os
import platform
import socket
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from matrixs.client import MatrixsClient
from matrixs.config import DEFAULT_API_URL, load_project_connection

from .models import Credentials


def _value(*items: Optional[Any], default: str = "") -> str:
    for item in items:
        if item is not None and str(item).strip():
            return str(item).strip()
    return default


def obtain_credentials(
    project_root: Path,
    *,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
    api_url: Optional[str] = None,
    project_name: Optional[str] = None,
    connection_token: Optional[str] = None,
    timeout: float = 10.0,
    input_fn: Callable[[str], str] = input,
    secret_input_fn: Callable[[str], str] = getpass.getpass,
) -> Credentials:
    existing = load_project_connection(project_root)
    resolved_name = _value(project_name, existing.get("project_name"), default=project_root.name)
    resolved_url = _value(
        api_url,
        os.getenv("MATRIXS_API_URL"),
        os.getenv("SOFTWARE_API_URL"),
        existing.get("api_url"),
        default=DEFAULT_API_URL,
    ).rstrip("/")
    if connection_token:
        installation_id = f"inst_{uuid.uuid4().hex}"
        response = MatrixsClient(
            api_url=resolved_url,
            api_key="",
            timeout=timeout,
        ).post(
            "/api/sdk/connect/exchange",
            {
                "token": connection_token,
                "installation_id": installation_id,
                "device_label": socket.gethostname() or "Matrixs-connected device",
                "operating_system": platform.platform(),
                "runtime": f"Python {platform.python_version()}",
                "environment": os.getenv("MATRIXS_ENVIRONMENT", "development"),
                "metadata": {
                    "source": "matrixs_connect",
                    "python_implementation": platform.python_implementation(),
                    "executable": Path(sys.executable).name,
                },
            },
        )
        remote_project = response.get("project") or {}
        remote_installation = response.get("installation") or {}
        resolved_key = str(response.get("api_key") or "").strip()
        resolved_project_id = str(remote_project.get("id") or "").strip()
        resolved_project_name = str(remote_project.get("name") or project_name or project_root.name).strip()
        if not resolved_key or not resolved_project_id:
            raise ValueError("Matrixs Cloud returned an incomplete project connection.")
        return Credentials(
            project_id=resolved_project_id,
            api_key=resolved_key,
            api_url=resolved_url,
            project_name=resolved_project_name,
            installation_id=str(remote_installation.get("id") or installation_id),
        )
    resolved_project_id = _value(
        project_id,
        os.getenv("MATRIXS_PROJECT_ID"),
        existing.get("project_id"),
    )
    if not resolved_project_id:
        resolved_project_id = input_fn("Matrixs Project ID: ").strip()
    if not resolved_project_id:
        raise ValueError("Matrixs Project ID is required.")
    resolved_key = _value(
        api_key,
        os.getenv("MATRIXS_API_KEY"),
        os.getenv("SOFTWARE_API_KEY"),
        existing.get("api_key"),
    )
    if not resolved_key:
        resolved_key = secret_input_fn("Matrixs API Key: ").strip()
    if not resolved_key:
        raise ValueError("Matrixs API key is required.")
    installation_id = _value(
        os.getenv("MATRIXS_INSTALLATION_ID"),
        existing.get("installation_id"),
        default=f"inst_{uuid.uuid4().hex}",
    )
    return Credentials(
        project_id=resolved_project_id,
        api_key=resolved_key,
        api_url=resolved_url,
        project_name=resolved_name,
        installation_id=installation_id,
    )
