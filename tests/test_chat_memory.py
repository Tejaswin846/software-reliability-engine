from __future__ import annotations

import unittest
from unittest.mock import patch

import app


class ChatMemoryIntegrationTests(unittest.TestCase):
    def test_user_message_retrieves_context_and_saves_memory(self):
        call_order = []

        def search_memory(user_id, query):
            call_order.append("search")
            return [{"text": "Existing preference", "score": 0.88}]

        def save_message(**kwargs):
            call_order.append("message")
            return {
                "ok": True,
                "available": True,
                "data": {"id": "message-1", **kwargs},
            }

        def save_memory(user_id, text):
            call_order.append("memory")
            return {"ok": True, "stored": True, "id": "memory-1"}

        with (
            patch.object(
                app,
                "supabase_get_chat_history",
                return_value={
                    "ok": True,
                    "available": True,
                    "data": {"chat": {"id": "chat-1"}, "messages": []},
                },
            ),
            patch.object(app, "qdrant_search_memory", side_effect=search_memory),
            patch.object(app, "supabase_save_message", side_effect=save_message),
            patch.object(app, "qdrant_save_memory", side_effect=save_memory),
        ):
            result = app.save_chat_message(
                "chat-1",
                app.ChatMessageCreate(role="user", content="Use my usual model."),
                {"id": "user-1"},
            )

        self.assertEqual(call_order, ["search", "message", "memory"])
        self.assertEqual(result["memory_context"][0]["text"], "Existing preference")
        self.assertTrue(result["memory_save"]["stored"])


if __name__ == "__main__":
    unittest.main()
