import uuid
import logging

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from core.notifier import encrypt_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])

VALID_CHANNELS = {"telegram", "slack", "email"}


class NotifConfigCreate(BaseModel):
    channel: str
    config: dict


@router.post("/config", status_code=201)
async def save_config(body: NotifConfigCreate, request: Request):
    user_id: str = request.state.user_id

    if body.channel not in VALID_CHANNELS:
        raise HTTPException(status_code=400, detail={"error": f"channel must be one of {VALID_CHANNELS}"})

    try:
        encrypted = encrypt_config(body.config)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail={"error": "Encryption not configured"})

    from db.postgres import get_pool
    pool = await get_pool()
    config_id = str(uuid.uuid4())

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO notification_configs (id, user_id, channel, encrypted_config)
               VALUES ($1, $2, $3, $4)""",
            config_id, user_id, body.channel, encrypted,
        )

    return {"config_id": config_id, "message": f"{body.channel} notification config saved"}


@router.get("/config")
async def list_configs(request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, channel, is_active, created_at FROM notification_configs WHERE user_id = $1",
            user_id,
        )
    return {"configs": [dict(r) for r in rows]}


@router.delete("/config/{config_id}", status_code=204)
async def delete_config(config_id: str, request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM notification_configs WHERE id = $1 AND user_id = $2",
            config_id, user_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail={"error": "Config not found"})


@router.post("/test")
async def test_notification(request: Request, channel: str = "telegram"):
    user_id: str = request.state.user_id
    if channel not in VALID_CHANNELS:
        raise HTTPException(status_code=400, detail={"error": "Invalid channel"})

    from db.postgres import get_pool
    from core.notifier import send_notification
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT encrypted_config FROM notification_configs
               WHERE user_id = $1 AND channel = $2 AND is_active = TRUE
               ORDER BY created_at DESC LIMIT 1""",
            user_id, channel,
        )
    if not row:
        raise HTTPException(status_code=404, detail={"error": f"No active {channel} config found"})

    success = await send_notification(
        user_id=user_id,
        loop_run_id="test-run-id",
        loop_name="Test Loop",
        status="converged",
        final_score=9.0,
        iterations=2,
        output_summary="This is a test notification from LoopForge.",
        encrypted_config=bytes(row["encrypted_config"]),
        channel=channel,
    )
    return {"success": success, "channel": channel}


@router.get("/log")
async def notification_log(request: Request, page: int = 1, page_size: int = 20):
    user_id: str = request.state.user_id
    offset = (page - 1) * page_size

    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, loop_run_id, channel, status, attempt_count, last_error, sent_at, created_at
               FROM notification_log WHERE user_id = $1
               ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
            user_id, page_size, offset,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM notification_log WHERE user_id = $1", user_id,
        )
    return {"log": [dict(r) for r in rows], "total": total, "page": page}
