from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient, models

try:
    from .sentry_monitoring import capture_operational_error, redact_text
except ImportError:
    from sentry_monitoring import capture_operational_error, redact_text


LOGGER = logging.getLogger("software.memory")

QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "").strip()
COLLECTION_NAME = "software_memory"
VECTOR_SIZE = 256
DEFAULT_SEARCH_LIMIT = 5
DEFAULT_RECENT_LIMIT = 20

client: Optional[QdrantClient] = (
    QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
        timeout=10,
    )
    if QDRANT_URL and QDRANT_API_KEY
    else None
)

_collection_ready = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text_vector(text: str) -> List[float]:
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    features = list(tokens)
    features.extend(
        f"{tokens[index]}::{tokens[index + 1]}"
        for index in range(len(tokens) - 1)
    )
    if not features:
        features = [text.strip().lower() or "empty"]

    vector = [0.0] * VECTOR_SIZE
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_SIZE
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        vector[0] = 1.0
        return vector
    return [value / magnitude for value in vector]


def _user_filter(user_id: str) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="user_id",
                match=models.MatchValue(value=user_id),
            )
        ]
    )


def _ensure_collection() -> bool:
    global _collection_ready
    if _collection_ready:
        return True
    if client is None:
        LOGGER.warning("Qdrant memory is disabled because credentials are missing.")
        return False

    try:
        if not client.collection_exists(COLLECTION_NAME):
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=VECTOR_SIZE,
                    distance=models.Distance.COSINE,
                ),
            )
            LOGGER.info("Created Qdrant collection %s.", COLLECTION_NAME)
        else:
            collection = client.get_collection(COLLECTION_NAME)
            vectors = collection.config.params.vectors
            vector_size = getattr(vectors, "size", None)
            if vector_size is not None and int(vector_size) != VECTOR_SIZE:
                LOGGER.error(
                    "Qdrant collection %s uses vector size %s; expected %s.",
                    COLLECTION_NAME,
                    vector_size,
                    VECTOR_SIZE,
                )
                return False

        try:
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="user_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
                wait=True,
            )
        except Exception as error:
            if "already exists" not in str(error).lower():
                LOGGER.warning(
                    "Could not create Qdrant user_id index: %s",
                    redact_text(str(error)),
                )
                capture_operational_error(
                    error,
                    category="qdrant_failure",
                    level="warning",
                    provider="qdrant",
                    operation="create_user_id_index",
                )

        try:
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="created_at",
                field_schema=models.PayloadSchemaType.DATETIME,
                wait=True,
            )
        except Exception as error:
            if "already exists" not in str(error).lower():
                LOGGER.warning(
                    "Could not create Qdrant created_at index: %s",
                    redact_text(str(error)),
                )
                capture_operational_error(
                    error,
                    category="qdrant_failure",
                    level="warning",
                    provider="qdrant",
                    operation="create_created_at_index",
                )

        _collection_ready = True
        return True
    except Exception as error:
        LOGGER.error(
            "Qdrant collection initialization failed: %s",
            redact_text(str(error)),
        )
        capture_operational_error(
            error,
            category="qdrant_failure",
            provider="qdrant",
            operation="initialize_collection",
        )
        return False


def _point_payload(point: Any, score: Optional[float] = None) -> Dict[str, Any]:
    payload = dict(getattr(point, "payload", None) or {})
    result = {
        "id": str(getattr(point, "id", "")),
        "user_id": payload.get("user_id"),
        "text": payload.get("text", ""),
        "created_at": payload.get("created_at"),
    }
    if score is not None:
        result["score"] = round(float(score), 6)
    return result


def save_memory(user_id: str, text: str) -> Dict[str, Any]:
    clean_user_id = user_id.strip()
    clean_text = text.strip()
    if not clean_user_id or not clean_text:
        return {
            "ok": False,
            "stored": False,
            "error": "user_id and text are required.",
        }
    if not _ensure_collection() or client is None:
        return {
            "ok": False,
            "stored": False,
            "error": "Qdrant memory is unavailable.",
        }

    point_id = str(uuid.uuid4())
    created_at = _now_iso()
    try:
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=_text_vector(clean_text),
                    payload={
                        "user_id": clean_user_id,
                        "text": clean_text,
                        "created_at": created_at,
                    },
                )
            ],
            wait=True,
        )
        LOGGER.info("Saved Qdrant memory for user %s.", clean_user_id)
        return {
            "ok": True,
            "stored": True,
            "id": point_id,
            "created_at": created_at,
        }
    except Exception as error:
        LOGGER.error(
            "Could not save Qdrant memory for user %s: %s",
            clean_user_id,
            redact_text(str(error)),
        )
        capture_operational_error(
            error,
            category="qdrant_failure",
            user_id=clean_user_id,
            provider="qdrant",
            operation="save_memory",
        )
        return {
            "ok": False,
            "stored": False,
            "error": redact_text(str(error)),
        }


def search_memory(
    user_id: str,
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> List[Dict[str, Any]]:
    clean_user_id = user_id.strip()
    clean_query = query.strip()
    if not clean_user_id or not clean_query:
        return []
    if not _ensure_collection() or client is None:
        return []

    try:
        response = client.query_points(
            collection_name=COLLECTION_NAME,
            query=_text_vector(clean_query),
            query_filter=_user_filter(clean_user_id),
            limit=max(1, min(limit, 50)),
            with_payload=True,
            with_vectors=False,
        )
        memories = [
            _point_payload(point, getattr(point, "score", 0.0))
            for point in response.points
        ]
        LOGGER.info(
            "Retrieved %s relevant Qdrant memories for user %s.",
            len(memories),
            clean_user_id,
        )
        return memories
    except Exception as error:
        LOGGER.error(
            "Could not search Qdrant memories for user %s: %s",
            clean_user_id,
            redact_text(str(error)),
        )
        capture_operational_error(
            error,
            category="qdrant_failure",
            user_id=clean_user_id,
            provider="qdrant",
            operation="search_memory",
        )
        return []


def get_recent_memories(
    user_id: str,
    limit: int = DEFAULT_RECENT_LIMIT,
) -> List[Dict[str, Any]]:
    clean_user_id = user_id.strip()
    if not clean_user_id:
        return []
    if not _ensure_collection() or client is None:
        return []

    try:
        points, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=_user_filter(clean_user_id),
            limit=max(20, min(limit * 5, 250)),
            with_payload=True,
            with_vectors=False,
        )
        memories = [_point_payload(point) for point in points]
        memories.sort(
            key=lambda item: item.get("created_at") or "",
            reverse=True,
        )
        return memories[: max(1, min(limit, 100))]
    except Exception as error:
        LOGGER.error(
            "Could not load recent Qdrant memories for user %s: %s",
            clean_user_id,
            redact_text(str(error)),
        )
        capture_operational_error(
            error,
            category="qdrant_failure",
            user_id=clean_user_id,
            provider="qdrant",
            operation="get_recent_memories",
        )
        return []


def memory_health_check() -> Dict[str, Any]:
    configured = bool(QDRANT_URL and QDRANT_API_KEY)
    if not configured:
        return {
            "ok": False,
            "configured": False,
            "available": False,
            "collection": COLLECTION_NAME,
            "error": "QDRANT_URL and QDRANT_API_KEY are required.",
        }
    available = _ensure_collection()
    return {
        "ok": available,
        "configured": True,
        "available": available,
        "collection": COLLECTION_NAME,
        "url": QDRANT_URL,
        "error": None if available else "Qdrant memory is unavailable.",
    }


def reset_memory_client() -> None:
    global client, _collection_ready, QDRANT_URL, QDRANT_API_KEY
    QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
    QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "").strip()
    client = (
        QdrantClient(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY,
            timeout=10,
        )
        if QDRANT_URL and QDRANT_API_KEY
        else None
    )
    _collection_ready = False
