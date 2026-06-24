import os
import logging
from datetime import datetime, timezone

import pytz
from celery.schedules import crontab
from redbeat import RedBeatSchedulerEntry

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)

TASK_KEY_PREFIX = "loopforge:loop"
MISFIRE_GRACE = 300  # 5 minutes in seconds


def _loop_key(loop_id: str) -> str:
    return f"{TASK_KEY_PREFIX}:{loop_id}"


def _parse_cron(cron_expression: str, user_timezone: str) -> crontab:
    parts = cron_expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {cron_expression!r} — must have 5 fields")
    minute, hour, day_of_month, month_of_year, day_of_week = parts
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


def register_loop(loop_id: str, user_id: str, cron_expression: str, user_timezone: str = "UTC") -> None:
    schedule = _parse_cron(cron_expression, user_timezone)
    entry = RedBeatSchedulerEntry(
        name=_loop_key(loop_id),
        task="loopforge.run_scheduled_loop",
        schedule=schedule,
        kwargs={"loop_id": loop_id, "user_id": user_id},
        options={"expires": MISFIRE_GRACE},
        app=celery_app,
    )
    entry.save()
    logger.info("Registered loop %s in RedBeat with cron '%s'", loop_id, cron_expression)


def update_loop(loop_id: str, user_id: str, cron_expression: str, user_timezone: str = "UTC") -> None:
    try:
        entry = RedBeatSchedulerEntry.from_key(_loop_key(loop_id), app=celery_app)
        entry.schedule = _parse_cron(cron_expression, user_timezone)
        entry.kwargs = {"loop_id": loop_id, "user_id": user_id}
        entry.save()
        logger.info("Updated loop %s RedBeat schedule to '%s'", loop_id, cron_expression)
    except Exception as e:
        logger.warning("Loop %s not found in RedBeat, re-registering: %s", loop_id, e)
        register_loop(loop_id, user_id, cron_expression, user_timezone)


def remove_loop(loop_id: str) -> None:
    try:
        entry = RedBeatSchedulerEntry.from_key(_loop_key(loop_id), app=celery_app)
        entry.delete()
        logger.info("Removed loop %s from RedBeat", loop_id)
    except Exception as e:
        logger.warning("Loop %s not found in RedBeat during removal: %s", loop_id, e)


def next_run_at(loop_id: str) -> datetime | None:
    try:
        entry = RedBeatSchedulerEntry.from_key(_loop_key(loop_id), app=celery_app)
        return entry.due_at
    except Exception:
        return None
