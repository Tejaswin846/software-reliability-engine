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
        self.assertIn("Sign in to get API key", install.text)
        self.assertIn("Show my API key", install.text)
        self.assertNotIn("Project Connection", install.text)
        self.assertIn("pip install software-sdk", docs.json()["install"]["python"])
        self.assertIn("npm install software-sdk", docs.json()["install"]["node"])
        self.assertFalse(docs.json()["auth_required_for_install"])

    def test_public_pages_expose_working_clerk_buttons(self):
        landing = self.client.get("/")
        login = self.client.get("/login")
        register = self.client.get("/register")
        forgot = self.client.get("/forgot-password")
        reset = self.client.get("/reset-password")
        pricing = self.client.get("/pricing")
        auth_js = self.client.get("/auth.js")

        for response in [landing, login, register, forgot, reset, pricing, auth_js]:
            self.assertEqual(response.status_code, 200)

        self.assertIn("Software", landing.text)
        self.assertIn("brand-plus", landing.text)
        self.assertIn("data-clerk-sign-in", landing.text)
        self.assertIn("data-clerk-sign-up", landing.text)
        self.assertIn("data-clerk-user-profile", landing.text)
        self.assertIn("/auth.js", landing.text)
        self.assertIn("data-clerk-sign-in", login.text)
        self.assertIn("data-clerk-reset", login.text)
        self.assertIn("data-clerk-sign-up", register.text)
        self.assertIn("data-clerk-reset", forgot.text)
        self.assertIn("data-clerk-reset", reset.text)
        self.assertIn("data-clerk-sign-up", pricing.text)
        self.assertIn("openUserProfile", auth_js.text)
        self.assertIn("data-clerk-manage-account", auth_js.text)
        self.assertIn("createClerkInstance", auth_js.text)
        self.assertNotIn("new window.Clerk", auth_js.text)

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

    def test_signed_in_install_endpoint_creates_project_key_and_commands(self):
        with patch.object(
            app,
            "verify_clerk_token",
            return_value={"sub": "user_install", "email": "install@example.com"},
        ), patch.object(app, "supabase_upsert_user_profile", return_value={"ok": True}):
            response = self.client.post(
                "/api/install/api-key",
                headers={"Authorization": "Bearer clerk-token"},
                json={"project_name": "simple-agent"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["api_key"].startswith("sw_"))
        self.assertEqual(payload["project"]["name"], "simple-agent")
        self.assertIn("software login --api-url", payload["commands"]["login"])
        self.assertIn(payload["api_key"], payload["commands"]["login"])
        with app.connect() as db:
            project = db.execute(
                "SELECT id, name FROM projects WHERE user_id = ?",
                ("user_install",),
            ).fetchone()
            active_key_count = db.execute(
                "SELECT COUNT(*) FROM api_keys WHERE user_id = ? AND is_active = 1",
                ("user_install",),
            ).fetchone()[0]
        self.assertIsNotNone(project)
        self.assertEqual(project["name"], "simple-agent")
        self.assertEqual(active_key_count, 1)

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
