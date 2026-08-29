"""Zero-code project discovery and integration primitives."""

from .analyzer import analyze_project
from .discover import discover_projects

__all__ = ["analyze_project", "discover_projects"]
