from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class ProjectCandidate:
    path: Path
    runtime: str
    framework: str
    confidence: int
    markers: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectAnalysis:
    path: Path
    runtime: str
    framework: str
    startup_command: List[str]
    ai_libraries: List[str]
    deployment_files: List[str]
    adapters: List[str]


@dataclass(frozen=True)
class Credentials:
    project_id: str
    api_key: str
    api_url: str
    project_name: str
    installation_id: str


@dataclass(frozen=True)
class PlanChange:
    path: Path
    content: bytes
    action: str
    sensitive: bool = False


@dataclass
class IntegrationPlan:
    project_root: Path
    analysis: ProjectAnalysis
    credentials: Credentials
    backup_id: str
    integration_backup_id: str
    changes: List[PlanChange]
    metadata: Dict[str, Any] = field(default_factory=dict)
