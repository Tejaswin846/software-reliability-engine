from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import supabase_client


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table_name, store, rows):
        self.table_name = table_name
        self.store = store
        self.rows = rows
        self.payload = None
        self.filters = []

    def insert(self, payload):
        self.payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.payload = payload
        self.store["on_conflict"] = on_conflict
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, _value):
        return self

    def order(self, _column):
        return self

    def execute(self):
        if self.payload is not None:
            self.store[self.table_name] = self.payload
            return FakeResponse([self.payload])
        result = list(self.rows.get(self.table_name, []))
        for column, value in self.filters:
            result = [row for row in result if row.get(column) == value]
        return FakeResponse(result)


class FakeClient:
    def __init__(self, rows=None):
        self.store = {}
        self.rows = rows or {}

    def table(self, name):
        return FakeQuery(name, self.store, self.rows)


class SupabaseClientTests(unittest.TestCase):
    def tearDown(self):
        supabase_client.reset_supabase_client()

    def test_missing_credentials_returns_degraded_result(self):
        with patch.dict(os.environ, {}, clear=True):
            supabase_client.reset_supabase_client()
            result = supabase_client.create_chat(user_id="usr_test", title="Test")
        self.assertFalse(result["ok"])
        self.assertFalse(result["available"])
        self.assertIn("SUPABASE_URL", result["error"])

    def test_save_benchmark_run_upserts_complete_payload(self):
        fake = FakeClient()
        with patch.object(supabase_client, "get_supabase_client", return_value=fake):
            result = supabase_client.save_benchmark_run(
                {
                    "run_id": "run_test",
                    "model": "test-model",
                    "total_workflows": 2,
                    "successful": 1,
                    "failed": 1,
                    "workflow_results": [{"workflow_id": "wf_1", "successful": True}],
                }
            )
        self.assertTrue(result["ok"])
        self.assertEqual(fake.store["on_conflict"], "run_id")
        self.assertEqual(fake.store["benchmark_runs"]["run_id"], "run_test")
        self.assertEqual(len(fake.store["benchmark_runs"]["workflow_results"]), 1)

    def test_save_message_writes_message_and_updates_chat(self):
        fake = FakeClient()
        with patch.object(supabase_client, "get_supabase_client", return_value=fake):
            result = supabase_client.save_message(
                chat_id="chat_test",
                user_id="usr_test",
                role="user",
                content="Hello",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(fake.store["messages"]["content"], "Hello")
        self.assertIn("updated_at", fake.store["chats"])

    def test_get_chat_history_returns_previous_messages(self):
        fake = FakeClient(
            rows={
                "chats": [{"id": "chat_test", "user_id": "usr_test", "title": "Saved"}],
                "messages": [
                    {
                        "id": "msg_1",
                        "chat_id": "chat_test",
                        "user_id": "usr_test",
                        "role": "user",
                        "content": "Previous message",
                    }
                ],
            }
        )
        with patch.object(supabase_client, "get_supabase_client", return_value=fake):
            result = supabase_client.get_chat_history(
                chat_id="chat_test",
                user_id="usr_test",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["chat"]["title"], "Saved")
        self.assertEqual(result["data"]["messages"][0]["content"], "Previous message")

    def test_upsert_user_profile_uses_clerk_user_id(self):
        fake = FakeClient()
        with patch.object(supabase_client, "get_supabase_client", return_value=fake):
            result = supabase_client.upsert_user_profile(
                user_id="user_clerk",
                email="person@example.com",
                metadata={"provider": "clerk"},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(fake.store["on_conflict"], "id")
        self.assertEqual(fake.store["user_profiles"]["id"], "user_clerk")
        self.assertEqual(fake.store["user_profiles"]["clerk_user_id"], "user_clerk")

    def test_supabase_auth_helpers_are_not_exposed(self):
        for name in [
            "auth_sign_up",
            "auth_sign_in",
            "auth_get_user",
            "auth_request_password_reset",
            "auth_update_password",
        ]:
            self.assertFalse(hasattr(supabase_client, name), f"{name} should be handled by Clerk")


if __name__ == "__main__":
    unittest.main()
