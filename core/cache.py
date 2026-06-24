import hashlib
import json
import logging

logger = logging.getLogger(__name__)

CACHE_TTL = 3600  # 1 hour


def _cache_key(user_id: str, task_input: str) -> str:
    digest = hashlib.sha256(task_input.strip().lower().encode()).hexdigest()[:16]
    return f"task_cache:{user_id}:{digest}"


async def get_cached_result(user_id: str, task_input: str) -> dict | None:
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        key = _cache_key(user_id, task_input)
        raw = await redis.get(key)
        if raw:
            logger.debug("Cache hit for key %s", key)
            return json.loads(raw)
    except Exception as e:
        logger.debug("Cache get failed: %s", e)
    return None


async def set_cached_result(user_id: str, task_input: str, result: dict) -> None:
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        key = _cache_key(user_id, task_input)
        await redis.setex(key, CACHE_TTL, json.dumps(result))
    except Exception as e:
        logger.debug("Cache set failed: %s", e)
