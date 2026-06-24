import os
import asyncio
import logging
from datetime import datetime, timezone

import sentry_sdk
from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded

logger = logging.getLogger(__name__)

celery_app = Celery(
    "loopforge",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)

celery_app.conf.imports = (
    "workers.celery_app",
    "workers.loop_runner",
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=240,
    task_time_limit=300,
)


@celery_app.task(
    name="loopforge.run_loop_task",
    max_retries=0,
)
def run_loop_task(
    task_id: str,
    user_id: str,
    role: str,
    input_text: str,
    max_iterations: int,
) -> dict:
    from core.graph import create_runnable
    from core.state import GraphState
    from auth.rbac import get_role_config
    from observability.langfuse_client import create_task_trace, log_final_span
    from db.postgres import get_pool

    async def _run() -> dict:
        role_config = get_role_config(role)
        trace_id = create_task_trace(
            task_id=task_id,
            user_id=user_id,
            role=role,
            input_length=len(input_text),
            max_iterations=max_iterations,
        )

        from core.cache import get_cached_result, set_cached_result
        cached = await get_cached_result(user_id, input_text)
        if cached:
            logger.info("Cache hit for task %s — skipping loop", task_id)
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """UPDATE tasks SET status='converged', final_score=$1,
                       iterations=0, tokens_used=0, completed_at=NOW()
                       WHERE id=$2 AND user_id=$3""",
                    cached.get("final_score"), task_id, user_id,
                )
            return {"task_id": task_id, "status": "converged", **cached}

        initial_state: GraphState = {
            "task_id": task_id,
            "user_id": user_id,
            "input": input_text,
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
            "langfuse_trace_id": trace_id or "",
        }

        try:
            runnable = create_runnable(max_iterations)
            final_state = runnable.invoke(initial_state)
        except Exception as e:
            logger.error("Graph execution failed for task %s: %s", task_id, e)
            sentry_sdk.capture_exception(e)
            final_state = {**initial_state, "status": "failed", "final_output": ""}

        score_history = final_state.get("score_history", [])
        final_score = score_history[-1] if score_history else None
        converged = final_state.get("status") == "converged"

        if converged and final_score:
            await set_cached_result(user_id, input_text, {
                "final_score": final_score,
                "final_output": final_state.get("final_output", ""),
            })

        if trace_id:
            log_final_span(
                trace_id=trace_id,
                converged=converged,
                total_iterations=final_state.get("iteration", 0),
                final_score=final_score or 0.0,
                total_tokens=final_state.get("tokens_used", 0),
            )

        import json as _json
        audit_meta = _json.dumps({
            "final_output": final_state.get("final_output", ""),
            "score_history": score_history,
            "final_score": final_score,
            "iterations": final_state.get("iteration", 0),
            "tools_used": list(set(final_state.get("tools_used", []))),
        })

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE tasks SET status=$1, final_score=$2, iterations=$3,
                   tokens_used=$4, tools_used=$5, completed_at=$6
                   WHERE id=$7 AND user_id=$8""",
                final_state.get("status", "failed"),
                final_score,
                final_state.get("iteration", 0),
                final_state.get("tokens_used", 0),
                ",".join(set(final_state.get("tools_used", []))),
                datetime.now(timezone.utc),
                task_id,
                user_id,
            )
            await conn.execute(
                """INSERT INTO audit_log (user_id, task_id, action, metadata, ip_hash, timestamp)
                   VALUES ($1, $2, $3, $4::jsonb, $5, $6)""",
                user_id, task_id, "task_completed",
                audit_meta, "system", datetime.now(timezone.utc),
            )

        return {
            "task_id": task_id,
            "status": final_state.get("status"),
            "final_score": final_score,
        }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()
    except SoftTimeLimitExceeded:
        logger.error("Task %s hit soft time limit", task_id)
        sentry_sdk.capture_message(f"Task {task_id} hit soft time limit")
        _mark_failed_sync(task_id, user_id)
        raise
    except Exception as exc:
        logger.error("Task %s failed: %s", task_id, exc)
        sentry_sdk.capture_exception(exc)
        _mark_failed_sync(task_id, user_id)
        raise


def _mark_failed_sync(task_id: str, user_id: str) -> None:
    async def _update():
        from db.postgres import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE tasks SET status='failed', completed_at=$1 WHERE id=$2 AND user_id=$3",
                datetime.now(timezone.utc), task_id, user_id,
            )
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_update())
    finally:
        loop.close()
