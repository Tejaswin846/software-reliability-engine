from __future__ import annotations

import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app


class ProjectsAndBillingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.original_path = app.DB_PATH
        self.original_data = app.DATA_DIR
        app.DATA_DIR = Path(self.temp.name)
        app.DB_PATH = Path(self.temp.name) / "projects-billing.db"
        app._INITIALIZED_DATABASES.discard(str(app.DB_PATH.resolve()))
        app.init_db()
        self.snapshot_patch = patch.object(app, "redis_save_sqlite_snapshot", return_value={"ok": True, "stored": True})
        self.snapshot_patch.start()
        self.client = TestClient(app.app)
        token = app.create_access_token("usr_dev_local")["access_token"]
        self.headers = {"Authorization": f"Bearer {token}"}

    def tearDown(self) -> None:
        self.client.close()
        self.snapshot_patch.stop()
        gc.collect()
        app._INITIALIZED_DATABASES.discard(str(app.DB_PATH.resolve()))
        app.DB_PATH = self.original_path
        app.DATA_DIR = self.original_data
        self.temp.cleanup()

    def unlock_developer_plan(self) -> None:
        with app.connect() as db:
            app.create_local_subscription(db, "usr_dev_local", "developer", metadata={"test": True})

    def create_project(self, name: str) -> dict:
        response = self.client.post(
            "/api/projects", headers=self.headers,
            json={"name": name, "environment": "production"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["project"]

    def test_projects_persist_and_offline_projects_remain_visible(self) -> None:
        self.unlock_developer_plan()
        project = self.create_project("Offline agent")
        app._INITIALIZED_DATABASES.discard(str(app.DB_PATH.resolve()))
        app.init_db()

        response = self.client.get("/api/projects", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        restored = next(item for item in response.json()["projects"] if item["id"] == project["id"])
        self.assertEqual(restored["status"], "offline")
        self.assertEqual(restored["environment"], "production")

    def test_current_project_switch_strictly_scopes_reliability(self) -> None:
        self.unlock_developer_plan()
        first = self.create_project("First")
        second = self.create_project("Second")
        with app.connect() as db:
            now = app.now_iso()
            for project, success in ((first, 1), (second, 0)):
                db.execute(
                    """INSERT INTO sdk_workflows (
                           workflow_id, user_id, project_id, project_name, workflow_name,
                           status, success, started_at, completed_at, reliability_score
                       ) VALUES (?, 'usr_dev_local', ?, ?, 'scope-test', 'completed', ?, ?, ?, ?)""",
                    (f"wf_{project['id']}", project["id"], project["name"], success, now, now, 100.0 if success else 0.0),
                )
        switched = self.client.post(
            "/api/projects/current", headers=self.headers, json={"project_id": second["id"]},
        )
        self.assertEqual(switched.status_code, 200)
        dashboard = self.client.get("/api/me/dashboard", headers=self.headers).json()
        self.assertEqual(dashboard["current_project"]["id"], second["id"])
        self.assertEqual(dashboard["overview"]["total_workflows"], 1)
        self.assertEqual(dashboard["overview"]["failed_workflows"], 1)
        self.assertEqual({row["project_id"] for row in dashboard["sdk_workflows"]["recent_workflows"]}, {second["id"]})

    def test_other_users_cannot_read_or_select_a_project(self) -> None:
        self.unlock_developer_plan()
        project = self.create_project("Private")
        with app.connect() as db:
            now = app.now_iso()
            db.execute("INSERT INTO users (id, email, password_hash, created_at) VALUES ('usr_other', 'other@example.com', 'x', ?)", (now,))
            app.ensure_default_subscriptions(db)
        other = {"Authorization": f"Bearer {app.create_access_token('usr_other')['access_token']}"}
        self.assertEqual(self.client.get(f"/api/projects/{project['id']}", headers=other).status_code, 404)
        self.assertEqual(self.client.post("/api/projects/current", headers=other, json={"project_id": project["id"]}).status_code, 404)

    def test_installation_records_persist_and_are_project_scoped(self) -> None:
        context = {"user_id": "usr_dev_local", "project_id": "prj_dev_local", "api_key_id": "key_dev_local"}
        payload = app.SDKInstallationRegistration(
            installation_id="inst_persistent", device_label="Build runner", operating_system="Linux",
            runtime="Python 3.12", environment="production",
        )
        result = app._record_sdk_installation_state("matrixs_installation_registered", payload, context)
        self.assertEqual(result["installation"]["state"], "connected")
        app._INITIALIZED_DATABASES.discard(str(app.DB_PATH.resolve()))
        app.init_db()
        details = self.client.get("/api/projects/prj_dev_local", headers=self.headers).json()
        self.assertEqual(details["installations"][0]["id"], "inst_persistent")
        self.assertEqual(details["installations"][0]["device_label"], "Build runner")

    def test_billing_uses_persisted_usage_and_plan_catalog(self) -> None:
        with app.connect() as db:
            app.record_usage(db, "usr_dev_local", "workflow", quantity=7, project_id="prj_dev_local")
            app.record_usage(db, "usr_dev_local", "telemetry_event", quantity=13, project_id="prj_dev_local")
        response = self.client.get("/api/billing/me", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        billing = response.json()["billing"]
        self.assertEqual(billing["usage"]["workflows"], 7)
        self.assertEqual(billing["plan"]["retention_days"], 7)
        plans = self.client.get("/api/billing/plans").json()["plans"]
        self.assertEqual([plan["id"] for plan in plans[:5]], ["free", "developer", "pro", "business", "enterprise"])
        self.assertEqual(self.client.get("/billing", headers=self.headers).status_code, 200)

    def test_free_project_limit_has_actionable_error_and_keeps_data(self) -> None:
        response = self.client.post("/api/projects", headers=self.headers, json={"name": "Too many"})
        self.assertEqual(response.status_code, 402)
        self.assertIn("supports 1 projects", response.json()["detail"])
        projects = self.client.get("/api/projects", headers=self.headers).json()["projects"]
        self.assertEqual(len(projects), 1)

    def test_pages_contain_honest_empty_states(self) -> None:
        self.assertIn("haven't connected any projects yet", (Path(app.BASE_DIR) / "saas.js").read_text(encoding="utf-8"))
        self.assertIn("No billing history yet", (Path(app.BASE_DIR) / "billing.js").read_text(encoding="utf-8"))
        self.assertIn("No workflows have been recorded", (Path(app.BASE_DIR) / "project_detail.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
