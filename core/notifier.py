import os
import json
import logging
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("BASE_URL", "http://localhost:8010")
_RATE_LIMITER_TTL = 2  # 1 msg/sec enforced with 2s TTL bucket


def _get_fernet() -> Fernet:
    key = os.getenv("NOTIFICATION_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("NOTIFICATION_ENCRYPTION_KEY not set")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_config(config: dict) -> bytes:
    f = _get_fernet()
    return f.encrypt(json.dumps(config).encode())


def decrypt_config(encrypted: bytes) -> dict:
    f = _get_fernet()
    return json.loads(f.decrypt(encrypted).decode())


def _format_message(loop_name: str, status: str, final_score: float | None,
                    iterations: int, output_summary: str, loop_run_id: str) -> str:
    summary = output_summary[:200] + "…" if len(output_summary) > 200 else output_summary
    score_str = f"{final_score:.2f}" if final_score is not None else "N/A"
    return (
        f"*LoopForge — {loop_name}*\n"
        f"Status: `{status}`\n"
        f"Score: {score_str} | Iterations: {iterations}\n"
        f"Summary: {summary}\n"
        f"Full output: {BASE_URL}/loop-runs/{loop_run_id}"
    )


async def _redis_rate_limit(key: str) -> None:
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        exists = await redis.get(key)
        if exists:
            await asyncio.sleep(1.1)
        await redis.setex(key, _RATE_LIMITER_TTL, "1")
    except Exception:
        pass


class BaseNotifier(ABC):
    @abstractmethod
    async def send(self, user_id: str, message: str, config: dict) -> bool:
        ...


class TelegramNotifier(BaseNotifier):
    async def send(self, user_id: str, message: str, config: dict) -> bool:
        try:
            from telegram import Bot
            bot_token = config["bot_token"]
            chat_id = config["chat_id"]
            await _redis_rate_limit(f"notif_rate:telegram:{chat_id}")
            bot = Bot(token=bot_token)
            escaped = message.replace(".", r"\.").replace("-", r"\-").replace("(", r"\(").replace(")", r"\)")
            chunks = [escaped[i:i+4096] for i in range(0, len(escaped), 4096)]
            for chunk in chunks:
                await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="MarkdownV2")
            return True
        except Exception as e:
            logger.warning("Telegram send failed: %s", e)
            return False


class SlackNotifier(BaseNotifier):
    async def send(self, user_id: str, message: str, config: dict) -> bool:
        try:
            from slack_sdk.web.async_client import AsyncWebClient
            token = config["bot_token"]
            channel = config["channel"]
            await _redis_rate_limit(f"notif_rate:slack:{channel}")
            client = AsyncWebClient(token=token)
            await client.chat_postMessage(
                channel=channel,
                blocks=[
                    {"type": "section", "text": {"type": "mrkdwn", "text": message}},
                ],
                text=message,
            )
            return True
        except Exception as e:
            logger.warning("Slack send failed: %s", e)
            return False


class EmailNotifier(BaseNotifier):
    async def send(self, user_id: str, message: str, config: dict) -> bool:
        try:
            import sendgrid
            from sendgrid.helpers.mail import Mail
            sg = sendgrid.SendGridAPIClient(api_key=config["sendgrid_api_key"])
            mail = Mail(
                from_email="noreply@loopforge.ai",
                to_emails=config["recipient"],
                subject="LoopForge Loop Run Notification",
                plain_text_content=message,
                html_content=f"<pre>{message}</pre>",
            )
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: sg.send(mail))
            return response.status_code in (200, 202)
        except Exception as e:
            logger.warning("Email send failed: %s", e)
            return False


_CHANNEL_MAP: dict[str, BaseNotifier] = {
    "telegram": TelegramNotifier(),
    "slack": SlackNotifier(),
    "email": EmailNotifier(),
}

_MAX_RETRIES = 5
_RETRY_DELAYS = [2, 4, 8, 16, 32]


async def send_notification(
    user_id: str,
    loop_run_id: str,
    loop_name: str,
    status: str,
    final_score: float | None,
    iterations: int,
    output_summary: str,
    encrypted_config: bytes,
    channel: str,
) -> bool:
    notifier = _CHANNEL_MAP.get(channel)
    if not notifier:
        logger.warning("Unknown notification channel: %s", channel)
        return False

    try:
        config = decrypt_config(encrypted_config)
    except Exception as e:
        logger.error("Failed to decrypt notification config for user %s: %s", user_id, type(e).__name__)
        return False

    message = _format_message(loop_name, status, final_score, iterations, output_summary, loop_run_id)

    for attempt in range(_MAX_RETRIES):
        success = await notifier.send(user_id, message, config)
        if success:
            return True
        if attempt < _MAX_RETRIES - 1:
            delay = _RETRY_DELAYS[attempt]
            logger.warning("Notification attempt %d failed, retrying in %ds", attempt + 1, delay)
            await asyncio.sleep(delay)

    logger.error("All %d notification attempts failed for user %s channel %s", _MAX_RETRIES, user_id, channel)
    return False


async def push_to_retry_queue(user_id: str, payload: dict) -> None:
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        await redis.rpush(f"notif:retry:{user_id}", json.dumps(payload))
    except Exception as e:
        logger.warning("Failed to push to retry queue: %s", e)
