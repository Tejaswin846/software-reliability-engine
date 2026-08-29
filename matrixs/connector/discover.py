from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Optional

from .models import ProjectCandidate


IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".matrixs",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "env",
    "node_modules",
    "site-packages",
    "venv",
}

MARKER_SCORES = {
    "pyproject.toml": 5,
    "requirements.txt": 4,
    "setup.py": 4,
    "manage.py": 6,
    "Pipfile": 3,
    "poetry.lock": 3,
    "app.py": 2,
    "main.py": 2,
}


def _read_metadata(path: Path, limit: int = 262_144) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as stream:
            return stream.read(limit).lower()
    except OSError:
        return ""


def _detect_framework(path: Path) -> str:
    if (path / "manage.py").exists():
        return "django"
    metadata = "\n".join(
        _read_metadata(path / name)
        for name in ("pyproject.toml", "requirements.txt", "Pipfile")
        if (path / name).exists()
    )
    if "fastapi" in metadata:
        return "fastapi"
    if "flask" in metadata:
        return "flask"
    if "django" in metadata:
        return "django"
    return "python"


def inspect_project(path: Path) -> Optional[ProjectCandidate]:
    root = path.resolve()
    markers = [name for name in MARKER_SCORES if (root / name).is_file()]
    confidence = sum(MARKER_SCORES[name] for name in markers)
    if confidence < 3:
        return None
    return ProjectCandidate(
        path=root,
        runtime="python",
        framework=_detect_framework(root),
        confidence=confidence,
        markers=markers,
    )


def _walk_directories(start: Path, max_depth: int) -> Iterable[Path]:
    start_depth = len(start.parts)
    for current, directory_names, _ in os.walk(start):
        current_path = Path(current)
        depth = len(current_path.parts) - start_depth
        directory_names[:] = [
            name
            for name in directory_names
            if name not in IGNORED_DIRECTORIES and not name.startswith(".")
        ]
        if depth >= max_depth:
            directory_names[:] = []
        if depth > 0:
            yield current_path


def discover_projects(start: Path, max_depth: int = 3) -> List[ProjectCandidate]:
    root = start.expanduser().resolve()
    if not root.is_dir():
        return []
    current = inspect_project(root)
    if current is not None:
        return [current]
    candidates = [
        candidate
        for path in _walk_directories(root, max_depth=max(1, max_depth))
        if (candidate := inspect_project(path)) is not None
    ]
    candidates.sort(key=lambda item: (-item.confidence, str(item.path).lower()))
    return candidates
