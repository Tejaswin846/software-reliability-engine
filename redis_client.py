from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
import zlib
from contextlib import closing, contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional
from urllib.parse import urlparse

try:
    from upstash_redis import Redis
except ImportError:  # pragma: no cover - exercised through the unavailable path
    Redis = None  # type: ignore[assignment]


LOGGER = logging.getLogger("software.redis")

REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").strip()
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
KEY_PREFIX = os.getenv("SOFTWARE_REDIS_KEY_PREFIX", "software").strip() or "software"
AI_CACHE_TTL_SECONDS = int(os.getenv("SOFTWARE_AI_CACHE_TTL_SECONDS", "3600"))
CONVERSATION_TTL_SECONDS = int(
    os.getenv("SOFTWARE_CONVERSATION_STATE_TTL_SECONDS", "21600")
)
SESSION_TTL_SECONDS = int(os.getenv("SOFTWARE_SESSION_CACHE_TTL_SECONDS", "3600"))
EXECUTION_STATE_TTL_SECONDS = int(
    os.getenv("SOFTWARE_AI_EXECUTION_STATE_TTL_SECONDS", "1800")
)
QUEUE_MAX_LENGTH = int(os.getenv("SOFTWARE_REDIS_QUEUE_MAX_LENGTH", "10000"))
DATABASE_SNAPSHOT_MAX_BYTES = max(
    1024 * 1024,
    int(os.getenv("SOFTWARE_REDIS_DATABASE_SNAPSHOT_MAX_BYTES", str(8 * 1024 * 1024))),
)
SDK_RETRIES = max(0, int(os.getenv("SOFTWARE_REDIS_RETRIES", "2")))
SDK_RETRY_INTERVAL = max(
    0.0, float(os.getenv("SOFTWARE_REDIS_RETRY_INTERVAL_SECONDS", "0.25"))
)

_client: Any = None
_client_lock = threading.RLock()
_local_metrics_lock = threading.RLock()
_local_metrics: Dict[str, int] = {
    "cache_hits": 0,
    "cache_misses": 0,
    "operation_failures": 0,
    "reconnects": 0,
}


def _configured() -> bool:
    return bool(REDIS_URL and REDIS_TOKEN and Redis is not None)


def _safe_endpoint() -> Optional[str]:
    if not REDIS_URL:
        return None
    parsed = urlparse(REDIS_URL)
    return parsed.hostname or "configured"


def _key(*parts: Any) -> str:
    normalized = [str(part).strip().replace(" ", "_") for part in parts]
    return ":".join([KEY_PREFIX, *normalized])


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _json_loads(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


def _record_local_metric(name: str, amount: int = 1) -> None:
    with _local_metrics_lock:
        _local_metrics[name] = int(_local_metrics.get(name, 0)) + amount


def _build_client() -> Any:
    if not _configured():
        return None
    return Redis(
        url=REDIS_URL,
        token=REDIS_TOKEN,
        rest_retries=SDK_RETRIES,
        rest_retry_interval=SDK_RETRY_INTERVAL,
    )


def initialize_redis(*, force: bool = False) -> Any:
    global _client
    if not _configured():
        return None
    with _client_lock:
        if _client is None or force:
            _client = _build_client()
            if force:
                _record_local_metric("reconnects")
    return _client


def _reset_client() -> None:
    global _client
    with _client_lock:
        _client = None


def _run(
    operation_name: str,
    operation: Callable[[Any], Any],
    *,
    default: Any = None,
    log_failure: bool = True,
) -> Any:
    if not _configured():
        return default
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            client = initialize_redis(force=attempt > 0)
            if client is None:
                return default
            return operation(client)
        except Exception as error:  # SDK exceptions vary by transport response
            last_error = error
            _reset_client()
            if attempt == 0:
                continue
    _record_local_metric("operation_failures")
    if log_failure and last_error is not None:
        LOGGER.warning(
            "Redis %s failed after reconnect: %s",
            operation_name,
            last_error.__class__.__name__,
        )
    return default


def _increment_metric(name: str) -> None:
    _record_local_metric(name)
    _run(
        f"metric:{name}",
        lambda client: client.incr(_key("metrics", name)),
        log_failure=False,
    )


def _metric_values() -> Dict[str, int]:
    names = ["cache_hits", "cache_misses", "operation_failures", "reconnects"]
    remote = _run(
        "metrics",
        lambda client: client.mget(*[_key("metrics", name) for name in names]),
        default=None,
        log_failure=False,
    )
    if isinstance(remote, list):
        return {
            name: int(remote[index] or 0)
            for index, name in enumerate(names)
        }
    with _local_metrics_lock:
        return {name: int(_local_metrics.get(name, 0)) for name in names}


def _parse_memory_info(value: Any) -> Dict[str, Any]:
    if not isinstance(value, str):
        return {"memory_usage_bytes": None, "memory_usage": "Unavailable"}
    values: Dict[str, str] = {}
    for line in value.splitlines():
        if ":" not in line or line.startswith("#"):
            continue
        name, raw = line.split(":", 1)
        values[name.strip()] = raw.strip()
    raw_bytes = values.get("used_memory")
    return {
        "memory_usage_bytes": int(raw_bytes) if raw_bytes and raw_bytes.isdigit() else None,
        "memory_usage": values.get("used_memory_human") or "Unavailable",
    }


def redis_health_check() -> Dict[str, Any]:
    configured = _configured()
    if not configured:
        metrics = _metric_values()
        return {
            "ok": True,
            "configured": False,
            "connected": False,
            "status": "Not configured",
            "latency_ms": None,
            "cache_hits": metrics["cache_hits"],
            "cache_misses": metrics["cache_misses"],
            "cache_hit_rate": 0.0,
            "memory_usage": "Unavailable",
            "memory_usage_bytes": None,
            "database_keys": None,
            "queue_depth": 0,
            "endpoint": None,
        }

    started = time.perf_counter()
    pong = _run("health check", lambda client: client.ping(), default=None)
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    connected = pong is not None
    metrics = _metric_values()
    total_cache = metrics["cache_hits"] + metrics["cache_misses"]
    info = (
        _run(
            "memory info",
            lambda client: client.execute(["INFO", "memory"]),
            default=None,
            log_failure=False,
        )
        if connected
        else None
    )
    memory = _parse_memory_info(info)
    database_keys = (
        _run("database size", lambda client: client.dbsize(), default=None)
        if connected
        else None
    )
    queue_depth = (
        _run(
            "queue depth",
            lambda client: client.llen(_key("queue", "background")),
            default=0,
            log_failure=False,
        )
        if connected
        else 0
    )
    return {
        "ok": connected,
        "configured": True,
        "connected": connected,
        "status": "Connected" if connected else "Unavailable",
        "latency_ms": latency_ms if connected else None,
        "cache_hits": metrics["cache_hits"],
        "cache_misses": metrics["cache_misses"],
        "cache_hit_rate": (
            round(metrics["cache_hits"] / total_cache * 100.0, 2)
            if total_cache
            else 0.0
        ),
        "memory_usage": memory["memory_usage"],
        "memory_usage_bytes": memory["memory_usage_bytes"],
        "database_keys": int(database_keys) if database_keys is not None else None,
        "queue_depth": int(queue_depth or 0),
        "endpoint": _safe_endpoint(),
        "operation_failures": metrics["operation_failures"],
        "reconnects": metrics["reconnects"],
    }


def save_sqlite_snapshot(path: Path) -> Dict[str, Any]:
    """Save a consistent compressed SQLite snapshot to durable Redis storage."""

    source = Path(path)
    if not source.is_file():
        return {"ok": False, "stored": False, "error": "Database file does not exist."}
    if not _configured():
        return {"ok": False, "stored": False, "error": "Redis is not configured."}
    temporary = source.with_name(f".{source.name}.{uuid.uuid4().hex}.snapshot")
    try:
        with closing(sqlite3.connect(source, timeout=30)) as database, closing(
            sqlite3.connect(temporary)
        ) as snapshot:
            database.backup(snapshot)
        serialized = temporary.read_bytes()
        compressed = zlib.compress(serialized, level=9)
        if len(compressed) > DATABASE_SNAPSHOT_MAX_BYTES:
            return {
                "ok": False,
                "stored": False,
                "error": "Compressed database snapshot exceeds the configured size limit.",
            }
        payload = _json_dumps(
            {
                "version": 1,
                "created_at": time.time(),
                "sha256": hashlib.sha256(serialized).hexdigest(),
                "data": base64.b64encode(compressed).decode("ascii"),
            }
        )
        stored = _run(
            "database snapshot save",
            lambda client: client.set(_key("persistence", "sqlite", "api", "v1"), payload),
            default=None,
        )
    except (OSError, sqlite3.Error, ValueError, zlib.error) as error:
        LOGGER.warning("Could not create database snapshot: %s", error.__class__.__name__)
        return {"ok": False, "stored": False, "error": "Could not create database snapshot."}
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    if stored is None:
        return {"ok": False, "stored": False, "error": "Redis did not store the database snapshot."}
    return {
        "ok": True,
        "stored": True,
        "bytes": len(serialized),
        "compressed_bytes": len(compressed),
    }


def restore_sqlite_snapshot(path: Path) -> Dict[str, Any]:
    """Restore a verified SQLite snapshot before the application opens the database."""

    target = Path(path)
    if not _configured():
        return {"ok": True, "restored": False, "reason": "redis_not_configured"}
    payload = _run(
        "database snapshot restore",
        lambda client: client.get(_key("persistence", "sqlite", "api", "v1")),
        default=None,
    )
    if not payload:
        return {"ok": True, "restored": False, "reason": "snapshot_not_found"}
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.restore")
    try:
        envelope = _json_loads(payload, default={})
        if not isinstance(envelope, dict) or envelope.get("version") != 1:
            raise ValueError("Unsupported database snapshot format.")
        compressed = base64.b64decode(str(envelope.get("data") or ""), validate=True)
        serialized = zlib.decompress(compressed)
        expected_hash = str(envelope.get("sha256") or "")
        if not expected_hash or not hmac.compare_digest(
            hashlib.sha256(serialized).hexdigest(), expected_hash
        ):
            raise ValueError("Database snapshot checksum does not match.")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(serialized)
        with closing(sqlite3.connect(temporary)) as database:
            quick_check = database.execute("PRAGMA quick_check").fetchone()
        if not quick_check or str(quick_check[0]).lower() != "ok":
            raise ValueError("Database snapshot failed SQLite integrity validation.")
        os.replace(temporary, target)
    except (OSError, sqlite3.Error, ValueError, zlib.error) as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        LOGGER.warning("Could not restore database snapshot: %s", error.__class__.__name__)
        return {"ok": False, "restored": False, "error": "Stored database snapshot is invalid."}
    return {"ok": True, "restored": True, "bytes": len(serialized)}


def _ai_cache_key(user_id: str, prompt: str, model: Optional[str] = None) -> str:
    digest = hashlib.sha256(
        f"{user_id}\n{model or 'default'}\n{prompt.strip()}".encode("utf-8")
    ).hexdigest()
    return _key("cache", "ai", digest)


def cache_ai_response(
    user_id: str,
    prompt: str,
    response: Any,
    *,
    model: Optional[str] = None,
    ttl_seconds: int = AI_CACHE_TTL_SECONDS,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not prompt.strip():
        return {"ok": False, "cached": False, "reason": "Prompt is empty."}
    payload = {
        "response": response,
        "model": model,
        "metadata": metadata or {},
        "cached_at": time.time(),
    }
    stored = _run(
        "cache AI response",
        lambda client: client.set(
            _ai_cache_key(user_id, prompt, model),
            _json_dumps(payload),
            ex=max(1, ttl_seconds),
        ),
        default=False,
    )
    return {
        "ok": bool(stored),
        "cached": bool(stored),
        "ttl_seconds": max(1, ttl_seconds),
    }


def get_cached_ai_response(
    user_id: str,
    prompt: str,
    *,
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    value = _run(
        "get cached AI response",
        lambda client: client.get(_ai_cache_key(user_id, prompt, model)),
        default=None,
    )
    if value is None:
        _increment_metric("cache_misses")
        return None
    parsed = _json_loads(value)
    if not isinstance(parsed, dict) or "response" not in parsed:
        _increment_metric("cache_misses")
        return None
    _increment_metric("cache_hits")
    return parsed


def set_conversation_state(
    user_id: str,
    chat_id: str,
    state: Dict[str, Any],
    *,
    ttl_seconds: int = CONVERSATION_TTL_SECONDS,
) -> bool:
    payload = {"user_id": user_id, "chat_id": chat_id, **state}
    return bool(
        _run(
            "set conversation state",
            lambda client: client.set(
                _key("conversation", user_id, chat_id),
                _json_dumps(payload),
                ex=max(1, ttl_seconds),
            ),
            default=False,
        )
    )


def get_conversation_state(user_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
    value = _run(
        "get conversation state",
        lambda client: client.get(_key("conversation", user_id, chat_id)),
        default=None,
    )
    parsed = _json_loads(value)
    if isinstance(parsed, dict) and str(parsed.get("user_id")) == str(user_id):
        return parsed
    return None


def delete_conversation_state(user_id: str, chat_id: str) -> bool:
    return bool(
        _run(
            "delete conversation state",
            lambda client: client.delete(_key("conversation", user_id, chat_id)),
            default=False,
        )
    )


def set_session_cache(
    session_id: str,
    value: Dict[str, Any],
    *,
    ttl_seconds: int = SESSION_TTL_SECONDS,
) -> bool:
    return bool(
        _run(
            "set session cache",
            lambda client: client.set(
                _key("session", session_id),
                _json_dumps(value),
                ex=max(1, ttl_seconds),
            ),
            default=False,
        )
    )


def get_session_cache(session_id: str) -> Optional[Dict[str, Any]]:
    value = _run(
        "get session cache",
        lambda client: client.get(_key("session", session_id)),
        default=None,
    )
    parsed = _json_loads(value)
    return parsed if isinstance(parsed, dict) else None


def delete_session_cache(session_id: str) -> bool:
    return bool(
        _run(
            "delete session cache",
            lambda client: client.delete(_key("session", session_id)),
            default=False,
        )
    )


def set_execution_state(
    user_id: str,
    request_id: str,
    value: Dict[str, Any],
    *,
    ttl_seconds: int = EXECUTION_STATE_TTL_SECONDS,
) -> bool:
    payload = {"user_id": user_id, "request_id": request_id, **value}
    return bool(
        _run(
            "set AI execution state",
            lambda client: client.set(
                _key("ai-execution", user_id, request_id),
                _json_dumps(payload),
                ex=max(1, ttl_seconds),
            ),
            default=False,
        )
    )


def get_execution_state(
    user_id: str,
    request_id: str,
) -> Optional[Dict[str, Any]]:
    value = _run(
        "get AI execution state",
        lambda client: client.get(_key("ai-execution", user_id, request_id)),
        default=None,
    )
    parsed = _json_loads(value)
    if (
        isinstance(parsed, dict)
        and str(parsed.get("user_id")) == str(user_id)
        and str(parsed.get("request_id")) == str(request_id)
    ):
        return parsed
    return None


def delete_execution_state(user_id: str, request_id: str) -> bool:
    return bool(
        _run(
            "delete AI execution state",
            lambda client: client.delete(_key("ai-execution", user_id, request_id)),
            default=False,
        )
    )


def enqueue_background_job(
    job_type: str,
    payload: Dict[str, Any],
    *,
    queue_name: str = "background",
) -> Dict[str, Any]:
    job = {
        "id": f"job_{uuid.uuid4().hex}",
        "type": job_type,
        "payload": payload,
        "queued_at": time.time(),
        "attempts": 0,
    }

    def push(client: Any) -> Any:
        pipeline = client.pipeline()
        pipeline.rpush(_key("queue", queue_name), _json_dumps(job))
        pipeline.ltrim(_key("queue", queue_name), -QUEUE_MAX_LENGTH, -1)
        return pipeline.exec()

    result = _run("enqueue background job", push, default=None)
    return {"ok": result is not None, "job": job if result is not None else None}


def dequeue_background_job(
    *,
    queue_name: str = "background",
) -> Optional[Dict[str, Any]]:
    value = _run(
        "dequeue background job",
        lambda client: client.lpop(_key("queue", queue_name)),
        default=None,
    )
    parsed = _json_loads(value)
    return parsed if isinstance(parsed, dict) else None


def background_queue_depth(*, queue_name: str = "background") -> int:
    value = _run(
        "background queue depth",
        lambda client: client.llen(_key("queue", queue_name)),
        default=0,
    )
    return int(value or 0)


RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


def check_rate_limit(
    identity: str,
    *,
    limit: int,
    window_seconds: int,
    scope: str = "api",
) -> Dict[str, Any]:
    if limit <= 0:
        return {
            "allowed": True,
            "limit": limit,
            "remaining": 0,
            "reset_seconds": 0,
            "degraded": False,
        }
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    result = _run(
        "rate limit",
        lambda client: client.eval(
            RATE_LIMIT_SCRIPT,
            keys=[_key("rate", scope, digest)],
            args=[str(max(1, window_seconds))],
        ),
        default=None,
        log_failure=False,
    )
    if not isinstance(result, list) or len(result) < 2:
        return {
            "allowed": True,
            "limit": limit,
            "remaining": limit,
            "reset_seconds": max(1, window_seconds),
            "degraded": _configured(),
        }
    current = int(result[0] or 0)
    ttl = max(0, int(result[1] or 0))
    return {
        "allowed": current <= limit,
        "limit": limit,
        "remaining": max(0, limit - current),
        "reset_seconds": ttl,
        "degraded": False,
    }


RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def acquire_lock(
    resource: str,
    *,
    ttl_seconds: int = 30,
    wait_seconds: float = 0.0,
    retry_interval_seconds: float = 0.05,
) -> Dict[str, Any]:
    if not _configured():
        return {"acquired": True, "token": None, "degraded": True}
    token = uuid.uuid4().hex
    lock_key = _key("lock", resource)
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        acquired = _run(
            "acquire lock",
            lambda client: client.set(
                lock_key,
                token,
                nx=True,
                px=max(1, ttl_seconds * 1000),
            ),
            default=None,
            log_failure=False,
        )
        if acquired:
            return {"acquired": True, "token": token, "degraded": False}
        if time.monotonic() >= deadline:
            available = redis_health_check()["connected"]
            return {
                "acquired": not available,
                "token": None,
                "degraded": not available,
            }
        time.sleep(max(0.01, retry_interval_seconds))


def release_lock(resource: str, token: Optional[str]) -> bool:
    if not token:
        return True
    result = _run(
        "release lock",
        lambda client: client.eval(
            RELEASE_LOCK_SCRIPT,
            keys=[_key("lock", resource)],
            args=[token],
        ),
        default=0,
        log_failure=False,
    )
    return bool(result)


@contextmanager
def distributed_lock(
    resource: str,
    *,
    ttl_seconds: int = 30,
    wait_seconds: float = 0.0,
) -> Iterator[Dict[str, Any]]:
    lock = acquire_lock(
        resource,
        ttl_seconds=ttl_seconds,
        wait_seconds=wait_seconds,
    )
    try:
        yield lock
    finally:
        release_lock(resource, lock.get("token"))


def reset_redis_state_for_tests() -> None:
    global _client
    with _client_lock:
        _client = None
    with _local_metrics_lock:
        for name in _local_metrics:
            _local_metrics[name] = 0
