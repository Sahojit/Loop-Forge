import uuid
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException

from api.schemas import TaskRequest, TaskResponse, TaskStatusResponse
from auth.rbac import get_role_config, get_max_iterations, get_tasks_per_hour
from security.sanitizer import sanitize_input
from security.rate_limiter import check_user_rate_limit
from db.postgres import get_pool
from workers.celery_app import run_loop_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/run-task", response_model=TaskResponse, status_code=202)
async def run_task(body: TaskRequest, request: Request):
    user_id: str = request.state.user_id
    role: str = request.state.role

    clean_input = sanitize_input(body.input)

    role_config = get_role_config(role)
    tasks_per_hour = get_tasks_per_hour(role)
    await check_user_rate_limit(user_id, tasks_per_hour)

    max_iter = get_max_iterations(role, body.max_iterations)
    if body.strategy == "fast":
        max_iter = min(max_iter, 2)
    elif body.strategy == "thorough":
        max_iter = min(max_iter, role_config["max_iterations"])

    task_id = str(uuid.uuid4())
    request.state.task_id = task_id

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO tasks (id, user_id, status, created_at)
               VALUES ($1, $2, $3, $4)""",
            task_id, user_id, "running", datetime.now(timezone.utc),
        )
        await conn.execute(
            """INSERT INTO audit_log (user_id, task_id, action, metadata, ip_hash, timestamp)
               VALUES ($1, $2, $3, $4::jsonb, $5, $6)""",
            user_id, task_id, "task_created",
            json.dumps({"strategy": body.strategy, "max_iterations": max_iter}),
            _hash_ip(request.client.host if request.client else "unknown"),
            datetime.now(timezone.utc),
        )

    run_loop_task.apply_async(
        args=[task_id, user_id, role, clean_input, max_iter],
        task_id=task_id,
        soft_time_limit=240,
        time_limit=300,
    )

    return TaskResponse(task_id=task_id, status="running")


@router.get("/task/{task_id}", response_model=TaskStatusResponse)
async def get_task(task_id: str, request: Request):
    user_id: str = request.state.user_id

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, status, final_score, iterations, tokens_used, tools_used
               FROM tasks WHERE id = $1 AND user_id = $2""",
            task_id, user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail={"error": "Task not found"})

        score_row = await conn.fetchrow(
            """SELECT metadata FROM audit_log
               WHERE task_id = $1 AND user_id = $2 AND action = 'task_completed'
               ORDER BY timestamp DESC LIMIT 1""",
            task_id, user_id,
        )

    tools = row["tools_used"].split(",") if row["tools_used"] else []
    final_output = None
    score_history: list[float] = []

    if score_row and score_row["metadata"]:
        try:
            raw = score_row["metadata"]
            meta = raw if isinstance(raw, dict) else json.loads(raw)
            final_output = meta.get("final_output")
            score_history = [float(s) for s in meta.get("score_history", [])]
        except Exception:
            pass

    return TaskStatusResponse(
        task_id=str(row["id"]),
        status=row["status"],
        final_output=final_output,
        score_history=score_history,
        iterations=row["iterations"] or 0,
        final_score=row["final_score"],
        tokens_used=row["tokens_used"] or 0,
        tools_used=[t for t in tools if t],
        convergence_status=row["status"],
    )


def _hash_ip(ip: str) -> str:
    import hashlib
    return hashlib.sha256(ip.encode()).hexdigest()[:16]
