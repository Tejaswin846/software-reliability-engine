from __future__ import annotations

import os
import platform
import socket
from pathlib import Path
from typing import Any, Dict

from matrixs.client import MatrixsClient
from matrixs.config import parse_dotenv, project_config_path, project_env_path, read_json

from .models import Credentials, IntegrationPlan


def _client(credentials: Credentials, timeout: float) -> MatrixsClient:
    return MatrixsClient(
        api_url=credentials.api_url,
        api_key=credentials.api_key,
        timeout=timeout,
    )


def validate_credentials(credentials: Credentials, timeout: float = 10.0) -> Dict[str, Any]:
    status = _client(credentials, timeout).status()
    remote_project = status.get("project") or {}
    remote_project_id = str(remote_project.get("id") or "")
    if not remote_project_id:
        raise RuntimeError("Matrixs did not return a project for this API key.")
    if remote_project_id != credentials.project_id:
        raise RuntimeError(
            "The Matrixs API key belongs to project "
            f"{remote_project_id}, not {credentials.project_id}."
        )
    return status


def check_cloud_health(credentials: Credentials, timeout: float = 10.0) -> Dict[str, Any]:
    health = _client(credentials, timeout).get("/health")
    if str(health.get("service") or "").lower() != "matrixs":
        raise RuntimeError("The configured backend did not identify itself as Matrixs.")
    return health


def validate_api_key_status(status: Dict[str, Any]) -> Dict[str, Any]:
    api_key = status.get("api_key") or {}
    if not str(api_key.get("id") or "").strip():
        raise RuntimeError("Matrixs did not confirm the supplied API key.")
    return api_key


def _installation_payload(credentials: Credentials) -> Dict[str, Any]:
    return {
        "installation_id": credentials.installation_id,
        "device_label": socket.gethostname() or "Matrixs-connected device",
        "operating_system": platform.platform(),
        "runtime": f"Python {platform.python_version()}",
        "environment": os.getenv("MATRIXS_ENVIRONMENT", "development"),
        "metadata": {"source": "matrixs_connect"},
    }


def register_installation(credentials: Credentials, timeout: float = 10.0) -> Dict[str, Any]:
    return _client(credentials, timeout).post(
        "/api/sdk/installations/register",
        _installation_payload(credentials),
    )


def disconnect_installation(credentials: Credentials, timeout: float = 10.0) -> Dict[str, Any]:
    return _client(credentials, timeout).post(
        "/api/sdk/installations/disconnect",
        _installation_payload(credentials),
    )


def send_test_event(credentials: Credentials, timeout: float = 10.0) -> Dict[str, Any]:
    return _client(credentials, timeout).post(
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


def _startup_target_exists(root: Path, command: list[str]) -> bool:
    if not command:
        return False
    if len(command) >= 2 and command[0].lower().startswith("python") and command[1].endswith(".py"):
        return (root / command[1]).is_file()
    if "uvicorn" in command:
        target = command[-1].split(":", 1)[0].replace(".", "/")
        return (root / f"{target}.py").is_file() or (root / target / "__init__.py").is_file()
    if len(command) >= 3 and command[1] == "-m":
        module = command[2].replace(".", "/")
        return (root / f"{module}.py").is_file() or (root / module).is_dir()
    return True


def verify_local_integration(plan: IntegrationPlan) -> Dict[str, Any]:
    root = plan.project_root.resolve()
    config = read_json(project_config_path(root))
    secrets = parse_dotenv(project_env_path(root))
    if config.get("project_id") != plan.credentials.project_id:
        raise RuntimeError("Saved Matrixs project configuration does not match the selected project.")
    if secrets.get("MATRIXS_API_KEY") != plan.credentials.api_key:
        raise RuntimeError("Matrixs API key was not saved correctly.")
    bootstrap = root / ".matrixs" / "runtime" / "sitecustomize.py"
    if not bootstrap.is_file():
        raise RuntimeError("Matrixs runtime bootstrap was not created.")
    compile(bootstrap.read_text(encoding="utf-8"), str(bootstrap), "exec")
    from matrixs.runtime.instrumentation import activate_from_environment

    if not callable(activate_from_environment):
        raise RuntimeError("Matrixs runtime instrumentation could not be loaded.")
    startup_command = list(config.get("startup_command") or [])
    if not _startup_target_exists(root, startup_command):
        raise RuntimeError("Detected application startup configuration is not valid.")
    return {
        "bootstrap": bootstrap.relative_to(root).as_posix(),
        "startup_command": startup_command,
    }


def verify_connection(credentials: Credentials, timeout: float = 10.0) -> Dict[str, Any]:
    health = check_cloud_health(credentials, timeout=timeout)
    status = validate_credentials(credentials, timeout=timeout)
    validate_api_key_status(status)
    test_event = send_test_event(credentials, timeout=timeout)
    return {"health": health, "status": status, "test_event": test_event}
