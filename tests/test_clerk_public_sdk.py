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
        onboarding = self.client.get("/onboarding")
        connection = self.client.get("/api-keys")
        projects_page = self.client.get("/projects")
        sdk = self.client.get("/sdk")
        docs = self.client.get("/api/sdk/docs")

        self.assertEqual(install.status_code, 200)
        self.assertEqual(onboarding.status_code, 200)
        self.assertEqual(connection.status_code, 200)
        self.assertEqual(projects_page.status_code, 200)
        self.assertEqual(sdk.status_code, 200)
        self.assertEqual(docs.status_code, 200)
        self.assertIn("pip install git+https://github.com/Tejaswin846/software-reliability-engine.git", install.text)
        self.assertIn("Project Connection", install.text)
        self.assertIn("Open Project Connection", install.text)
        self.assertIn(">matrixs connect<", install.text)
        self.assertIn('data-copy-target="install-command-github"', install.text)
        self.assertIn('data-copy-target="install-command-connect"', install.text)
        self.assertLess(install.text.index('id="install-command-github"'), install.text.index('id="install-command-connect"'))
        self.assertNotIn("matrixs connect --token", install.text)
        self.assertIn('id="onboarding-install-command"', onboarding.text)
        self.assertIn('id="onboarding-connect-command"', onboarding.text)
        self.assertNotIn("matrixs connect --", onboarding.text)
        self.assertIn('<pre id="connection-command" class="code-snippet">matrixs connect</pre>', connection.text)
        self.assertIn("Project ID and API key", connection.text)
        self.assertIn("Generate API Key", connection.text)
        self.assertIn("Regenerate", connection.text)
        self.assertIn("Copy API Key", connection.text)
        self.assertIn("Copy Project ID", connection.text)
        self.assertNotIn("Generate connection command", connection.text)
        self.assertNotIn("--token", connection.text)
        self.assertIn("Matrixs", projects_page.text)
        self.assertNotIn("<span>Software</span>", projects_page.text)
        self.assertIn("Copy Project ID", self.client.get("/saas.js").text)
        self.assertNotIn("Show my API key", install.text)
        self.assertIn("pip install git+https://github.com/Tejaswin846/software-reliability-engine.git", docs.json()["install"]["python"])
        self.assertIn("supports Python 3.10+", docs.json()["install"]["node"])
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
        self.assertTrue(payload["api_key"].startswith("mx_"))
        self.assertEqual(payload["project"]["name"], "simple-agent")
        self.assertEqual(payload["commands"]["login"], "matrixs connect")
        self.assertNotIn(payload["api_key"], payload["commands"]["login"])
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

    def test_signed_in_install_endpoint_replaces_existing_active_keys(self):
        with patch.object(
            app,
            "verify_clerk_token",
            return_value={"sub": "user_replace_key", "email": "replace@example.com"},
        ), patch.object(app, "supabase_upsert_user_profile", return_value={"ok": True}):
            first_response = self.client.post(
                "/api/install/api-key",
                headers={"Authorization": "Bearer clerk-token"},
                json={"project_name": "first-agent"},
            )

        self.assertEqual(first_response.status_code, 200)
        extra_key = app.generate_api_key()
        created_at = app.now_iso()
        with app.connect() as db:
            db.execute(
                """
                INSERT INTO projects (id, user_id, organization_id, name, created_at)
                VALUES (?, ?, NULL, ?, ?)
                """,
                ("prj_extra_install", "user_replace_key", "extra-agent", created_at),
            )
            db.execute(
                """
                INSERT INTO api_keys (
                    id, user_id, project_id, key_hash, key_prefix,
                    created_at, last_used_at, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, 1)
                """,
                (
                    "key_extra_install",
                    "user_replace_key",
                    "prj_extra_install",
                    extra_key["key_hash"],
                    extra_key["key_prefix"],
                    created_at,
                ),
            )

        with patch.object(
            app,
            "verify_clerk_token",
            return_value={"sub": "user_replace_key", "email": "replace@example.com"},
        ), patch.object(app, "supabase_upsert_user_profile", return_value={"ok": True}):
            second_response = self.client.post(
                "/api/install/api-key",
                headers={"Authorization": "Bearer clerk-token"},
                json={"project_name": "second-agent"},
            )

        self.assertEqual(second_response.status_code, 200)
        payload = second_response.json()
        self.assertGreaterEqual(payload["key"]["replaced_existing_keys"], 2)
        with app.connect() as db:
            active_key_count = db.execute(
                "SELECT COUNT(*) FROM api_keys WHERE user_id = ? AND is_active = 1",
                ("user_replace_key",),
            ).fetchone()[0]
            total_key_count = db.execute(
                "SELECT COUNT(*) FROM api_keys WHERE user_id = ?",
                ("user_replace_key",),
            ).fetchone()[0]
        self.assertEqual(active_key_count, 1)
        self.assertEqual(total_key_count, 3)

    def test_install_endpoint_handles_clerk_token_without_email_claim(self):
        class ClerkProfileResponse:
            status_code = 200
            content = b'{"id":"user_profile_fetch"}'

            @staticmethod
            def json():
                return {
                    "id": "user_profile_fetch",
                    "primary_email_address_id": "email_primary",
                    "email_addresses": [
                        {
                            "id": "email_primary",
                            "email_address": "profile-fetch@example.com",
                        }
                    ],
                }

        with patch.object(
            app,
            "verify_clerk_token",
            return_value={"sub": "user_profile_fetch"},
        ), patch.object(app.requests, "get", return_value=ClerkProfileResponse()) as clerk_get, patch.object(
            app,
            "supabase_upsert_user_profile",
            return_value={"ok": True},
        ):
            response = self.client.post(
                "/api/install/api-key",
                headers={"Authorization": "Bearer clerk-token"},
                json={"project_name": "profile-fetch-agent"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["api_key"].startswith("mx_"))
        clerk_get.assert_called_once()
        with app.connect() as db:
            row = db.execute(
                "SELECT id, email FROM users WHERE id = ?",
                ("user_profile_fetch",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["email"], "profile-fetch@example.com")

    def test_cached_clerk_user_rehydrates_local_row_before_usage_write(self):
        cached_user = {
            "user": {
                "id": "user_cached_clerk",
                "email": "cached-clerk@example.com",
                "created_at": app.now_iso(),
            },
            "provider": "clerk",
        }
        with patch.object(
            app,
            "verify_clerk_token",
            return_value={"sub": "user_cached_clerk", "email": "cached-clerk@example.com"},
        ), patch.object(app, "redis_get_session_cache", return_value=cached_user), patch.object(
            app,
            "redis_set_session_cache",
            return_value=True,
        ), patch.object(app, "supabase_upsert_user_profile", return_value={"ok": True}):
            response = self.client.post(
                "/api/install/api-key",
                headers={"Authorization": "Bearer clerk-token"},
                json={"project_name": "cached-agent"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        with app.connect() as db:
            user = db.execute(
                "SELECT id, email FROM users WHERE id = ?",
                ("user_cached_clerk",),
            ).fetchone()
            usage_count = db.execute(
                "SELECT COUNT(*) FROM usage_records WHERE user_id = ?",
                ("user_cached_clerk",),
            ).fetchone()[0]
        self.assertIsNotNone(user)
        self.assertEqual(user["email"], "cached-clerk@example.com")
        self.assertGreaterEqual(usage_count, 1)

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
