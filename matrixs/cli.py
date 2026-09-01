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
    resolve_matrixs_api_url,
    write_global_config,
)
from matrixs.connector.analyzer import analyze_project
from matrixs.connector.backup import create_backup, find_backup, latest_backup, new_backup_id
from matrixs.connector.browser_setup import collect_credentials_in_browser
from matrixs.connector.credentials import obtain_credentials
from matrixs.connector.discover import discover_projects, inspect_project
from matrixs.connector.models import Credentials, IntegrationPlan, ProjectCandidate
from matrixs.connector.operations import apply_plan, rollback_backup
from matrixs.connector.permissions import request_integration_permission
from matrixs.connector.planner import build_integration_plan
from matrixs.connector.verify import (
    check_cloud_health,
    disconnect_installation,
    register_installation,
    send_test_event,
    validate_api_key_status,
    validate_credentials,
    verify_connection,
    verify_local_integration,
)
from matrixs.runtime.launcher import run_project


MANUAL_GUIDE_URL = "https://software-reliability-engine.onrender.com/developer-docs/sdk-usage"


class CLIError(RuntimeError):
    pass


def _project_label(candidate: ProjectCandidate) -> str:
    framework = candidate.framework if candidate.framework != "python" else "Python"
    return f"{candidate.path.name:<22} Python / {framework.title()}"


def _choose_project(
    candidates: Sequence[ProjectCandidate],
    selection: Optional[int],
    *,
    input_fn: Callable[[str], str] = input,
) -> ProjectCandidate:
    if not candidates:
        raise CLIError("No supported Python project was found. Use --path to provide the project folder.")
    if len(candidates) == 1:
        candidate = candidates[0]
        print(f"Project found: {_project_label(candidate)}")
        return candidate
    print("Projects found:")
    for index, candidate in enumerate(candidates, start=1):
        print(f"[{index}] {_project_label(candidate)}")
    selected = selection
    while selected is None:
        raw = input_fn("Choose a project: ").strip()
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
            return _choose_project(candidates, selection, input_fn=input_fn)
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


def _terminal_symbol(symbol: str, fallback: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        symbol.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return fallback
    return symbol


def _run_progress(label: str, action: Callable[[], object]) -> object:
    print(f"{label:<40}", end="", flush=True)
    try:
        result = action()
    except Exception:
        print("x")
        raise
    print(_terminal_symbol("\u2713", "[OK]"))
    return result


def _complete_progress(label: str) -> None:
    print(f"{label:<40}{_terminal_symbol(chr(0x2713), '[OK]')}")


def command_connect(args: argparse.Namespace) -> int:
    if args.manual:
        print("Matrixs automatic integration was not started.")
        _open_manual_guide()
        return 0
    start = Path(args.path or Path.cwd()).expanduser().resolve()
    resolved_api_url = resolve_matrixs_api_url()
    print("Matrixs project connector")
    print("Matrixs Cloud:")
    print(resolved_api_url)
    location = "." if start == Path.cwd().resolve() else start.name
    print(f"Searching {location} and controlled subfolders...")
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
    analysis = _run_progress("Detecting application...", lambda: analyze_project(candidate.path))
    assert hasattr(analysis, "runtime")
    print(
        "Detected "
        f"{analysis.runtime} / {analysis.framework}; adapters: {', '.join(analysis.adapters)}"
    )
    libraries = ", ".join(analysis.ai_libraries) or "none detected"
    print(f"AI libraries: {libraries}")
    existing = load_project_connection(candidate.path)
    if args.dry_run:
        preview_credentials = Credentials(
            project_id=existing.get("project_id") or "project-id-entered-in-browser",
            api_key="secret-entered-in-browser",
            api_url=resolved_api_url,
            project_name=existing.get("project_name") or candidate.path.name,
            installation_id="installation-created-after-validation",
        )
        preview_plan = build_integration_plan(analysis, preview_credentials, backup_id=new_backup_id())
        _show_plan(preview_plan)
        print("Dry run complete. No browser was opened and no files were changed.")
        return 0

    def validate_for_browser(credentials: Credentials) -> object:
        _run_progress(
            "Connecting to Matrixs Cloud...",
            lambda: check_cloud_health(credentials, timeout=args.timeout),
        )
        status = _run_progress(
            "Validating Project ID...",
            lambda: validate_credentials(credentials, timeout=args.timeout),
        )
        assert isinstance(status, dict)
        _run_progress("Validating API key...", lambda: validate_api_key_status(status))
        return status

    credentials = collect_credentials_in_browser(
        candidate.path,
        project_id=existing.get("project_id") or "",
        project_name=existing.get("project_name") or candidate.path.name,
        api_url=resolved_api_url,
        timeout=args.setup_timeout,
        validator=validate_for_browser,
    )
    _complete_progress("Credentials received...")
    _run_progress(
        "Registering installation...",
        lambda: register_installation(credentials, timeout=args.timeout),
    )
    backup_id = new_backup_id()
    plan = build_integration_plan(analysis, credentials, backup_id=backup_id)
    _show_plan(plan)
    backup_dir = _run_progress(
        "Creating backup...",
        lambda: create_backup(plan.project_root, plan.changes, backup_id),
    )
    assert isinstance(backup_dir, Path)
    runtime_changes = [
        change
        for change in plan.changes
        if change.path.relative_to(plan.project_root).parts[:2] == (".matrixs", "runtime")
    ]
    configuration_changes = [change for change in plan.changes if change not in runtime_changes]
    try:
        runtime_changed = _run_progress(
            "Adding Matrixs integration...",
            lambda: apply_plan(plan, runtime_changes),
        )
        configuration_changed = _run_progress(
            "Saving configuration...",
            lambda: apply_plan(plan, configuration_changes),
        )

        test_event = _run_progress(
            "Testing telemetry...",
            lambda: send_test_event(credentials, timeout=args.timeout),
        )
        local_verification = _run_progress(
            "Integration verified...",
            lambda: verify_local_integration(plan),
        )
        verification = {"local": local_verification, "test_event": test_event}
    except Exception:
        rollback_backup(plan.project_root, backup_dir)
        print("Integration failed. Matrixs restored the project from its backup.", file=sys.stderr)
        raise
    changed_count = len(runtime_changed) + len(configuration_changed)
    print("Project connected successfully.")
    print(f"Project: {credentials.project_name} ({credentials.project_id})")
    print(f"Applied {changed_count} reversible Matrixs integration change(s).")
    print("Start the application with: matrixs run")
    if isinstance(verification, dict):
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
    print(f"Matrixs Cloud: {connection['api_url']}")
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
    connection = load_project_connection(root)
    print(f"Matrixs Cloud: {connection['api_url']}")
    if connection.get("api_key") and connection.get("installation_id"):
        credentials = Credentials(
            project_id=connection["project_id"],
            api_key=connection["api_key"],
            api_url=connection["api_url"],
            project_name=connection["project_name"],
            installation_id=connection["installation_id"],
        )
        try:
            _run_progress(
                "Disconnecting from Matrixs Cloud...",
                lambda: disconnect_installation(credentials, timeout=args.timeout),
            )
        except MatrixsClientError as error:
            print(f"Matrixs Cloud disconnect warning: {error}", file=sys.stderr)
    restored = rollback_backup(root, backup_dir)
    print(f"Matrixs disconnected. Restored {len(restored)} path(s); customer files were preserved.")
    return 0


def command_run(args: argparse.Namespace) -> int:
    root = Path(args.path or Path.cwd()).expanduser().resolve()
    return run_project(root, args.application_command or None)


def command_login(args: argparse.Namespace) -> int:
    api_url = resolve_matrixs_api_url(args.api_url)
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
    connect.add_argument("--timeout", type=float, default=10.0)
    connect.add_argument("--setup-timeout", type=float, default=600.0, help="Seconds to wait for the local credential page.")
    connect.add_argument("--dry-run", action="store_true", help="Show the integration plan without changing files.")
    connect.set_defaults(func=command_connect)

    status = subparsers.add_parser("status", help="Show the local and Matrixs Cloud connection state.")
    status.add_argument("--path")
    status.add_argument("--offline", action="store_true", help="Do not contact Matrixs Cloud.")
    status.add_argument("--timeout", type=float, default=10.0)
    status.set_defaults(func=command_status)

    disconnect = subparsers.add_parser("disconnect", help="Remove Matrixs integration using its original backup.")
    disconnect.add_argument("--path")
    disconnect.add_argument("--timeout", type=float, default=10.0)
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
