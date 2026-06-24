import os
import logging
import asyncio
from datetime import date, datetime, timezone
from typing import Any

import pytz

logger = logging.getLogger(__name__)

MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT_SECONDS", "10"))


async def _fetch_with_timeout(coro, fallback, label: str):
    try:
        return await asyncio.wait_for(coro, timeout=MCP_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("MCP fetch timeout (%ds) for %s", MCP_TIMEOUT, label)
        return fallback
    except Exception as e:
        logger.warning("MCP fetch failed for %s: %s", label, type(e).__name__)
        return fallback


async def _fetch_calendar_events(user_id: str, user_tz: str) -> list[str]:
    """Stub — replace with real Google Calendar MCP call."""
    try:
        tz = pytz.timezone(user_tz)
        today = datetime.now(tz).date().isoformat()
        logger.info("MCP: would fetch calendar events for user %s on %s (0 fetched — MCP not connected)", user_id, today)
        return []
    except Exception as e:
        logger.warning("Calendar MCP context failed: %s", e)
        return []


async def _fetch_emails(user_id: str) -> list[str]:
    """Stub — replace with real Gmail MCP call."""
    logger.info("MCP: would fetch unread emails for user %s (0 fetched — MCP not connected)", user_id)
    return []


async def build_skill_context(
    user_id: str,
    user_input: str,
    user_timezone: str = "UTC",
    custom: dict | None = None,
    pending_tasks: list[str] | None = None,
    use_calendar: bool = False,
    use_email: bool = False,
) -> dict[str, Any]:
    tz = pytz.timezone(user_timezone)
    date_today = datetime.now(tz).date().isoformat()

    calendar_events: list[str] = []
    emails: list[str] = []

    if use_calendar:
        calendar_events = await _fetch_with_timeout(
            _fetch_calendar_events(user_id, user_timezone),
            fallback=[],
            label="calendar",
        )
        logger.info("MCP calendar: fetched %d events for user %s", len(calendar_events), user_id)

    if use_email:
        raw_emails = await _fetch_with_timeout(
            _fetch_emails(user_id),
            fallback=[],
            label="gmail",
        )
        emails = raw_emails[:15]
        logger.info("MCP gmail: fetched %d email subjects for user %s", len(emails), user_id)

    return {
        "user_input": user_input,
        "calendar_events": calendar_events,
        "emails": emails,
        "date_today": date_today,
        "pending_tasks": pending_tasks or [],
        "custom": custom or {},
    }
