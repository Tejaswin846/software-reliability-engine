from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app
from ai_execution import storage


class AIExecutionAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.init_db()
        with app.connect() as db:
            cls.user = db.execute(
                "SELECT id, email FROM users ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
        if cls.user is None:
            raise RuntimeError("A bootstrap user is required for API tests.")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            storage,
            "DB_PATH",
            Path(self.temp_dir.name) / "ai_execution_api.db",
        )
        self.db_patch.start()
        token = app.create_access_token(self.user["id"])["access_token"]
        self.client = TestClient(app.app)
        self.client.cookies.set(app.SESSION_COOKIE_NAME, token)

    def tearDown(self):
        self.client.close()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_low_risk_api_flow_and_audit(self):
        with (
            patch.object(app.AI_EXECUTION_SERVICE, "search_memory", return_value=[]),
            patch.object(
                app.AI_EXECUTION_SERVICE,
                "get_integrations",
                return_value={"configured": False, "apps": []},
            ),
            patch.object(
                app.AI_EXECUTION_SERVICE,
                "get_tool_context",
                return_value={"tools": [], "connected_apps": []},
            ),
        ):
            planned = self.client.post(
                "/api/ai/plan",
                json={"request": "Explain reliability scoring simply."},
            )
            self.assertEqual(planned.status_code, 200)
            request_id = planned.json()["request_id"]

            validated = self.client.post(
                "/api/ai/validate",
                json={"request_id": request_id},
            )
            executed = self.client.post(
                "/api/ai/execute",
                json={"request_id": request_id},
            )
            audit = self.client.get(f"/api/ai/audit/{request_id}")

        self.assertEqual(validated.status_code, 200)
        self.assertEqual(executed.status_code, 200)
        self.assertEqual(audit.status_code, 200)
        self.assertGreaterEqual(len(audit.json()["events"]), 6)

    def test_high_risk_api_requires_confirmation(self):
        integrations = {
            "configured": True,
            "apps": [
                {
                    "id": "gmail",
                    "name": "Gmail",
                    "connected": True,
                    "permissions_granted": ["Send email"],
                }
            ],
        }
        tools = {
            "tools": [
                {
                    "name": "GMAIL_SEND_EMAIL",
                    "description": "Send email",
                    "parameters": {},
                }
            ],
            "connected_apps": [{"id": "gmail", "name": "Gmail"}],
        }
        with (
            patch.object(app.AI_EXECUTION_SERVICE, "search_memory", return_value=[]),
            patch.object(
                app.AI_EXECUTION_SERVICE,
                "get_integrations",
                return_value=integrations,
            ),
            patch.object(
                app.AI_EXECUTION_SERVICE,
                "get_tool_context",
                return_value=tools,
            ),
            patch.object(
                app.AI_EXECUTION_SERVICE,
                "execute_tool",
                return_value={"ok": True, "data": {"message_id": "mail-1"}},
            ),
        ):
            planned = self.client.post(
                "/api/ai/plan",
                json={
                    "request": "Send email to person@example.com",
                    "action": {"subject": "Report", "body": "Ready."},
                },
            ).json()
            request_id = planned["request_id"]
            validated = self.client.post(
                "/api/ai/validate",
                json={"request_id": request_id},
            )
            blocked = self.client.post(
                "/api/ai/execute",
                json={"request_id": request_id},
            )
            confirmed = self.client.post(
                "/api/ai/confirm",
                json={"request_id": request_id, "decision": "confirm"},
            )
            executed = self.client.post(
                "/api/ai/execute",
                json={"request_id": request_id},
            )

        self.assertEqual(validated.status_code, 200)
        self.assertTrue(validated.json()["confirmation_required"])
        self.assertEqual(validated.json()["confirmation_card"]["title"], "Review before running")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(executed.status_code, 200)
        self.assertEqual(executed.json()["status"], "executed")

    def test_confirmation_frontend_asset_is_available(self):
        response = self.client.get("/ai_confirmation.js")
        dashboard = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Review before running", response.text)
        self.assertIn("software:ai-execution-completed", response.text)
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn('<script src="/ai_confirmation.js"></script>', dashboard.text)


if __name__ == "__main__":
    unittest.main()
