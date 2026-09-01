from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlsplit


MATRIXS_PRODUCTION_API_URL = "https://software-reliability-engine.onrender.com"
MATRIXS_LOCAL_API_URL = "http://127.0.0.1:8000"
DEFAULT_API_URL = MATRIXS_PRODUCTION_API_URL
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


def _local_development_requested(environ: Mapping[str, str]) -> bool:
    mode = str(environ.get("MATRIXS_MODE") or "").strip().lower()
    enabled = str(environ.get("MATRIXS_LOCAL_DEVELOPMENT") or "").strip().lower()
    return mode in {"local", "development", "dev"} or enabled in {"1", "true", "yes", "on"}


def _normalized_api_url(value: Any, *, source: str, allow_loopback: bool) -> str:
    normalized = str(value or "").strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"{source} must be a valid http:// or https:// URL.")
    hostname = (parsed.hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1", "::1"} and not allow_loopback:
        raise ConfigError(
            f"{source} points to localhost. Set MATRIXS_MODE=local to explicitly enable local development."
        )
    return normalized


def resolve_matrixs_api_url(
    *configured_urls: Optional[Any],
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve one backend URL while preventing accidental localhost fallbacks."""

    values = os.environ if environ is None else environ
    local_mode = _local_development_requested(values)
    matrixs_override = str(values.get("MATRIXS_API_URL") or "").strip()
    if matrixs_override:
        return _normalized_api_url(
            matrixs_override,
            source="MATRIXS_API_URL",
            allow_loopback=local_mode,
        )
    if local_mode:
        local_url = str(values.get("MATRIXS_LOCAL_API_URL") or "").strip() or MATRIXS_LOCAL_API_URL
        return _normalized_api_url(
            local_url,
            source="MATRIXS_LOCAL_API_URL",
            allow_loopback=True,
        )

    # SOFTWARE_API_URL remains read-only compatibility for legacy installs.
    legacy_override = str(values.get("SOFTWARE_API_URL") or "").strip()
    if legacy_override:
        try:
            return _normalized_api_url(
                legacy_override,
                source="SOFTWARE_API_URL",
                allow_loopback=False,
            )
        except ConfigError:
            # Old local defaults must never pull a normal Matrixs connection
            # back to localhost.
            pass

    for configured_url in configured_urls:
        if configured_url is None or not str(configured_url).strip():
            continue
        try:
            return _normalized_api_url(
                configured_url,
                source="Saved Matrixs API URL",
                allow_loopback=False,
            )
        except ConfigError:
            # Ignore stale localhost values written by older Matrixs builds.
            continue
    return MATRIXS_PRODUCTION_API_URL


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
        "api_url": resolve_matrixs_api_url(
            secrets.get("MATRIXS_API_URL"),
            config.get("api_url"),
            global_config.get("api_url"),
        ),
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
