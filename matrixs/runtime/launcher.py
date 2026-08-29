from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from matrixs.config import load_project_connection, parse_dotenv, project_config_path, project_env_path, read_json


def build_runtime_environment(project_root: Path, base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    root = project_root.resolve()
    config = read_json(project_config_path(root))
    connection = load_project_connection(root)
    env = dict(base or os.environ)
    env.update(parse_dotenv(project_env_path(root)))
    env.update(
        {
            "MATRIXS_API_URL": connection["api_url"],
            "MATRIXS_API_KEY": connection["api_key"],
            "MATRIXS_PROJECT_ID": connection["project_id"],
            "MATRIXS_PROJECT_NAME": connection["project_name"],
            "MATRIXS_ADAPTERS": ",".join(config.get("adapters") or []),
            "MATRIXS_PROJECT_ROOT": str(root),
        }
    )
    bootstrap = str(root / ".matrixs" / "runtime")
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = bootstrap + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    return env


def configured_command(project_root: Path) -> List[str]:
    config = read_json(project_config_path(project_root.resolve()))
    command = config.get("startup_command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        raise RuntimeError("Matrixs startup command is missing or invalid. Run `matrixs connect` again.")
    return list(command)


def run_project(project_root: Path, command: Optional[Iterable[str]] = None) -> int:
    root = project_root.expanduser().resolve()
    selected = list(command or configured_command(root))
    if selected and selected[0] == "--":
        selected = selected[1:]
    if not selected:
        raise RuntimeError("No application command was provided.")
    completed = subprocess.run(selected, cwd=root, env=build_runtime_environment(root), check=False)
    return int(completed.returncode)
