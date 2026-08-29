from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path
from typing import Callable, Optional, Sequence

from matrixs.client import MatrixsClient, MatrixsClientError
from matrixs.config import (
    GLOBAL_CONFIG_PATH,
    load_project_connection,
    project_config_path,
    read_json,
    write_global_config,
)
from matrixs.connector.analyzer import analyze_project
from matrixs.connector.backup import create_backup, find_backup, latest_backup, new_backup_id
from matrixs.connector.browser_setup import collect_credentials_in_browser
from matrixs.connector.credentials import obtain_credentials
from matrixs.connector.discover import discover_projects, inspect_project
from matrixs.connector.models import IntegrationPlan, ProjectCandidate
from matrixs.connector.operations import apply_plan, rollback_backup
from matrixs.connector.permissions import request_integration_permission
from matrixs.connector.planner import build_integration_plan
from matrixs.connector.verify import verify_connection
from matrixs.runtime.launcher import run_project


MANUAL_GUIDE_URL = "https://software-reliability-engine.onrender.com/developer-docs/sdk-usage"


class CLIError(RuntimeError):
    pass


def _project_label(candidate: ProjectCandidate) -> str:
    framework = candidate.framework if candidate.framework != "python" else "Python"
    return f"{candidate.path.name:<22} Python / {framework.title()}"


def _choose_project(candidates: Sequence[ProjectCandidate], selection: Optional[int]) -> ProjectCandidate:
    if not candidates:
        raise CLIError("No supported Python project was found. Use --path to provide the project folder.")
    if len(candidates) == 1:
        candidate = candidates[0]
        print(f"Project found: {_project_label(candidate)}")
        print(f"  {candidate.path}")
        return candidate
    print("Projects found:")
    for index, candidate in enumerate(candidates, start=1):
        print(f"[{index}] {_project_label(candidate)}")
        print(f"    {candidate.path}")
    selected = selection
    while selected is None:
        raw = input("Choose a project: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(candidates):
            selected = int(raw)
        else:
            print(f"Choose a number from 1 to {len(candidates)}.")
    if selected < 1 or selected > len(candidates):
        raise CLIError(f"Project selection must be from 1 to {len(candidates)}.")
    return candidates[selected - 1]


def _discover_or_prompt(
    start: Path,
    *,
    max_depth: int,
    selection: Optional[int],
    allow_prompt: bool,
    input_fn: Callable[[str], str] = input,
) -> Optional[ProjectCandidate]:
    search_root = start
    while True:
        candidates = discover_projects(search_root, max_depth=max_depth)
        if candidates:
            return _choose_project(candidates, selection)
        print("No project found.")
        if not allow_prompt:
            raise CLIError("Use --path to provide a supported Python project folder.")
        print("[1] Search another folder")
        print("[2] Enter project path manually")
        print("[3] Exit")
        choice = input_fn("Choose: ").strip()
        if choice == "1":
            search_root = Path(input_fn("Folder to search: ").strip()).expanduser().resolve()
            selection = None
            continue
        if choice == "2":
            manual_path = Path(input_fn("Project path: ").strip()).expanduser().resolve()
            candidate = inspect_project(manual_path)
            if candidate is not None:
                return candidate
            print(f"No supported Python project found at {manual_path}.")
            continue
        if choice == "3":
            return None
        print("Choose 1, 2, or 3.")


def _open_manual_guide() -> None:
    print(f"Manual Matrixs integration guide: {MANUAL_GUIDE_URL}")
    try:
        webbrowser.open(MANUAL_GUIDE_URL)
    except Exception:
        pass


def _show_plan(plan: IntegrationPlan) -> None:
    print("Matrixs integration plan:")
    if not plan.changes:
        print("- no file changes are required")
        return
    for change in plan.changes:
        relative = change.path.relative_to(plan.project_root)
        suffix = " (secret; contents hidden)" if change.sensitive else ""
        print(f"- {change.action}: {relative}{suffix}")


def command_connect(args: argparse.Namespace) -> int:
    if args.manual:
        print("Matrixs automatic integration was not started.")
        _open_manual_guide()
        return 0
    start = Path(args.path or Path.cwd()).expanduser().resolve()
    print("Matrixs project connector")
    print(f"Searching {start} and controlled subfolders...")
    candidate = _discover_or_prompt(
        start,
        max_depth=args.max_depth,
        selection=args.selection,
        allow_prompt=sys.stdin.isatty(),
    )
    if candidate is None:
        print("Matrixs connector closed without changing a project.")
        return 0
    if not args.yes:
        allowed = request_integration_permission(
            candidate.path,
            open_manual_guide=_open_manual_guide,
        )
        if not allowed:
            return 0
    print("Permission granted.")
    print("Analyzing project...")
    analysis = analyze_project(candidate.path)
    print(
        "Detected "
        f"{analysis.runtime} / {analysis.framework}; adapters: {', '.join(analysis.adapters)}"
    )
    existing = load_project_connection(candidate.path)
    known_project_id = args.project_id or existing.get("project_id") or ""
    if args.token or (args.project_id and args.api_key):
        credentials = obtain_credentials(
            candidate.path,
            project_id=args.project_id,
            api_key=args.api_key,
            api_url=args.api_url,
            project_name=args.project_name,
            connection_token=args.token,
            timeout=args.timeout,
        )
    else:
        credentials = collect_credentials_in_browser(
            candidate.path,
            project_id=known_project_id,
            project_name=args.project_name or existing.get("project_name") or candidate.path.name,
            api_url=args.api_url or existing.get("api_url") or "",
            timeout=args.setup_timeout,
        )
    backup_id = new_backup_id()
    plan = build_integration_plan(analysis, credentials, backup_id=backup_id)
    _show_plan(plan)
    if args.dry_run:
        print("Dry run complete. No files were changed.")
        return 0
    backup_dir = create_backup(plan.project_root, plan.changes, backup_id)
    print(f"Backup created: {backup_dir.relative_to(plan.project_root)}")
    try:
        changed = apply_plan(plan)
        print(f"Applied {len(changed)} Matrixs integration change(s).")
        verification = None if args.no_verify else verify_connection(credentials, timeout=args.timeout)
    except Exception:
        rollback_backup(plan.project_root, backup_dir)
        print("Integration failed. Matrixs restored the project from its backup.", file=sys.stderr)
        raise
    print(f"{credentials.project_name} is connected to Matrixs.")
    print("Start the application with: matrixs run")
    if verification:
        test_event = verification.get("test_event") or {}
        print(f"Connection test passed: {test_event.get('workflow_id', 'verified')}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    root = Path(args.path or Path.cwd()).expanduser().resolve()
    path = project_config_path(root)
    if not path.is_file():
        print(f"Matrixs status: not connected ({root})")
        return 1
    config = read_json(path)
    connection = load_project_connection(root)
    print("Matrixs status: connected")
    print(f"Project: {config.get('project_name')} ({config.get('project_id')})")
    print(f"Framework: {config.get('framework')}")
    print(f"Adapters: {', '.join(config.get('adapters') or [])}")
    print(f"Startup: {' '.join(config.get('startup_command') or [])}")
    if not args.offline:
        if not connection.get("api_key"):
            raise CLIError("Matrixs API key is missing from .matrixs/.env.")
        result = verify_connection(
            obtain_credentials(
                root,
                project_id=connection["project_id"],
                api_key=connection["api_key"],
                api_url=connection["api_url"],
                project_name=connection["project_name"],
            ),
            timeout=args.timeout,
        )
        print(f"Matrixs Cloud: OK ({(result.get('status') or {}).get('service', 'Matrixs')})")
    return 0


def command_undo(args: argparse.Namespace) -> int:
    root = Path(args.path or Path.cwd()).expanduser().resolve()
    backup_dir = latest_backup(root)
    if backup_dir is None:
        raise CLIError("No Matrixs backup is available to undo.")
    restored = rollback_backup(root, backup_dir)
    print(f"Restored {len(restored)} path(s) from {backup_dir.name}.")
    return 0


def command_disconnect(args: argparse.Namespace) -> int:
    root = Path(args.path or Path.cwd()).expanduser().resolve()
    config = read_json(project_config_path(root))
    backup_id = str(config.get("integration_backup") or "")
    if not backup_id:
        raise CLIError("This project does not contain a Matrixs integration backup reference.")
    backup_dir = find_backup(root, backup_id)
    if backup_dir is None:
        raise CLIError(f"Matrixs integration backup {backup_id} is missing.")
    restored = rollback_backup(root, backup_dir)
    print(f"Matrixs disconnected. Restored {len(restored)} path(s); customer files were preserved.")
    return 0


def command_run(args: argparse.Namespace) -> int:
    root = Path(args.path or Path.cwd()).expanduser().resolve()
    return run_project(root, args.application_command or None)


def command_login(args: argparse.Namespace) -> int:
    api_url = (args.api_url or input("Matrixs API URL: ").strip()).rstrip("/")
    api_key = args.api_key
    if not api_key:
        import getpass

        api_key = getpass.getpass("Matrixs API Key: ").strip()
    if not api_url or not api_key:
        raise CLIError("API URL and API key are required.")
    project_id = args.project_id
    project_name = args.project_name
    if not project_id:
        status = MatrixsClient(api_url=api_url, api_key=api_key, timeout=args.timeout).status()
        remote_project = status.get("project") or {}
        project_id = str(remote_project.get("id") or "")
        project_name = project_name or str(remote_project.get("name") or "")
    if not project_id:
        raise CLIError("Matrixs Cloud did not return a project ID for this API key.")
    write_global_config(
        {
            "api_url": api_url,
            "project_id": project_id,
            "project_name": project_name or "",
            "api_key": api_key,
        }
    )
    print(f"Matrixs login saved to {GLOBAL_CONFIG_PATH}.")
    return 0


def command_test(args: argparse.Namespace) -> int:
    root = Path(args.path or Path.cwd()).expanduser().resolve()
    connection = load_project_connection(root)
    credentials = obtain_credentials(
        root,
        project_id=connection.get("project_id"),
        api_key=connection.get("api_key"),
        api_url=connection.get("api_url"),
        project_name=connection.get("project_name"),
    )
    result = verify_connection(credentials, timeout=args.timeout)
    print(f"Matrixs test passed: {(result.get('test_event') or {}).get('workflow_id', 'verified')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="matrixs",
        description="Matrixs zero-code project integration and reliability monitoring.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    connect = subparsers.add_parser("connect", help="Discover and connect a Python project to Matrixs.")
    connect.add_argument("--path", help="Folder to search. Defaults to the current folder.")
    connect.add_argument("--selection", type=int, help="Select a discovered project by its displayed number.")
    connect.add_argument("--max-depth", type=int, default=3, help="Maximum controlled subfolder search depth.")
    connect.add_argument("--yes", action="store_true", help="Grant integration permission non-interactively.")
    connect.add_argument("--manual", action="store_true", help="Open the manual integration guide without changing files.")
    connect.add_argument("--project-id", help="Matrixs Cloud project ID.")
    connect.add_argument("--project-name", help="Display name for the connected project.")
    connect.add_argument("--api-url", help="Matrixs Cloud API base URL.")
    connect.add_argument("--api-key", help="Matrixs API key. Prefer MATRIXS_API_KEY or the masked prompt.")
    connect.add_argument("--token", help="Short-lived one-time connection token generated by Matrixs Cloud.")
    connect.add_argument("--timeout", type=float, default=10.0)
    connect.add_argument("--setup-timeout", type=float, default=600.0, help="Seconds to wait for the local credential page.")
    connect.add_argument("--no-verify", action="store_true", help="Skip the Matrixs Cloud connection test.")
    connect.add_argument("--dry-run", action="store_true", help="Show the integration plan without changing files.")
    connect.set_defaults(func=command_connect)

    status = subparsers.add_parser("status", help="Show the local and Matrixs Cloud connection state.")
    status.add_argument("--path")
    status.add_argument("--offline", action="store_true", help="Do not contact Matrixs Cloud.")
    status.add_argument("--timeout", type=float, default=10.0)
    status.set_defaults(func=command_status)

    disconnect = subparsers.add_parser("disconnect", help="Remove Matrixs integration using its original backup.")
    disconnect.add_argument("--path")
    disconnect.set_defaults(func=command_disconnect)

    undo = subparsers.add_parser("undo", help="Restore the latest Matrixs backup.")
    undo.add_argument("--path")
    undo.set_defaults(func=command_undo)

    run = subparsers.add_parser("run", help="Run the project with Matrixs runtime attachment.")
    run.add_argument("--path")
    run.add_argument("application_command", nargs=argparse.REMAINDER)
    run.set_defaults(func=command_run)

    login = subparsers.add_parser("login", help="Save Matrixs Cloud credentials for future connections.")
    login.add_argument("--api-url")
    login.add_argument("--project-id")
    login.add_argument("--project-name")
    login.add_argument("--api-key")
    login.add_argument("--timeout", type=float, default=10.0)
    login.set_defaults(func=command_login)

    test = subparsers.add_parser("test", help="Send a verified test event to Matrixs Cloud.")
    test.add_argument("--path")
    test.add_argument("--timeout", type=float, default=10.0)
    test.set_defaults(func=command_test)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (CLIError, MatrixsClientError, ValueError, RuntimeError, OSError) as error:
        print(f"Matrixs error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
