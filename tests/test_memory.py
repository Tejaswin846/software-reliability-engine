from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import memory


class FakeQdrantClient:
    def __init__(self):
        self.upserted = []
        self.query_filter = None
        self.scroll_filter = None

    def upsert(self, collection_name, points, wait):
        self.upserted.extend(points)
        return SimpleNamespace(status="completed")

    def query_points(
        self,
        collection_name,
        query,
        query_filter,
        limit,
        with_payload,
        with_vectors,
    ):
        self.query_filter = query_filter
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    id="point-1",
                    score=0.91,
                    payload={
                        "user_id": "user-1",
                        "text": "Remember the timeout setting.",
                        "created_at": "2026-06-25T08:00:00+00:00",
                    },
                )
            ]
        )

    def scroll(
        self,
        collection_name,
        scroll_filter,
        limit,
        with_payload,
        with_vectors,
    ):
        self.scroll_filter = scroll_filter
        return (
            [
                SimpleNamespace(
                    id="older",
                    payload={
                        "user_id": "user-1",
                        "text": "Older",
                        "created_at": "2026-06-24T08:00:00+00:00",
                    },
                ),
                SimpleNamespace(
                    id="newer",
                    payload={
                        "user_id": "user-1",
                        "text": "Newer",
                        "created_at": "2026-06-25T08:00:00+00:00",
                    },
                ),
            ],
            None,
        )


class MemoryTests(unittest.TestCase):
    def test_text_vector_is_deterministic_and_normalized(self):
        first = memory._text_vector("Qdrant remembers user preferences")
        second = memory._text_vector("Qdrant remembers user preferences")
        self.assertEqual(first, second)
        self.assertEqual(len(first), memory.VECTOR_SIZE)
        magnitude = sum(value * value for value in first) ** 0.5
        self.assertAlmostEqual(magnitude, 1.0, places=6)

    def test_save_memory_upserts_user_scoped_payload(self):
        fake = FakeQdrantClient()
        with (
            patch.object(memory, "client", fake),
            patch.object(memory, "_collection_ready", True),
        ):
            result = memory.save_memory("user-1", "Remember my model choice.")
        self.assertTrue(result["ok"])
        self.assertEqual(len(fake.upserted), 1)
        self.assertEqual(fake.upserted[0].payload["user_id"], "user-1")
        self.assertEqual(fake.upserted[0].payload["text"], "Remember my model choice.")

    def test_search_memory_returns_payload_and_score(self):
        fake = FakeQdrantClient()
        with (
            patch.object(memory, "client", fake),
            patch.object(memory, "_collection_ready", True),
        ):
            results = memory.search_memory("user-1", "timeout")
        self.assertEqual(results[0]["text"], "Remember the timeout setting.")
        self.assertEqual(results[0]["score"], 0.91)
        condition = fake.query_filter.must[0]
        self.assertEqual(condition.key, "user_id")
        self.assertEqual(condition.match.value, "user-1")

    def test_recent_memories_are_sorted_newest_first(self):
        fake = FakeQdrantClient()
        with (
            patch.object(memory, "client", fake),
            patch.object(memory, "_collection_ready", True),
        ):
            results = memory.get_recent_memories("user-1")
        self.assertEqual([item["id"] for item in results], ["newer", "older"])

    def test_unavailable_qdrant_fails_gracefully(self):
        with (
            patch.object(memory, "client", None),
            patch.object(memory, "_collection_ready", False),
        ):
            saved = memory.save_memory("user-1", "text")
            searched = memory.search_memory("user-1", "text")
            recent = memory.get_recent_memories("user-1")
        self.assertFalse(saved["ok"])
        self.assertEqual(searched, [])
        self.assertEqual(recent, [])


if __name__ == "__main__":
    unittest.main()
