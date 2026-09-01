from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from matrixs.config import MATRIXS_PRODUCTION_API_URL, resolve_matrixs_api_url

from .client import SoftwareClient, SoftwareClientError
from .monitor import ReliabilityMonitor


CONFIG_DIR = Path.home() / ".software"
GLOBAL_CONFIG_PATH = CONFIG_DIR / "config.json"
PROJECT_CONFIG_PATH = Path("software.config.json")
DEFAULT_API_URL = MATRIXS_PRODUCTION_API_URL


class CLIError(RuntimeError):
    pass


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise CLIError(f"Invalid JSON in {path}: {error}") from error
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _default_project_name() -> str:
    cwd_name = Path.cwd().name.strip()
    return cwd_name or "software-agent"


def load_config() -> Dict[str, Any]:
    global_config = _read_json(GLOBAL_CONFIG_PATH)
    project_config = _read_json(PROJECT_CONFIG_PATH)
    api_url = resolve_matrixs_api_url(
        project_config.get("api_url"),
        global_config.get("api_url"),
    )
    api_key = (
        os.getenv("SOFTWARE_API_KEY")
        or project_config.get("api_key")
        or global_config.get("api_key")
        or ""
    )
    project_name = (
        os.getenv("SOFTWARE_PROJECT_NAME")
        or project_config.get("project_name")
        or global_config.get("project_name")
        or _default_project_name()
    )
    return {
        "api_url": api_url,
        "api_key": str(api_key),
        "project_name": str(project_name),
        "global_config_path": str(GLOBAL_CONFIG_PATH),
        "project_config_path": str(PROJECT_CONFIG_PATH.resolve()),
    }


def require_api_key(config: Dict[str, Any]) -> str:
    api_key = config.get("api_key", "")
    if not api_key:
        raise CLIError("No API key found. Run `software login` first.")
    return api_key


def command_login(args: argparse.Namespace) -> int:
    requested_url = args.api_url or input(f"Software API URL [{DEFAULT_API_URL}]: ").strip()
    api_url = resolve_matrixs_api_url(requested_url)
    api_key = args.api_key or getpass.getpass("Software API key: ").strip()
    if not api_key:
        raise CLIError("API key is required.")
    project_name = args.project_name or input(f"Default project name [{_default_project_name()}]: ").strip() or _default_project_name()

    client = SoftwareClient(api_url=api_url, api_key=api_key, timeout=args.timeout)
    try:
        status = client.status()
    except SoftwareClientError as error:
        raise CLIError(f"Login failed: {error}") from error

    _write_json(
        GLOBAL_CONFIG_PATH,
        {
            "api_url": api_url,
            "api_key": api_key,
            "project_name": project_name,
            "last_login_status": status,
        },
    )
    print("Software login saved.")
    print(f"API URL: {api_url}")
    print(f"Project: {project_name}")
    print(f"Config: {GLOBAL_CONFIG_PATH}")
    return 0


def command_init(args: argparse.Namespace) -> int:
    config = load_config()
    project_name = args.project_name or config["project_name"] or _default_project_name()
    api_url = resolve_matrixs_api_url(args.api_url, config["api_url"])
    output_path = Path(args.output)
    if output_path.exists() and not args.force:
        raise CLIError(f"{output_path} already exists. Use --force to overwrite it.")
    _write_json(
        output_path,
        {
            "project_name": project_name,
            "api_url": api_url,
            "sdk": "software-sdk",
            "config_version": 1,
        },
    )
    print(f"Created {output_path.resolve()}")
    print("API key is read from ~/.software/config.json or SOFTWARE_API_KEY.")
    return 0


def command_status(args: argparse.Namespace) -> int:
    config = load_config()
    api_key = require_api_key(config)
    client = SoftwareClient(api_url=config["api_url"], api_key=api_key, timeout=args.timeout)
    started = time.perf_counter()
    try:
        status = client.status()
    except SoftwareClientError as error:
        raise CLIError(f"Status check failed: {error}") from error
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    print("Software status: OK")
    print(f"API URL: {config['api_url']}")
    print(f"Project: {config['project_name']}")
    print(f"Latency: {latency_ms} ms")
    print(f"Dashboard: {status.get('dashboard_url', '/dashboard')}")
    project = status.get("project", {})
    if project:
        print(f"Connected project: {project.get('name')} ({project.get('id')})")
    return 0


def command_test(args: argparse.Namespace) -> int:
    config = load_config()
    api_key = require_api_key(config)
    workflow_name = args.workflow_name or "software-cli-test"
    started = time.perf_counter()
    monitor = ReliabilityMonitor(
        project_name=config["project_name"],
        api_url=config["api_url"],
        api_key=api_key,
        timeout=args.timeout,
        raise_on_error=True,
    )
    with monitor.track_workflow(
        workflow_name,
        metadata={
            "source": "software_cli",
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
    ) as workflow:
        workflow.track_stage("cli_test_start", status="completed", success=True, latency_ms=12, confidence=0.99)
        workflow.log_tool_call("software_cli", success=True, latency_ms=24, result_count=1, confidence=0.99)
        workflow.log_model_call("no_model_cli_test", success=True, latency_ms=10, confidence=0.99)
        total_latency_ms = int((time.perf_counter() - started) * 1000)
        response = workflow.complete(success=True, confidence=0.99, total_latency_ms=total_latency_ms)

    if monitor.buffer:
        raise CLIError(f"Test workflow buffered instead of sent: {monitor.buffer[0].error}")
    print("Software test workflow sent.")
    print(f"Workflow ID: {response.get('workflow_id')}")
    print(f"Failure probability: {response.get('probability_of_failure')}")
    print(f"Dashboard: {config['api_url']}/dashboard")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="software",
        description="Software SDK command line tools for AI-agent reliability monitoring.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="Save your Software API URL and API key locally.")
    login.add_argument("--api-url", help="Software API URL, for example https://software-platform.onrender.com")
    login.add_argument("--api-key", help="Software project API key. Omit to enter it securely.")
    login.add_argument("--project-name", help="Default project name for SDK workflows.")
    login.add_argument("--timeout", type=float, default=10.0)
    login.set_defaults(func=command_login)

    init = subparsers.add_parser("init", help="Create software.config.json in this project.")
    init.add_argument("--project-name", help="Project name to write into software.config.json.")
    init.add_argument("--api-url", help="Software API URL to write into software.config.json.")
    init.add_argument("--output", default="software.config.json", help="Config file path.")
    init.add_argument("--force", action="store_true", help="Overwrite existing config.")
    init.set_defaults(func=command_init)

    test = subparsers.add_parser("test", help="Send a test workflow to the Software dashboard.")
    test.add_argument("--workflow-name", help="Workflow name for the test event.")
    test.add_argument("--timeout", type=float, default=10.0)
    test.set_defaults(func=command_test)

    status = subparsers.add_parser("status", help="Check API connection and project status.")
    status.add_argument("--timeout", type=float, default=10.0)
    status.set_defaults(func=command_status)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except CLIError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except SoftwareClientError as error:
        print(f"Software API error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
