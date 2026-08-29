from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

from .backup import read_manifest
from .models import IntegrationPlan, PlanChange


def _atomic_write(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise RuntimeError(f"Refusing to replace symbolic link: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def apply_plan(plan: IntegrationPlan) -> List[Path]:
    changed: List[Path] = []
    root = plan.project_root.resolve()
    for change in plan.changes:
        target = change.path.resolve()
        try:
            target.relative_to(root)
        except ValueError as error:
            raise RuntimeError(f"Refusing to modify a path outside the project: {target}") from error
        _atomic_write(target, change.content)
        if change.sensitive:
            try:
                target.chmod(0o600)
            except OSError:
                pass
        changed.append(target)
    return changed


def rollback_backup(project_root: Path, backup_dir: Path, *, mark_undone: bool = True) -> List[Path]:
    root = project_root.resolve()
    manifest = read_manifest(backup_dir)
    manifest_root = Path(str(manifest.get("project_root", ""))).resolve()
    if manifest_root != root:
        raise RuntimeError(f"Backup belongs to {manifest_root}, not {root}.")
    restored: List[Path] = []
    for record in reversed(list(manifest.get("files", []))):
        target = (root / str(record["path"])).resolve()
        try:
            target.relative_to(root)
        except ValueError as error:
            raise RuntimeError(f"Unsafe path in Matrixs backup: {target}") from error
        if record.get("existed"):
            source = (backup_dir / str(record["backup_path"])).resolve()
            source.relative_to(backup_dir.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        elif target.exists():
            if target.is_dir():
                raise RuntimeError(f"Expected a file while rolling back Matrixs: {target}")
            target.unlink()
        restored.append(target)
    if mark_undone:
        (backup_dir / "undone.json").write_text(
            json.dumps({"undone_at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n",
            encoding="utf-8",
        )
    return restored
