from __future__ import annotations

import os
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

import composio_service


@dataclass
class FakeConnection:
    is_active: bool


@dataclass
class FakeToolkit:
    slug: str
    name: str
    is_no_auth: bool = False
    connection: FakeConnection | None = None


class FakeSession:
    def __init__(self) -> None:
        self.execute_calls = []
        self.tool = SimpleNamespace(
            name="COMPOSIO_SEARCH_TOOLS",
            description="Search connected tools.",
            params_json_schema={"type": "object"},
        )

    def tools(self):
        return [self.tool]

    def toolkits(self, **kwargs):
        return SimpleNamespace(
            items=[
                FakeToolkit(
                    slug="github",
                    name="GitHub",
                    connection=FakeConnection(is_active=True),
                )
            ]
        )

    def execute(self, tool_slug, *, arguments, account=None):
        self.execute_calls.append((tool_slug, arguments, account))
        return SimpleNamespace(
            data={"repositories": 3},
            error=None,
            log_id="log_123",
        )


class FakeComposio:
    create_calls = []
    sessions = []

    def __init__(self, provider):
        self.provider = provider

    def create(self, **kwargs):
        self.__class__.create_calls.append(kwargs)
        session = FakeSession()
        self.__class__.sessions.append(session)
        return session


class ComposioServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeComposio.create_calls.clear()
        FakeComposio.sessions.clear()
        composio_service.reset_composio_state()

    def tearDown(self) -> None:
        composio_service.reset_composio_state()

    def configured(self):
        return patch.dict(
            os.environ,
            {"COMPOSIO_API_KEY": "test-composio-key"},
            clear=False,
        )

    def test_one_session_is_reused_per_user(self) -> None:
        with (
            self.configured(),
            patch.object(composio_service, "Composio", FakeComposio),
            patch.object(
                composio_service,
                "OpenAIAgentsProvider",
                lambda: object(),
            ),
        ):
            first = composio_service.get_user_tools("user_1")
            second = composio_service.get_user_tools("user_1")
        self.assertEqual(first, second)
        self.assertEqual(len(FakeComposio.create_calls), 1)
        self.assertEqual(
            FakeComposio.create_calls[0]["toolkits"],
            list(composio_service.SUPPORTED_TOOLKITS),
        )

    def test_refresh_recreates_user_session(self) -> None:
        with (
            self.configured(),
            patch.object(composio_service, "Composio", FakeComposio),
            patch.object(composio_service, "OpenAIAgentsProvider", lambda: object()),
        ):
            composio_service.get_user_tools("user_1")
            composio_service.refresh_tools("user_1")
        self.assertEqual(len(FakeComposio.create_calls), 2)

    def test_execute_tool_uses_the_user_session(self) -> None:
        with (
            self.configured(),
            patch.object(composio_service, "Composio", FakeComposio),
            patch.object(composio_service, "OpenAIAgentsProvider", lambda: object()),
        ):
            result = composio_service.execute_tool(
                "user_1",
                "github_list_repositories",
                {"limit": 5},
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["repositories"], 3)
        self.assertEqual(
            FakeComposio.sessions[0].execute_calls[0],
            ("GITHUB_LIST_REPOSITORIES", {"limit": 5}, None),
        )

    def test_tool_context_reports_connected_apps(self) -> None:
        with (
            self.configured(),
            patch.object(composio_service, "Composio", FakeComposio),
            patch.object(composio_service, "OpenAIAgentsProvider", lambda: object()),
        ):
            context = composio_service.get_user_tool_context("user_1")
        self.assertTrue(context["available"])
        self.assertEqual(context["connected_toolkits"][0]["slug"], "github")
        self.assertEqual(context["tools"][0]["name"], "COMPOSIO_SEARCH_TOOLS")

    def test_missing_api_key_degrades_without_raising(self) -> None:
        with patch.dict(os.environ, {"COMPOSIO_API_KEY": ""}, clear=False):
            self.assertEqual(composio_service.get_user_tools("user_1"), [])
            health = composio_service.composio_health_check()
        self.assertTrue(health["ok"])
        self.assertFalse(health["configured"])
        self.assertFalse(health["degraded"])


if __name__ == "__main__":
    unittest.main()
