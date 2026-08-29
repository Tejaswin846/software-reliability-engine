from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List

from .discover import inspect_project
from .models import ProjectAnalysis


AI_LIBRARY_PATTERNS: Dict[str, Iterable[str]] = {
    "openai": ("openai",),
    "anthropic": ("anthropic",),
    "gemini": ("google-generativeai", "google.genai", "gemini"),
    "langchain": ("langchain",),
    "crewai": ("crewai",),
}

DEPLOYMENT_FILES = ("Dockerfile", "Procfile", "render.yaml", "docker-compose.yml")


def _read(path: Path, limit: int = 524_288) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as stream:
            return stream.read(limit)
    except OSError:
        return ""


def _metadata_text(root: Path) -> str:
    names = ("pyproject.toml", "requirements.txt", "Pipfile", "setup.py")
    return "\n".join(_read(root / name) for name in names if (root / name).is_file()).lower()


def _fastapi_target(root: Path) -> List[str]:
    for name in ("main.py", "app.py"):
        path = root / name
        if path.is_file() and re.search(r"\bapp\s*=\s*FastAPI\s*\(", _read(path)):
            return ["python", "-m", "uvicorn", f"{path.stem}:app"]
    return ["python", "-m", "uvicorn", "main:app"]


def _startup_command(root: Path, framework: str) -> List[str]:
    if framework == "django" and (root / "manage.py").is_file():
        return ["python", "manage.py", "runserver"]
    if framework == "fastapi":
        return _fastapi_target(root)
    if (root / "app.py").is_file():
        return ["python", "app.py"]
    if (root / "main.py").is_file():
        return ["python", "main.py"]
    return ["python", "-m", root.name.replace("-", "_")]


def analyze_project(path: Path) -> ProjectAnalysis:
    root = path.expanduser().resolve()
    candidate = inspect_project(root)
    if candidate is None:
        raise ValueError(f"No supported Python project found at {root}.")
    metadata = _metadata_text(root)
    libraries = [
        name
        for name, patterns in AI_LIBRARY_PATTERNS.items()
        if any(pattern in metadata for pattern in patterns)
    ]
    adapters: List[str] = []
    if candidate.framework != "python":
        adapters.append(candidate.framework)
    adapters.extend(libraries)
    if not adapters:
        adapters.append("http")
    return ProjectAnalysis(
        path=root,
        runtime="python",
        framework=candidate.framework,
        startup_command=_startup_command(root, candidate.framework),
        ai_libraries=libraries,
        deployment_files=[name for name in DEPLOYMENT_FILES if (root / name).is_file()],
        adapters=adapters,
    )
