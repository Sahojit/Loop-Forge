from typing import TypedDict


class GraphState(TypedDict):
    task_id: str
    user_id: str
    input: str
    execution_output: str
    critique: dict  # {factuality, completeness, clarity, task_alignment, overall, reasoning}
    refined_output: str
    iteration: int
    max_iterations: int
    score_history: list
    tools_used: list
    tokens_used: int
    status: str  # "running" | "converged" | "max_iter_reached" | "failed"
    final_output: str
    role: str
    allowed_tools: list
    langfuse_trace_id: str
