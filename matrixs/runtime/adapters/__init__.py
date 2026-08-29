"""Adapter registry used by Matrixs runtime discovery."""

SUPPORTED_ADAPTERS = ("fastapi", "flask", "django", "openai", "anthropic", "gemini", "langchain", "crewai", "http")

__all__ = ["SUPPORTED_ADAPTERS"]
