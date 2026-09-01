from __future__ import annotations

from pathlib import Path
from typing import Callable


InputFunction = Callable[[str], str]


def ask_yes_no(question: str, input_fn: InputFunction = input) -> bool:
    while True:
        answer = input_fn(f"{question} [Y/N]: ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer Y or N.")


def request_integration_permission(
    project_root: Path,
    *,
    input_fn: InputFunction = input,
    open_manual_guide: Callable[[], None],
) -> bool:
    print("Matrixs needs permission to automatically integrate with this project.")
    print(f'Project: "{project_root.name}"')
    print("Matrixs may:")
    print("- create Matrixs configuration files")
    print("- add required Matrixs integration/runtime code")
    print("- update startup configuration when necessary")
    print("- save Matrixs configuration")
    print("- create a backup before making changes")
    print("Matrixs will not modify unrelated files.")
    while True:
        if ask_yes_no("Allow Matrixs to modify this project?", input_fn=input_fn):
            return True
        if ask_yes_no("Do you want to integrate Matrixs manually instead?", input_fn=input_fn):
            open_manual_guide()
            return False
        print("Returning...")
