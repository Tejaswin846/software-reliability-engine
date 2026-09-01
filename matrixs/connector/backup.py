from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from matrixs.config import MATRIXS_DIR_NAME

from .models import PlanChange


def new_backup_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def backups_root(project_root: Path) -> Path:
    return project_root / MATRIXS_DIR_NAME / "backups"


def create_backup(project_root: Path, changes: Iterable[PlanChange], backup_id: str) -> Path:
    root = project_root.resolve()
    backup_dir = backups_root(root) / backup_id
    files_dir = backup_dir / "files"
    if backup_dir.exists():
        raise RuntimeError(f"Matrixs backup already exists: {backup_dir}")
    files_dir.mkdir(parents=True, exist_ok=False)
    records = []
    for change in changes:
        target = change.path.resolve()
        try:
            relative = target.relative_to(root)
        except ValueError as error:
            raise RuntimeError(f"Refusing to back up a path outside the project: {target}") from error
        existed = target.is_file()
        record: Dict[str, Any] = {
            "path": relative.as_posix(),
            "existed": existed,
            "sensitive": change.sensitive,
        }
        if existed:
            destination = files_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
            record["backup_path"] = destination.relative_to(backup_dir).as_posix()
        records.append(record)
    manifest = {
        "backup_id": backup_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_root": ".",
        "files": records,
    }
    (backup_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return backup_dir


def read_manifest(backup_dir: Path) -> Dict[str, Any]:
    path = backup_dir / "manifest.json"
    if not path.is_file():
        raise RuntimeError(f"Invalid Matrixs backup: {backup_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def find_backup(project_root: Path, backup_id: str) -> Optional[Path]:
    path = backups_root(project_root.resolve()) / backup_id
    return path if (path / "manifest.json").is_file() else None


def latest_backup(project_root: Path) -> Optional[Path]:
    root = backups_root(project_root.resolve())
    if not root.is_dir():
        return None
    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "manifest.json").is_file() and not (path / "undone.json").exists()
    ]
    return max(candidates, key=lambda item: item.name) if candidates else None
