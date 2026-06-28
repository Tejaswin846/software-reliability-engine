from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app


class ClerkPublicSDKTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(app, "DB_PATH", Path(self.temp_dir.name) / "software.db"),
            patch.object(app, "CLERK_PUBLISHABLE_KEY", "pk_test_clerk"),
            patch.object(app, "CLERK_SECRET_KEY", "sk_test_clerk"),
            patch.object(app, "CLERK_JWT_ISSUER", "https://lasting-weevil-59.clerk.accounts.dev"),
            patch.object(app, "CLERK_JWKS_URL", "https://lasting-weevil-59.clerk.accounts.dev/.well-known/jwks.json"),
            patch.object(app, "CLERK_JWK_CLIENT", object()),
            patch.object(app, "PUBLIC_BASE_URL", "https://software-reliability-engine.onrender.com"),
        ]
        for item in self.patches:
            item.start()
        app.init_db()
        self.client = TestClient(app.app)

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    def test_clerk_config_is_public(self):
        response = self.client.get("/auth/config")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["provider"], "clerk")
        self.assertTrue(payload["configured"])
        self.assertEqual(payload["clerk_publishable_key"], "pk_test_clerk")
        self.assertTrue(payload["sdk_install_public"])

    def test_sdk_install_is_public_without_login(self):
        install = self.client.get("/install")
        sdk = self.client.get("/sdk")
        docs = self.client.get("/api/sdk/docs")

        self.assertEqual(install.status_code, 200)
        self.assertEqual(sdk.status_code, 200)
        self.assertEqual(docs.status_code, 200)
        self.assertIn("pip install software-sdk", install.text)
        self.assertIn("npm install software-sdk", install.text)
        self.assertIn("pip install software-sdk", docs.json()["install"]["python"])
        self.assertIn("npm install software-sdk", docs.json()["install"]["node"])
        self.assertFalse(docs.json()["auth_required_for_install"])

    def test_dashboard_page_loads_but_data_api_requires_auth(self):
        dashboard = self.client.get("/dashboard")
        projects = self.client.get("/api/projects")

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(projects.status_code, 401)

    def test_cloud_sdk_api_rejects_without_key_but_mentions_local_install(self):
        response = self.client.post(
            "/api/sdk/workflows/start",
            json={"project_name": "sdk", "workflow_name": "cloud"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("install and use the SDK locally", response.json()["detail"])

    def test_clerk_jwt_can_access_user_api_and_creates_user(self):
        with patch.object(
            app,
            "verify_clerk_token",
            return_value={"sub": "user_clerk", "email": "clerk@example.com"},
        ), patch.object(app, "supabase_upsert_user_profile", return_value={"ok": True}) as sync_profile:
            response = self.client.get("/api/projects", headers={"Authorization": "Bearer clerk-token"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["projects"], [])
        with app.connect() as db:
            row = db.execute("SELECT id, email FROM users WHERE id = ?", ("user_clerk",)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["email"], "clerk@example.com")
        sync_profile.assert_called_once()


if __name__ == "__main__":
    unittest.main()
