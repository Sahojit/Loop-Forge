import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from security.sanitizer import sanitize_input

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/loops", tags=["loops"])

LOOP_QUOTA_FREE = int(__import__("os").getenv("LOOP_QUOTA_FREE", "2"))


class LoopCreate(BaseModel):
    name: str
    description: str = ""
    skill_id: str | None = None
    cron_expression: str
    timezone: str = "UTC"
    max_iterations: int = 3


class LoopUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    skill_id: str | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    max_iterations: int | None = None


def _validate_cron(expr: str) -> None:
    import re
    if len(expr.strip().split()) != 5:
        raise HTTPException(status_code=400, detail={"error": "cron_expression must have 5 fields"})


@router.post("", status_code=201)
async def create_loop(body: LoopCreate, request: Request):
    user_id: str = request.state.user_id
    role: str = request.state.role

    sanitize_input(body.name)
    _validate_cron(body.cron_expression)

    from db.postgres import get_pool
    pool = await get_pool()

    if role == "free":
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM loops WHERE user_id = $1", user_id,
            )
        if count >= LOOP_QUOTA_FREE:
            raise HTTPException(
                status_code=403,
                detail={"error": f"Free tier limited to {LOOP_QUOTA_FREE} loops. Upgrade to pro."},
            )

    loop_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO loops (id, user_id, skill_id, name, description, cron_expression, timezone, max_iterations)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            loop_id, user_id, body.skill_id, body.name, body.description,
            body.cron_expression, body.timezone, body.max_iterations,
        )

    return {"loop_id": loop_id, "message": "Loop created. Activate to start scheduling."}


@router.get("")
async def list_loops(request: Request, page: int = 1, page_size: int = 20):
    user_id: str = request.state.user_id
    offset = (page - 1) * page_size

    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, name, description, cron_expression, timezone, is_active,
                      max_iterations, last_run_at, next_run_at, created_at
               FROM loops WHERE user_id = $1
               ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
            user_id, page_size, offset,
        )
        total = await conn.fetchval("SELECT COUNT(*) FROM loops WHERE user_id = $1", user_id)

    return {"loops": [dict(r) for r in rows], "total": total, "page": page}


@router.get("/{loop_id}")
async def get_loop(loop_id: str, request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM loops WHERE id = $1 AND user_id = $2", loop_id, user_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail={"error": "Loop not found"})
    return dict(row)


@router.put("/{loop_id}")
async def update_loop(loop_id: str, body: LoopUpdate, request: Request):
    user_id: str = request.state.user_id
    if body.cron_expression:
        _validate_cron(body.cron_expression)

    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM loops WHERE id = $1 AND user_id = $2", loop_id, user_id,
        )
        if not existing:
            raise HTTPException(status_code=404, detail={"error": "Loop not found"})

        await conn.execute(
            """UPDATE loops SET
               name=COALESCE($1, name),
               description=COALESCE($2, description),
               skill_id=COALESCE($3, skill_id),
               cron_expression=COALESCE($4, cron_expression),
               timezone=COALESCE($5, timezone),
               max_iterations=COALESCE($6, max_iterations),
               updated_at=NOW()
               WHERE id=$7 AND user_id=$8""",
            body.name, body.description, body.skill_id,
            body.cron_expression, body.timezone, body.max_iterations,
            loop_id, user_id,
        )
        updated = await conn.fetchrow(
            "SELECT cron_expression, timezone, is_active FROM loops WHERE id = $1", loop_id,
        )

    if updated["is_active"] and body.cron_expression:
        from workers.scheduler import update_loop as sched_update
        sched_update(loop_id, user_id, updated["cron_expression"], updated["timezone"])

    return {"loop_id": loop_id, "message": "Loop updated"}


@router.delete("/{loop_id}", status_code=204)
async def delete_loop(loop_id: str, request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    from workers.scheduler import remove_loop
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM loops WHERE id = $1 AND user_id = $2", loop_id, user_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail={"error": "Loop not found"})
    remove_loop(loop_id)


@router.patch("/{loop_id}/activate")
async def activate_loop(loop_id: str, request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    from workers.scheduler import register_loop, next_run_at
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT cron_expression, timezone FROM loops WHERE id = $1 AND user_id = $2",
            loop_id, user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail={"error": "Loop not found"})
        register_loop(loop_id, user_id, row["cron_expression"], row["timezone"])
        nxt = next_run_at(loop_id)
        await conn.execute(
            "UPDATE loops SET is_active=TRUE, next_run_at=$1, updated_at=NOW() WHERE id=$2 AND user_id=$3",
            nxt, loop_id, user_id,
        )
    return {"loop_id": loop_id, "message": "Loop activated"}


@router.patch("/{loop_id}/deactivate")
async def deactivate_loop(loop_id: str, request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    from workers.scheduler import remove_loop
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE loops SET is_active=FALSE, next_run_at=NULL, updated_at=NOW() WHERE id=$1 AND user_id=$2",
            loop_id, user_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail={"error": "Loop not found"})
    remove_loop(loop_id)
    return {"loop_id": loop_id, "message": "Loop deactivated"}


@router.post("/{loop_id}/trigger")
async def manual_trigger(loop_id: str, request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM loops WHERE id = $1 AND user_id = $2", loop_id, user_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail={"error": "Loop not found"})

    from workers.loop_runner import run_scheduled_loop
    run_scheduled_loop.apply_async(
        kwargs={"loop_id": loop_id, "user_id": user_id, "triggered_by": "manual"},
        soft_time_limit=240,
        time_limit=300,
    )
    return {"loop_id": loop_id, "message": "Manual trigger fired"}


@router.get("/{loop_id}/history")
async def loop_history(loop_id: str, request: Request, page: int = 1, page_size: int = 20):
    user_id: str = request.state.user_id
    offset = (page - 1) * page_size

    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM loops WHERE id = $1 AND user_id = $2", loop_id, user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail={"error": "Loop not found"})

        runs = await conn.fetch(
            """SELECT id, status, final_score, iterations, tokens_used, tools_used,
                      score_history, triggered_by, hooks_fired, started_at, completed_at
               FROM loop_runs WHERE loop_id = $1 AND user_id = $2
               ORDER BY started_at DESC LIMIT $3 OFFSET $4""",
            loop_id, user_id, page_size, offset,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM loop_runs WHERE loop_id = $1 AND user_id = $2",
            loop_id, user_id,
        )

    return {"runs": [dict(r) for r in runs], "total": total, "page": page}
