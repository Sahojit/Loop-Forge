import time
import logging
from fastapi import HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from db.redis_client import get_redis

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


def _hour_timestamp() -> int:
    return int(time.time()) // 3600


def _rate_key(user_id: str) -> str:
    return f"ratelimit:{user_id}:{_hour_timestamp()}"


async def check_user_rate_limit(user_id: str, tasks_per_hour: int | None) -> None:
    if tasks_per_hour is None:
        return

    redis = await get_redis()
    key = _rate_key(user_id)

    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 3600)
        if count > tasks_per_hour:
            raise HTTPException(
                status_code=429,
                detail={"error": "Rate limit exceeded", "code": "RATE_LIMIT_EXCEEDED"},
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Rate limit check failed, allowing request: %s", e)
