import os
import json
import hmac
import hashlib
import asyncio
import logging
import aiohttp
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

HOOK_EVENTS = {"PostRun", "OnFailure", "OnConverge", "OnMaxIter", "OnBudgetExceeded"}
HOOK_ACTIONS = {"notify", "webhook", "log"}

WEBHOOK_TIMEOUT = 10
WEBHOOK_RETRIES = 3
WEBHOOK_BACKOFF = [2, 4, 8]

HOOK_CHANNEL = "loopforge:hooks"


async def publish_event(event: str, payload: dict) -> None:
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        message = json.dumps({"event": event, "payload": payload})
        await redis.publish(HOOK_CHANNEL, message)
    except Exception as e:
        logger.warning("Hook publish failed: %s", e)


async def fire_hooks_for_event(
    user_id: str,
    loop_id: str,
    loop_run_id: str,
    event: str,
    context: dict,
) -> list[str]:
    from db.postgres import get_pool
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, action, config FROM hooks
               WHERE user_id = $1 AND loop_id = $2 AND event = $3 AND is_active = TRUE""",
            user_id, loop_id, event,
        )

    fired: list[str] = []
    tasks = []
    for row in rows:
        action = row["action"]
        config = row["config"] if isinstance(row["config"], dict) else json.loads(row["config"] or "{}")
        hook_id = str(row["id"])

        if action == "notify":
            tasks.append(_fire_notify(user_id, loop_run_id, context, config, hook_id))
        elif action == "webhook":
            tasks.append(_fire_webhook(loop_run_id, context, config, hook_id))
        elif action == "log":
            tasks.append(_fire_log(loop_run_id, event, context, hook_id))

        fired.append(f"{event}:{action}:{hook_id}")

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    return fired


async def _fire_notify(user_id: str, loop_run_id: str, context: dict, config: dict, hook_id: str) -> None:
    try:
        from core.notifier import send_notification, push_to_retry_queue
        from db.postgres import get_pool

        channel = config.get("channel", "telegram")
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT encrypted_config FROM notification_configs
                   WHERE user_id = $1 AND channel = $2 AND is_active = TRUE""",
                user_id, channel,
            )
        if not row:
            logger.warning("No active notification config for user %s channel %s", user_id, channel)
            return

        success = await send_notification(
            user_id=user_id,
            loop_run_id=loop_run_id,
            loop_name=context.get("loop_name", "Unknown"),
            status=context.get("status", "unknown"),
            final_score=context.get("final_score"),
            iterations=context.get("iterations", 0),
            output_summary=context.get("output_summary", ""),
            encrypted_config=bytes(row["encrypted_config"]),
            channel=channel,
        )
        if not success:
            await push_to_retry_queue(user_id, {
                "loop_run_id": loop_run_id,
                "channel": channel,
                "context": context,
            })
    except Exception as e:
        logger.error("Notify hook failed: %s", e)


async def _fire_webhook(loop_run_id: str, context: dict, config: dict, hook_id: str) -> None:
    url = config.get("url", "")
    secret = config.get("secret", "")
    if not url:
        return

    payload = json.dumps({"loop_run_id": loop_run_id, "event": context.get("event", "")})
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest() if secret else ""
    headers = {
        "Content-Type": "application/json",
        "X-LoopForge-Signature": f"sha256={sig}",
    }

    for attempt in range(WEBHOOK_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, data=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=WEBHOOK_TIMEOUT),
                ) as resp:
                    if resp.status < 400:
                        return
                    logger.warning("Webhook returned %d on attempt %d", resp.status, attempt + 1)
        except Exception as e:
            logger.warning("Webhook attempt %d failed: %s", attempt + 1, e)

        if attempt < WEBHOOK_RETRIES - 1:
            await asyncio.sleep(WEBHOOK_BACKOFF[attempt])

    logger.error("Webhook dead-lettered after %d attempts for hook %s", WEBHOOK_RETRIES, hook_id)
    await _write_dead_letter(loop_run_id, hook_id, "webhook_exhausted")


async def _fire_log(loop_run_id: str, event: str, context: dict, hook_id: str) -> None:
    try:
        from observability.langfuse_client import get_langfuse
        lf = get_langfuse()
        if lf:
            lf.event(
                name=f"hook:{event}",
                metadata={"loop_run_id": loop_run_id, "hook_id": hook_id, "context_keys": list(context.keys())},
            )
    except Exception as e:
        logger.warning("Log hook failed: %s", e)


async def _write_dead_letter(loop_run_id: str, hook_id: str, reason: str) -> None:
    try:
        from db.postgres import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO notification_log (user_id, loop_run_id, channel, status, last_error, created_at)
                   SELECT user_id, $1::uuid, 'webhook', 'failed', $2, NOW()
                   FROM loop_runs WHERE id = $1""",
                loop_run_id, reason,
            )
    except Exception as e:
        logger.warning("Dead letter write failed: %s", e)
