from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


DEFAULT_API_URL = "https://software-reliability-engine.onrender.com"
MATRIXS_DIR_NAME = ".matrixs"
PROJECT_CONFIG_NAME = "config.json"
PROJECT_ENV_NAME = ".env"
GLOBAL_CONFIG_PATH = Path.home() / MATRIXS_DIR_NAME / "config.json"
LEGACY_GLOBAL_CONFIG_PATH = Path.home() / ".software" / "config.json"


class ConfigError(RuntimeError):
    pass


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"Invalid Matrixs configuration at {path}: {error}") from error
    if not isinstance(value, dict):
        raise ConfigError(f"Matrixs configuration at {path} must be a JSON object.")
    return value


def project_config_path(project_root: Path) -> Path:
    return project_root / MATRIXS_DIR_NAME / PROJECT_CONFIG_NAME


def project_env_path(project_root: Path) -> Path:
    return project_root / MATRIXS_DIR_NAME / PROJECT_ENV_NAME


def parse_dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _first(*values: Optional[Any], default: str = "") -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def load_global_config() -> Dict[str, Any]:
    if GLOBAL_CONFIG_PATH.exists():
        return read_json(GLOBAL_CONFIG_PATH)
    return read_json(LEGACY_GLOBAL_CONFIG_PATH)


def load_project_connection(project_root: Path) -> Dict[str, str]:
    root = project_root.resolve()
    config = read_json(project_config_path(root))
    secrets = parse_dotenv(project_env_path(root))
    global_config = load_global_config()
    return {
        "api_url": _first(
            os.getenv("MATRIXS_API_URL"),
            os.getenv("SOFTWARE_API_URL"),
            secrets.get("MATRIXS_API_URL"),
            config.get("api_url"),
            global_config.get("api_url"),
            default=DEFAULT_API_URL,
        ).rstrip("/"),
        "api_key": _first(
            os.getenv("MATRIXS_API_KEY"),
            os.getenv("SOFTWARE_API_KEY"),
            secrets.get("MATRIXS_API_KEY"),
            global_config.get("api_key"),
        ),
        "project_id": _first(
            os.getenv("MATRIXS_PROJECT_ID"),
            secrets.get("MATRIXS_PROJECT_ID"),
            config.get("project_id"),
            global_config.get("project_id"),
        ),
        "project_name": _first(
            os.getenv("MATRIXS_PROJECT_NAME"),
            os.getenv("SOFTWARE_PROJECT_NAME"),
            secrets.get("MATRIXS_PROJECT_NAME"),
            config.get("project_name"),
            global_config.get("project_name"),
            default=root.name,
        ),
        "installation_id": _first(
            os.getenv("MATRIXS_INSTALLATION_ID"),
            secrets.get("MATRIXS_INSTALLATION_ID"),
            config.get("installation_id"),
            global_config.get("installation_id"),
        ),
    }


def write_global_config(values: Mapping[str, Any]) -> None:
    GLOBAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    GLOBAL_CONFIG_PATH.write_text(
        json.dumps(dict(values), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        GLOBAL_CONFIG_PATH.chmod(0o600)
    except OSError:
        pass
