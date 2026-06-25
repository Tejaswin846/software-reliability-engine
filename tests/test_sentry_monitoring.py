from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import sentry_monitoring


class SentryMonitoringTests(unittest.TestCase):
    def test_scrubs_secret_keys_and_values(self) -> None:
        with patch.dict(
            os.environ,
            {"TEST_API_KEY": "super-secret-value"},
            clear=False,
        ):
            scrubbed = sentry_monitoring.scrub_sensitive_data(
                {
                    "api_key": "another-secret",
                    "message": "request failed with super-secret-value",
                    "authorization": "Bearer abc.def.ghi",
                }
            )
        self.assertEqual(scrubbed["api_key"], "[Filtered]")
        self.assertNotIn("super-secret-value", scrubbed["message"])
        self.assertEqual(scrubbed["authorization"], "[Filtered]")

    def test_scrubs_jwt_and_query_tokens(self) -> None:
        text = (
            "token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature "
            "https://example.test/path?api_key=secret123&safe=yes"
        )
        redacted = sentry_monitoring.redact_text(text)
        self.assertNotIn("eyJhbGci", redacted)
        self.assertNotIn("secret123", redacted)
        self.assertIn("[Filtered]", redacted)

    def test_missing_dsn_is_healthy_but_disabled(self) -> None:
        with patch.dict(os.environ, {"SENTRY_DSN": ""}, clear=False):
            health = sentry_monitoring.initialize_sentry()
        self.assertTrue(health["ok"])
        self.assertFalse(health["configured"])
        self.assertFalse(health["initialized"])
        self.assertEqual(health["traces_sample_rate"], 0.2)

    def test_invalid_sample_rate_uses_default(self) -> None:
        with patch.dict(
            os.environ,
            {"SENTRY_DSN": "", "SENTRY_TRACES_SAMPLE_RATE": "5"},
            clear=False,
        ):
            health = sentry_monitoring.initialize_sentry()
        self.assertEqual(health["traces_sample_rate"], 0.2)

    def test_capture_uses_only_safe_context(self) -> None:
        active_client = SimpleNamespace(is_active=lambda: True)
        fake_scope = unittest.mock.MagicMock()
        scope_manager = unittest.mock.MagicMock()
        scope_manager.__enter__.return_value = fake_scope
        scope_manager.__exit__.return_value = False
        with (
            patch.object(sentry_monitoring.sentry_sdk, "get_client", return_value=active_client),
            patch.object(sentry_monitoring.sentry_sdk, "new_scope", return_value=scope_manager),
            patch.object(
                sentry_monitoring.sentry_sdk,
                "capture_message",
                return_value="event-id",
            ) as capture_message,
        ):
            event_id = sentry_monitoring.capture_operational_error(
                "API key=secret-value",
                category="provider_failure",
                workflow_id="wf_123",
                provider="qdrant",
                password="must-not-leave",
            )
        self.assertEqual(event_id, "event-id")
        self.assertNotIn("secret-value", capture_message.call_args.args[0])
        context = fake_scope.set_context.call_args.args[1]
        self.assertNotIn("password", context)


if __name__ == "__main__":
    unittest.main()
