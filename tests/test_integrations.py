from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from integrations import composio_service
from integrations.models import APPS, app_for_tool, get_app
from integrations import storage


class IntegrationStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "integrations.db"
        self.db_patch = patch.object(storage, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.env_patch = patch.dict(
            os.environ,
            {
                "INTEGRATION_ENCRYPTION_KEY": "test-encryption-key-that-is-long",
                "INTEGRATION_STATE_SECRET": "test-state-key-that-is-at-least-32-bytes-long",
            },
            clear=False,
        )
        self.env_patch.start()
        composio_service.reset_composio_state()

    def tearDown(self) -> None:
        composio_service.reset_composio_state()
        self.env_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_catalog_contains_requested_apps_and_categories(self) -> None:
        self.assertGreaterEqual(len(APPS), 25)
        self.assertIsNotNone(get_app("gmail"))
        self.assertIsNotNone(get_app("microsoft-teams"))
        self.assertIsNotNone(get_app("postgresql"))
        self.assertIsNotNone(get_app("webhooks"))
        self.assertEqual(app_for_tool("GMAIL_SEND_EMAIL").id, "gmail")
        self.assertEqual(
            {app.category for app in APPS},
            {"Communication", "Development", "Storage", "Productivity", "AI", "Database"},
        )

    def test_connection_metadata_is_encrypted_and_user_scoped(self) -> None:
        storage.save_connection(
            "user_1",
            "gmail",
            "gmail",
            status="ACTIVE",
            health="Healthy",
            metadata={
                "connected_account_id": "ca_secret_identifier",
                "permissions": ["email.read"],
            },
            last_sync_at="2026-06-25T12:00:00+00:00",
        )
        with sqlite3.connect(self.db_path) as db:
            raw = db.execute(
                "SELECT encrypted_metadata FROM integration_connections"
            ).fetchone()[0]
        self.assertNotIn("ca_secret_identifier", raw)
        self.assertEqual(
            storage.get_connection("user_1", "gmail")["metadata"]["connected_account_id"],
            "ca_secret_identifier",
        )
        self.assertIsNone(storage.get_connection("user_2", "gmail"))

    def test_pending_action_is_encrypted(self) -> None:
        action_id = storage.create_pending_action(
            "user_1",
            "gmail",
            {
                "tool_slug": "GMAIL_SEND_EMAIL",
                "arguments": {"recipient_email": "private@example.com"},
            },
            "/conversation/123",
        )
        with sqlite3.connect(self.db_path) as db:
            raw = db.execute(
                "SELECT encrypted_action FROM integration_pending_actions WHERE id = ?",
                (action_id,),
            ).fetchone()[0]
        self.assertNotIn("private@example.com", raw)
        pending = storage.get_pending_action("user_1", action_id)
        self.assertEqual(pending["action"]["tool_slug"], "GMAIL_SEND_EMAIL")

    def test_state_tokens_are_user_bound(self) -> None:
        token = composio_service.create_connection_state(
            "user_1",
            "gmail",
            return_to="/conversation/123",
            pending_action_id="resume_123",
        )
        payload = composio_service.decode_connection_state(token)
        self.assertEqual(payload["sub"], "user_1")
        self.assertEqual(payload["return_to"], "/conversation/123")

    def test_unconnected_tool_creates_resumable_action(self) -> None:
        with patch.object(composio_service, "is_app_connected", return_value=False):
            result = composio_service.execute_tool(
                "user_1",
                "GMAIL_SEND_EMAIL",
                {"recipient_email": "person@example.com"},
                workflow_id="wf_123",
                chat_id="chat_123",
                return_to="/conversation/chat_123",
            )
        self.assertTrue(result["connection_required"])
        pending = storage.get_pending_action("user_1", result["pending_action_id"])
        self.assertEqual(pending["action"]["workflow_id"], "wf_123")
        self.assertEqual(pending["action"]["chat_id"], "chat_123")

    def test_pending_action_resumes_after_connection(self) -> None:
        action_id = storage.create_pending_action(
            "user_1",
            "github",
            {
                "workflow_id": "wf_123",
                "tool_slug": "GITHUB_LIST_REPOSITORIES",
                "arguments": {},
                "agent_name": "research-agent",
            },
            "/conversation/123",
        )
        fake_session = SimpleNamespace(
            execute=lambda *args, **kwargs: SimpleNamespace(
                data={"repositories": []},
                error=None,
                log_id="log_123",
            )
        )
        with (
            patch.object(composio_service, "is_app_connected", return_value=True),
            patch.object(
                composio_service,
                "_get_user_session",
                return_value=SimpleNamespace(session=fake_session),
            ),
            patch.object(composio_service, "composio_is_configured", return_value=True),
        ):
            result = composio_service.resume_pending_action("user_1", action_id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["workflow_id"], "wf_123")


if __name__ == "__main__":
    unittest.main()
