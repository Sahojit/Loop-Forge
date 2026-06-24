import uuid
import logging

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from core.hooks import HOOK_EVENTS, HOOK_ACTIONS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/hooks", tags=["hooks"])


class HookCreate(BaseModel):
    loop_id: str | None = None
    event: str
    action: str
    config: dict = {}
    is_active: bool = True


class HookUpdate(BaseModel):
    event: str | None = None
    action: str | None = None
    config: dict | None = None
    is_active: bool | None = None


@router.post("", status_code=201)
async def create_hook(body: HookCreate, request: Request):
    user_id: str = request.state.user_id

    if body.event not in HOOK_EVENTS:
        raise HTTPException(status_code=400, detail={"error": f"Invalid event. Choose from: {HOOK_EVENTS}"})
    if body.action not in HOOK_ACTIONS:
        raise HTTPException(status_code=400, detail={"error": f"Invalid action. Choose from: {HOOK_ACTIONS}"})

    from db.postgres import get_pool
    import json
    pool = await get_pool()
    hook_id = str(uuid.uuid4())

    async with pool.acquire() as conn:
        if body.loop_id:
            loop_row = await conn.fetchrow(
                "SELECT id FROM loops WHERE id = $1 AND user_id = $2", body.loop_id, user_id,
            )
            if not loop_row:
                raise HTTPException(status_code=404, detail={"error": "Loop not found"})

        await conn.execute(
            """INSERT INTO hooks (id, user_id, loop_id, event, action, config, is_active)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)""",
            hook_id, user_id, body.loop_id, body.event, body.action,
            json.dumps(body.config), body.is_active,
        )

    return {"hook_id": hook_id, "message": "Hook created"}


@router.get("")
async def list_hooks(request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, loop_id, event, action, is_active, created_at FROM hooks WHERE user_id = $1 ORDER BY created_at DESC",
            user_id,
        )
    return {"hooks": [dict(r) for r in rows]}


@router.put("/{hook_id}")
async def update_hook(hook_id: str, body: HookUpdate, request: Request):
    user_id: str = request.state.user_id
    import json
    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE hooks SET
               event=COALESCE($1, event),
               action=COALESCE($2, action),
               config=COALESCE($3::jsonb, config),
               is_active=COALESCE($4, is_active)
               WHERE id=$5 AND user_id=$6""",
            body.event, body.action,
            json.dumps(body.config) if body.config is not None else None,
            body.is_active, hook_id, user_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail={"error": "Hook not found"})
    return {"hook_id": hook_id, "message": "Hook updated"}


@router.delete("/{hook_id}", status_code=204)
async def delete_hook(hook_id: str, request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM hooks WHERE id = $1 AND user_id = $2", hook_id, user_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail={"error": "Hook not found"})


@router.post("/{hook_id}/test")
async def test_hook(hook_id: str, request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    from core.hooks import fire_hooks_for_event
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT loop_id FROM hooks WHERE id = $1 AND user_id = $2", hook_id, user_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail={"error": "Hook not found"})

    test_context = {
        "loop_name": "Test Loop",
        "status": "converged",
        "final_score": 8.5,
        "iterations": 2,
        "output_summary": "This is a test hook fire.",
        "event": "PostRun",
    }
    fired = await fire_hooks_for_event(
        user_id=user_id,
        loop_id=str(row["loop_id"] or "00000000-0000-0000-0000-000000000000"),
        loop_run_id="00000000-0000-0000-0000-000000000000",
        event="PostRun",
        context=test_context,
    )
    return {"message": "Test hook fired", "hooks_fired": fired}
