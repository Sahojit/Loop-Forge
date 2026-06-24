import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

_langfuse = None


def get_langfuse():
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        return _langfuse
    except Exception as e:
        logger.warning("LangFuse init failed: %s", e)
        return None


def create_task_trace(
    task_id: str,
    user_id: str,
    role: str,
    input_length: int,
    max_iterations: int,
) -> str | None:
    lf = get_langfuse()
    if lf is None:
        return None
    try:
        trace = lf.trace(
            name="loopforge-task",
            id=task_id,
            metadata={
                "user_id": user_id,
                "role": role,
                "input_length": input_length,
                "max_iterations": max_iterations,
            },
        )
        return trace.id
    except Exception as e:
        logger.warning("LangFuse trace creation failed: %s", e)
        return None


def log_final_span(
    trace_id: str,
    converged: bool,
    total_iterations: int,
    final_score: float,
    total_tokens: int,
) -> None:
    lf = get_langfuse()
    if lf is None or not trace_id:
        return
    try:
        trace = lf.trace(id=trace_id)
        trace.span(
            name="final-summary",
            metadata={
                "converged": converged,
                "total_iterations": total_iterations,
                "final_score": final_score,
                "total_tokens": total_tokens,
            },
        )
        lf.flush()
    except Exception as e:
        logger.warning("LangFuse final span failed: %s", e)
