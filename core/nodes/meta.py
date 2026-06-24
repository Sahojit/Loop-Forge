import os
import logging
from core.state import GraphState

logger = logging.getLogger(__name__)

CONVERGENCE_THRESHOLD = float(os.getenv("CONVERGENCE_THRESHOLD", "7.5"))


def _classify_task(task_input: str) -> str:
    task_lower = task_input.lower()
    if any(w in task_lower for w in ("calculate", "compute", "math", "formula")):
        return "calculation"
    if any(w in task_lower for w in ("search", "find", "look up", "research")):
        return "research"
    if any(w in task_lower for w in ("code", "python", "function", "script")):
        return "coding"
    if any(w in task_lower for w in ("stock", "market", "price", "ticker")):
        return "market_data"
    return "general"


def _determine_status(state: GraphState) -> str:
    score_history = state.get("score_history", [])
    final_score = score_history[-1] if score_history else 0.0
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 5)

    if final_score >= CONVERGENCE_THRESHOLD:
        return "converged"
    if iteration >= max_iterations:
        return "max_iter_reached"
    return state.get("status", "max_iter_reached")


def meta_node(state: GraphState) -> GraphState:
    user_id = state["user_id"]
    task_id = state["task_id"]
    task_input = state["input"]
    score_history = state.get("score_history", [])
    tools_used = state.get("tools_used", [])
    final_score = score_history[-1] if score_history else 0.0
    iterations = state.get("iteration", 1)
    final_output = state.get("refined_output") or state.get("execution_output", "")
    status = _determine_status(state)

    avg_score_delta = 0.0
    if len(score_history) > 1:
        deltas = [score_history[i] - score_history[i - 1] for i in range(1, len(score_history))]
        avg_score_delta = round(sum(deltas) / len(deltas), 3)

    task_type = _classify_task(task_input)

    try:
        from memory.chroma import get_chroma_client
        chroma = get_chroma_client()
        collection = chroma.get_or_create_collection("task_strategies")
        collection.upsert(
            documents=[f"{task_type}: {task_input[:200]}"],
            metadatas=[{
                "user_id": user_id,
                "task_id": task_id,
                "task_type": task_type,
                "iterations_to_converge": str(iterations),
                "final_score": str(final_score),
                "tools_used": ",".join(set(tools_used)),
                "avg_score_delta": str(avg_score_delta),
            }],
            ids=[task_id],
        )
    except Exception as e:
        logger.warning("ChromaDB write failed: %s", e)

    return {
        **state,
        "final_output": final_output,
        "status": status,
    }
