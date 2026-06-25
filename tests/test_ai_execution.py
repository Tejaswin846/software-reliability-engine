from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_execution import storage
from ai_execution.service import AIExecutionService
from sentry_monitoring import redact_text, scrub_sensitive_data


class AIExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            storage,
            "DB_PATH",
            Path(self.temp_dir.name) / "ai_execution.db",
        )
        self.db_patch.start()
        self.temporary_state = {}
        self.captured_errors = []
        self.tool_result = {"ok": True, "data": {"id": "tool-result"}}
        self.available_tools = {
            "GMAIL_SEND_EMAIL",
            "GOOGLECALENDAR_CREATE_EVENT",
            "SUPABASE_DELETE_ROW",
            "SUPABASE_UPDATE_ROW",
        }
        self.connected_apps = {"gmail", "google-calendar", "supabase"}
        self.service = self.make_service()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def make_service(self):
        def get_integrations(_user_id):
            app_names = {
                "gmail": "Gmail",
                "google-calendar": "Google Calendar",
                "supabase": "Supabase",
            }
            return {
                "configured": True,
                "apps": [
                    {
                        "id": app_id,
                        "name": app_names[app_id],
                        "connected": app_id in self.connected_apps,
                        "permissions_granted": ["Read", "Write"],
                    }
                    for app_id in app_names
                ],
            }

        def get_tool_context(_user_id):
            return {
                "tools": [
                    {"name": name, "description": "", "parameters": {}}
                    for name in sorted(self.available_tools)
                ],
                "connected_apps": [
                    {"id": app_id} for app_id in sorted(self.connected_apps)
                ],
            }

        def execute_tool(*_args, **_kwargs):
            if isinstance(self.tool_result, BaseException):
                raise self.tool_result
            return dict(self.tool_result)

        def set_state(user_id, request_id, value):
            self.temporary_state[(user_id, request_id)] = dict(value)
            return True

        def get_state(user_id, request_id):
            return self.temporary_state.get((user_id, request_id))

        def capture_error(error, **context):
            self.captured_errors.append((error, context))
            return "event-id"

        return AIExecutionService(
            get_integrations=get_integrations,
            get_tool_context=get_tool_context,
            execute_tool=execute_tool,
            search_memory=lambda _user_id, query: [
                {"text": f"context for {query}", "score": 0.9}
            ],
            supabase_health=lambda: {
                "ok": True,
                "configured": True,
                "available": True,
            },
            redis_health=lambda: {
                "ok": True,
                "configured": True,
                "connected": True,
            },
            set_temporary_state=set_state,
            get_temporary_state=get_state,
            capture_error=capture_error,
            redact=redact_text,
            scrub=scrub_sensitive_data,
        )

    def plan(self, request, action=None):
        return self.service.plan(
            user_id="user-1",
            request_text=request,
            action=action or {},
            return_to="/conversation",
        )

    def test_low_risk_direct_response(self):
        planned = self.plan("Explain how photosynthesis works.")
        self.assertEqual(planned["plan"]["intent"], "answer_question")
        self.assertEqual(planned["plan"]["risk_level"], "low_risk")

        validated = self.service.validate(
            user_id="user-1",
            request_id=planned["request_id"],
        )
        executed = self.service.execute(
            user_id="user-1",
            request_id=planned["request_id"],
        )

        self.assertTrue(validated["ok"])
        self.assertFalse(validated["confirmation_required"])
        self.assertTrue(executed["ok"])
        self.assertTrue(executed["execution_result"]["authorized"])

    def test_medium_risk_validation(self):
        planned = self.plan("Search my memory for the preferred coding model.")
        self.assertEqual(planned["plan"]["intent"], "search_data")
        self.assertEqual(planned["plan"]["risk_level"], "medium_risk")

        validated = self.service.validate(
            user_id="user-1",
            request_id=planned["request_id"],
        )
        executed = self.service.execute(
            user_id="user-1",
            request_id=planned["request_id"],
        )

        self.assertTrue(validated["validation_result"]["passed"])
        self.assertTrue(validated["verification_result"]["passed"])
        self.assertEqual(executed["execution_result"]["source"], "qdrant_memory")

    def test_high_risk_is_blocked_without_confirmation(self):
        planned = self.plan(
            "Send email to teammate@example.com",
            {
                "subject": "Reliability report",
                "body": "The report is ready.",
            },
        )
        validated = self.service.validate(
            user_id="user-1",
            request_id=planned["request_id"],
        )
        blocked = self.service.execute(
            user_id="user-1",
            request_id=planned["request_id"],
        )

        self.assertTrue(validated["confirmation_required"])
        self.assertFalse(blocked["ok"])
        self.assertTrue(blocked["blocked"])
        self.assertTrue(blocked["confirmation_required"])

    def test_email_send_is_blocked_when_recipient_is_missing(self):
        planned = self.plan(
            "Send an email with the reliability report.",
            {"subject": "Reliability report", "body": "Attached."},
        )
        validated = self.service.validate(
            user_id="user-1",
            request_id=planned["request_id"],
        )

        self.assertFalse(validated["ok"])
        self.assertIn("recipient", planned["plan"]["missing_info"])
        self.assertTrue(
            any(
                check["name"] == "email_recipient" and not check["passed"]
                for check in validated["validation_result"]["checks"]
            )
        )

    def test_database_delete_is_blocked_without_confirmation(self):
        planned = self.plan(
            "Delete data from the Supabase audit table.",
            {
                "app_id": "supabase",
                "tool_slug": "SUPABASE_DELETE_ROW",
                "target": "audit row 42",
                "data_affected": "audit row 42",
                "arguments": {"table": "audit", "id": 42},
            },
        )
        validated = self.service.validate(
            user_id="user-1",
            request_id=planned["request_id"],
        )
        blocked = self.service.execute(
            user_id="user-1",
            request_id=planned["request_id"],
        )

        self.assertTrue(validated["ok"])
        self.assertEqual(planned["plan"]["intent"], "delete_data")
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["status"], "awaiting_confirmation")

    def test_tool_unavailable_handling(self):
        self.available_tools.remove("GMAIL_SEND_EMAIL")
        planned = self.plan("Send email to teammate@example.com")
        validated = self.service.validate(
            user_id="user-1",
            request_id=planned["request_id"],
        )

        self.assertFalse(validated["ok"])
        self.assertFalse(validated["verification_result"]["passed"])
        self.assertTrue(
            any(
                check["name"] == "actual_tool_availability"
                and not check["passed"]
                for check in validated["verification_result"]["checks"]
            )
        )

    def test_secret_input_is_redacted_and_rejected(self):
        planned = self.plan(
            "Use api_key=super-secret-value-1234567890 to search data."
        )
        validated = self.service.validate(
            user_id="user-1",
            request_id=planned["request_id"],
        )
        audit = self.service.audit(
            user_id="user-1",
            request_id=planned["request_id"],
        )

        self.assertFalse(validated["ok"])
        self.assertTrue(
            any(
                check["name"] == "secret_exposure" and not check["passed"]
                for check in validated["validation_result"]["checks"]
            )
        )
        self.assertNotIn(
            "super-secret-value-1234567890",
            str(audit),
        )

    def test_audit_log_is_created(self):
        planned = self.plan("Summarize this reliability report.")
        self.service.validate(
            user_id="user-1",
            request_id=planned["request_id"],
        )
        self.service.execute(
            user_id="user-1",
            request_id=planned["request_id"],
        )
        audit = self.service.audit(
            user_id="user-1",
            request_id=planned["request_id"],
        )

        self.assertIsNotNone(audit)
        stages = [event["stage"] for event in audit["events"]]
        self.assertIn("request_received", stages)
        self.assertIn("planning", stages)
        self.assertIn("validation", stages)
        self.assertIn("verification", stages)
        self.assertIn("execution", stages)

    def test_sentry_logging_on_execution_failure(self):
        self.tool_result = RuntimeError("provider request failed")
        planned = self.plan("Send email to teammate@example.com")
        self.service.validate(
            user_id="user-1",
            request_id=planned["request_id"],
        )
        self.service.confirm(
            user_id="user-1",
            request_id=planned["request_id"],
            decision="confirm",
        )
        executed = self.service.execute(
            user_id="user-1",
            request_id=planned["request_id"],
        )

        self.assertFalse(executed["ok"])
        self.assertGreaterEqual(len(self.captured_errors), 1)
        self.assertEqual(
            self.captured_errors[0][1]["category"],
            "ai_execution_failure",
        )


if __name__ == "__main__":
    unittest.main()
