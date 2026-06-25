from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import redis_client


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.results = []

    def rpush(self, key, value):
        self.results.append(self.client.rpush(key, value))
        return self

    def ltrim(self, key, start, stop):
        self.results.append(self.client.ltrim(key, start, stop))
        return self

    def exec(self):
        return self.results


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.lists = {}
        self.rate_counts = {}

    def ping(self):
        return "PONG"

    def set(self, key, value, nx=None, **_kwargs):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                removed += 1
        return removed

    def incr(self, key):
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = value
        return value

    def mget(self, *keys):
        return [self.values.get(key) for key in keys]

    def dbsize(self):
        return len(self.values) + len(self.lists)

    def execute(self, command):
        if command[:2] == ["INFO", "memory"]:
            return "# Memory\r\nused_memory:2048\r\nused_memory_human:2KB\r\n"
        return None

    def pipeline(self):
        return FakePipeline(self)

    def rpush(self, key, *elements):
        target = self.lists.setdefault(key, [])
        target.extend(elements)
        return len(target)

    def ltrim(self, key, start, stop):
        target = self.lists.setdefault(key, [])
        length = len(target)
        normalized_start = start if start >= 0 else max(0, length + start)
        normalized_stop = stop if stop >= 0 else length + stop
        self.lists[key] = target[normalized_start:normalized_stop + 1]
        return True

    def lpop(self, key):
        target = self.lists.setdefault(key, [])
        return target.pop(0) if target else None

    def llen(self, key):
        return len(self.lists.get(key, []))

    def eval(self, script, keys=None, args=None):
        key = keys[0]
        if "INCR" in script:
            current = int(self.rate_counts.get(key, 0)) + 1
            self.rate_counts[key] = current
            return [current, int(args[0])]
        if self.values.get(key) == args[0]:
            del self.values[key]
            return 1
        return 0


class FailingRedis:
    def get(self, _key):
        raise RuntimeError("transport failed")


class RedisClientTests(unittest.TestCase):
    def setUp(self):
        redis_client.reset_redis_state_for_tests()
        self.fake = FakeRedis()
        self.config = patch.multiple(
            redis_client,
            REDIS_URL="https://example.upstash.io",
            REDIS_TOKEN="test-token",
            _client=self.fake,
        )
        self.config.start()

    def tearDown(self):
        self.config.stop()
        redis_client.reset_redis_state_for_tests()

    def test_health_reports_latency_metrics_and_memory(self):
        health = redis_client.redis_health_check()
        self.assertTrue(health["ok"])
        self.assertTrue(health["connected"])
        self.assertEqual(health["memory_usage"], "2KB")
        self.assertEqual(health["memory_usage_bytes"], 2048)
        self.assertEqual(health["endpoint"], "example.upstash.io")

    def test_ai_response_cache_tracks_hits_and_misses(self):
        missing = redis_client.get_cached_ai_response("user-1", "hello")
        self.assertIsNone(missing)

        stored = redis_client.cache_ai_response(
            "user-1",
            "hello",
            "cached answer",
            model="model-a",
        )
        cached = redis_client.get_cached_ai_response(
            "user-1",
            "hello",
            model="model-a",
        )

        self.assertTrue(stored["cached"])
        self.assertEqual(cached["response"], "cached answer")
        health = redis_client.redis_health_check()
        self.assertEqual(health["cache_hits"], 1)
        self.assertEqual(health["cache_misses"], 1)

    def test_conversation_and_session_state_are_scoped(self):
        self.assertTrue(
            redis_client.set_conversation_state(
                "user-1",
                "chat-1",
                {"messages": [{"content": "hello"}]},
            )
        )
        state = redis_client.get_conversation_state("user-1", "chat-1")
        self.assertEqual(state["messages"][0]["content"], "hello")
        self.assertIsNone(redis_client.get_conversation_state("user-2", "chat-1"))

        self.assertTrue(
            redis_client.set_session_cache(
                "session-hash",
                {"user": {"id": "user-1"}},
            )
        )
        self.assertEqual(
            redis_client.get_session_cache("session-hash")["user"]["id"],
            "user-1",
        )
        self.assertTrue(redis_client.delete_session_cache("session-hash"))

        self.assertTrue(
            redis_client.set_execution_state(
                "user-1",
                "request-1",
                {"status": "awaiting_confirmation"},
            )
        )
        execution = redis_client.get_execution_state("user-1", "request-1")
        self.assertEqual(execution["status"], "awaiting_confirmation")
        self.assertIsNone(
            redis_client.get_execution_state("user-2", "request-1")
        )
        self.assertTrue(
            redis_client.delete_execution_state("user-1", "request-1")
        )

    def test_queue_rate_limit_and_distributed_lock(self):
        queued = redis_client.enqueue_background_job(
            "benchmark.refresh",
            {"run_id": "run-1"},
        )
        self.assertTrue(queued["ok"])
        self.assertEqual(redis_client.background_queue_depth(), 1)
        job = redis_client.dequeue_background_job()
        self.assertEqual(job["payload"]["run_id"], "run-1")

        first = redis_client.check_rate_limit(
            "user-1",
            limit=2,
            window_seconds=60,
        )
        second = redis_client.check_rate_limit(
            "user-1",
            limit=2,
            window_seconds=60,
        )
        third = redis_client.check_rate_limit(
            "user-1",
            limit=2,
            window_seconds=60,
        )
        self.assertTrue(first["allowed"])
        self.assertTrue(second["allowed"])
        self.assertFalse(third["allowed"])

        lock = redis_client.acquire_lock("workflow:1")
        blocked = redis_client.acquire_lock("workflow:1")
        self.assertTrue(lock["acquired"])
        self.assertFalse(blocked["acquired"])
        self.assertTrue(redis_client.release_lock("workflow:1", lock["token"]))

    def test_failed_operation_recreates_the_client(self):
        redis_client._client = FailingRedis()
        replacement = FakeRedis()
        replacement.set("key", json.dumps({"value": 1}))
        with patch.object(redis_client, "_build_client", return_value=replacement):
            result = redis_client._run(
                "reconnect test",
                lambda client: client.get("key"),
            )
        self.assertEqual(json.loads(result)["value"], 1)

    def test_missing_credentials_fail_gracefully(self):
        with patch.multiple(redis_client, REDIS_URL="", REDIS_TOKEN="", _client=None):
            health = redis_client.redis_health_check()
            limit = redis_client.check_rate_limit(
                "user-1",
                limit=1,
                window_seconds=60,
            )
            lock = redis_client.acquire_lock("workflow:missing")
        self.assertTrue(health["ok"])
        self.assertFalse(health["configured"])
        self.assertTrue(limit["allowed"])
        self.assertTrue(lock["acquired"])
        self.assertTrue(lock["degraded"])


if __name__ == "__main__":
    unittest.main()
