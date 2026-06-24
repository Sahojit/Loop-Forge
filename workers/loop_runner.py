import os
import json
import asyncio
import logging
from datetime import datetime, timezone

import sentry_sdk

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)

LOCK_TTL = 300
CONCURRENCY_FREE = int(os.getenv("LOOP_CONCURRENCY_FREE", "1"))
CONCURRENCY_PRO = int(os.getenv("LOOP_CONCURRENCY_PRO", "5"))


def _concurrency_limit(role: str) -> int:
    if role == "admin":
        return 999
    if role == "pro":
        return CONCURRENCY_PRO
    return CONCURRENCY_FREE


@celery_app.task(
    name="loopforge.run_scheduled_loop",
    max_retries=0,
)
def run_scheduled_loop(loop_id: str, user_id: str, triggered_by: str = "schedule") -> dict:
    async def _run() -> dict:
        from db.postgres import get_pool
        from db.redis_client import get_redis
        from core.skills import render_template
        from core.mcp_context import build_skill_context
        from core.graph import create_runnable
        from core.state import GraphState
        from core.hooks import fire_hooks_for_event, publish_event
        from auth.rbac import get_role_config
        from workers.scheduler import next_run_at

        redis = await get_redis()
        pool = await get_pool()

        async with pool.acquire() as conn:
            loop_row = await conn.fetchrow(
                """SELECT l.*, u.role, s.prompt_template, s.name AS skill_name
                   FROM loops l
                   JOIN users u ON u.id = l.user_id
                   LEFT JOIN skills s ON s.id = l.skill_id
                   WHERE l.id = $1 AND l.user_id = $2 AND l.is_active = TRUE""",
                loop_id, user_id,
            )
        if not loop_row:
            logger.info("Loop %s not found or inactive — skipping", loop_id)
            return {"skipped": True, "reason": "loop_not_found_or_inactive"}

        role = loop_row["role"]
        role_config = get_role_config(role)

        conc_key = f"loop_conc:{user_id}"
        conc_limit = _concurrency_limit(role)
        current_conc = int(await redis.get(conc_key) or 0)
        if current_conc >= conc_limit:
            logger.warning("User %s at concurrency limit (%d) — skipping loop %s", user_id, conc_limit, loop_id)
            return {"skipped": True, "reason": "concurrency_limit"}

        lock_key = f"lock:loop:{loop_id}"
        acquired = await redis.set(lock_key, "1", ex=LOCK_TTL, nx=True)
        if not acquired:
            logger.info("Loop %s already running — skipping duplicate fire", loop_id)
            return {"skipped": True, "reason": "lock_not_acquired"}

        fired_ts = datetime.now(timezone.utc).isoformat()
        idempotency_key = f"{loop_id}:{fired_ts}"
        loop_run_id: str | None = None

        try:
            await redis.incr(conc_key)
            await redis.expire(conc_key, LOCK_TTL)

            async with pool.acquire() as conn:
                result = await conn.fetchrow(
                    """INSERT INTO loop_runs
                       (user_id, loop_id, idempotency_key, status, triggered_by)
                       VALUES ($1, $2, $3, 'running', $4)
                       ON CONFLICT (idempotency_key) DO NOTHING
                       RETURNING id""",
                    user_id, loop_id, idempotency_key, triggered_by,
                )
            if not result:
                logger.info("Duplicate idempotency key %s — skipping", idempotency_key)
                return {"skipped": True, "reason": "duplicate_idempotency_key"}

            loop_run_id = str(result["id"])

            template = loop_row["prompt_template"] or "{{ user_input }}"
            skill_name = loop_row["skill_name"] or loop_row["name"]
            context = await build_skill_context(
                user_id=user_id,
                user_input=loop_row.get("description") or "",
                user_timezone=loop_row["timezone"] or "UTC",
            )
            rendered_input = render_template(template, context)

            max_iterations = min(loop_row["max_iterations"], role_config["max_iterations"])
            initial_state: GraphState = {
                "task_id": loop_run_id,
                "user_id": user_id,
                "input": rendered_input,
                "execution_output": "",
                "critique": {},
                "refined_output": "",
                "iteration": 0,
                "max_iterations": max_iterations,
                "score_history": [],
                "tools_used": [],
                "tokens_used": 0,
                "status": "running",
                "final_output": "",
                "role": role,
                "allowed_tools": role_config["allowed_tools"],
                "langfuse_trace_id": "",
            }

            runnable = create_runnable(max_iterations)
            final_state = runnable.invoke(initial_state)

            score_history = final_state.get("score_history", [])
            final_score = score_history[-1] if score_history else None
            status = final_state.get("status", "failed")
            final_output = final_state.get("final_output", "")
            tools_used = list(set(final_state.get("tools_used", [])))

            async with pool.acquire() as conn:
                await conn.execute(
                    """UPDATE loop_runs SET status=$1, final_score=$2, iterations=$3,
                       tokens_used=$4, tools_used=$5, final_output=$6,
                       score_history=$7, completed_at=NOW()
                       WHERE id=$8 AND user_id=$9""",
                    status, final_score, final_state.get("iteration", 0),
                    final_state.get("tokens_used", 0), tools_used,
                    final_output, score_history, loop_run_id, user_id,
                )
                nxt = next_run_at(loop_id)
                await conn.execute(
                    "UPDATE loops SET last_run_at=NOW(), next_run_at=$1, updated_at=NOW() WHERE id=$2 AND user_id=$3",
                    nxt, loop_id, user_id,
                )

            hook_event = "OnConverge" if status == "converged" else ("OnMaxIter" if status == "max_iter_reached" else "OnFailure")
            hook_context = {
                "loop_name": skill_name,
                "status": status,
                "final_score": final_score,
                "iterations": final_state.get("iteration", 0),
                "output_summary": final_output[:200] if final_output else "",
                "event": hook_event,
            }
            hooks_fired = await fire_hooks_for_event(user_id, loop_id, loop_run_id, "PostRun", hook_context)
            hooks_fired += await fire_hooks_for_event(user_id, loop_id, loop_run_id, hook_event, hook_context)

            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE loop_runs SET hooks_fired=$1 WHERE id=$2 AND user_id=$3",
                    hooks_fired, loop_run_id, user_id,
                )

            return {"loop_run_id": loop_run_id, "status": status, "final_score": final_score}

        except Exception as exc:
            logger.error("Loop run %s failed: %s", loop_run_id, exc)
            sentry_sdk.capture_exception(exc)
            if loop_run_id:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE loop_runs SET status='failed', completed_at=NOW() WHERE id=$1 AND user_id=$2",
                        loop_run_id, user_id,
                    )
                await fire_hooks_for_event(user_id, loop_id, loop_run_id, "OnFailure", {
                    "loop_name": loop_id, "status": "failed", "event": "OnFailure",
                    "final_score": None, "iterations": 0, "output_summary": "",
                })
            raise
        finally:
            await redis.delete(lock_key)
            conc_val = int(await redis.get(conc_key) or 1)
            if conc_val > 1:
                await redis.decr(conc_key)
            else:
                await redis.delete(conc_key)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()
