import os
from core.state import GraphState

CONVERGENCE_THRESHOLD = float(os.getenv("CONVERGENCE_THRESHOLD", "7.5"))
CIRCUIT_BREAK_WINDOW = 2
CIRCUIT_BREAK_DECLINE = 0.2


def route_after_critic(state: GraphState) -> str:
    iteration = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", 5)
    score_history = state.get("score_history", [])
    current_score = score_history[-1] if score_history else 0.0

    if current_score >= CONVERGENCE_THRESHOLD:
        return "meta"

    if iteration >= max_iterations:
        state["status"] = "max_iter_reached"
        return "meta"

    if len(score_history) >= CIRCUIT_BREAK_WINDOW + 1:
        recent = score_history[-(CIRCUIT_BREAK_WINDOW + 1):]
        all_declining = all(
            recent[i] <= recent[i - 1] - CIRCUIT_BREAK_DECLINE
            for i in range(1, len(recent))
        )
        if all_declining:
            state["status"] = "max_iter_reached"
            return "meta"

    return "refiner"
