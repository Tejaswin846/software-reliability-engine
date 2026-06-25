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
            patch.object(app, "redis_get_conversation_state", return_value=None),
            patch.object(
                app,
                "redis_get_cached_ai_response",
                return_value={"response": "Use qwen.", "model": None},
            ),
            patch.object(app, "redis_set_conversation_state", return_value=True),
        ):
            result = app.save_chat_message(
                "chat-1",
                app.ChatMessageCreate(role="user", content="Use my usual model."),
                {"id": "user-1"},
            )

        self.assertEqual(call_order, ["search", "message", "memory"])
        self.assertEqual(result["memory_context"][0]["text"], "Existing preference")
        self.assertTrue(result["memory_save"]["stored"])
        self.assertEqual(result["cached_ai_response"]["response"], "Use qwen.")

    def test_assistant_message_populates_response_cache(self):
        history = {
            "chat": {"id": "chat-1"},
            "messages": [{"id": "message-1", "role": "user", "content": "Explain Redis."}],
        }
        saved = {
            "ok": True,
            "available": True,
            "data": {
                "id": "message-2",
                "role": "assistant",
                "content": "Redis is an in-memory data store.",
            },
        }
        with (
            patch.object(app, "redis_get_conversation_state", return_value=history),
            patch.object(app, "supabase_save_message", return_value=saved),
            patch.object(app, "redis_set_conversation_state", return_value=True),
            patch.object(
                app,
                "redis_cache_ai_response",
                return_value={"ok": True, "cached": True},
            ) as cache_response,
        ):
            result = app.save_chat_message(
                "chat-1",
                app.ChatMessageCreate(
                    role="assistant",
                    content="Redis is an in-memory data store.",
                    metadata={"prompt": "Explain Redis.", "model": "qwen"},
                ),
                {"id": "user-1"},
            )

        cache_response.assert_called_once()
        self.assertTrue(result["response_cache"]["cached"])


if __name__ == "__main__":
    unittest.main()
