import os
import json
import logging
import time
from typing import Any

from huggingface_hub import InferenceClient
from groq import Groq

from core.state import GraphState

logger = logging.getLogger(__name__)

HF_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct"
GROQ_MODEL = "llama-3.1-8b-instant"
DEFAULT_SCORE = 5.0

_CRITIC_SYSTEM = """You are a strict output quality evaluator. Score the following task output across 4 axes.

Score anchors:
- 1-3: Severely incomplete, factually wrong, or off-topic
- 4-6: Partially correct, missing key elements, or unclear
- 7 (meets requirements): Addresses all task requirements with only minor gaps
- 8-9: Exceeds requirements, well-structured, highly accurate
- 10: Perfect — comprehensive, factual, clear, and fully aligned

Few-shot examples:
EXAMPLE 1:
Task: "Explain quantum entanglement"
Output: "Quantum entanglement is a phenomenon where particles become correlated."
Scores: factuality=7, completeness=4, clarity=7, task_alignment=7

EXAMPLE 2:
Task: "Calculate compound interest on $1000 at 5% for 3 years"
Output: "The answer is $1157.63. Formula: A = P(1+r)^t = 1000(1.05)^3 = 1157.63"
Scores: factuality=10, completeness=9, clarity=10, task_alignment=10

You MUST return valid JSON only. No explanation outside the JSON.

JSON format:
{
  "factuality": <int 1-10>,
  "completeness": <int 1-10>,
  "clarity": <int 1-10>,
  "task_alignment": <int 1-10>,
  "reasoning": {
    "factuality": "<one sentence>",
    "completeness": "<one sentence>",
    "clarity": "<one sentence>",
    "task_alignment": "<one sentence>"
  }
}
"""


def _compute_overall(scores: dict[str, Any]) -> float:
    weights = {"factuality": 0.35, "completeness": 0.30, "clarity": 0.20, "task_alignment": 0.15}
    total = sum(scores.get(k, 5) * w for k, w in weights.items())
    return round(total, 2)


def _parse_critique(text: str) -> dict[str, Any]:
    json_match = text[text.find("{"):text.rfind("}") + 1]
    parsed = json.loads(json_match)
    for key in ("factuality", "completeness", "clarity", "task_alignment"):
        if key not in parsed:
            raise ValueError(f"Missing key: {key}")
    overall = _compute_overall(parsed)
    return {**parsed, "overall": overall}


def _call_groq(prompt: str) -> str:
    client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    chat = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=256,
    )
    return chat.choices[0].message.content or ""


def _call_hf(prompt: str) -> str:
    client = InferenceClient(token=os.getenv("HUGGINGFACE_API_KEY", ""))
    return client.text_generation(
        prompt,
        model=HF_MODEL,
        max_new_tokens=256,
        temperature=0.0,
    )


def _llm_call(prompt: str) -> str:
    try:
        return _call_groq(prompt)
    except Exception as groq_err:
        logger.warning("Groq critic call failed, falling back to HuggingFace: %s", groq_err)
        return _call_hf(prompt)


def _default_critique(reason: str) -> dict[str, Any]:
    return {
        "factuality": 5,
        "completeness": 5,
        "clarity": 5,
        "task_alignment": 5,
        "overall": DEFAULT_SCORE,
        "reasoning": {
            "factuality": reason,
            "completeness": reason,
            "clarity": reason,
            "task_alignment": reason,
        },
    }


def critic_node(state: GraphState) -> GraphState:
    from observability.langfuse_client import get_langfuse

    output = state.get("execution_output", "")
    task = state["input"]
    iteration = state.get("iteration", 0)

    prompt = (
        f"{_CRITIC_SYSTEM}\n\n"
        f"Task: {task}\n\n"
        f"Output to evaluate:\n{output}\n\n"
        f"Return JSON scores only:"
    )

    lf = get_langfuse()
    span_name = f"critic-iter-{iteration}"
    start_ms = time.time()

    critique: dict[str, Any]
    response = ""
    try:
        response = _llm_call(prompt)
        critique = _parse_critique(response)
    except Exception as first_err:
        logger.warning("First critique parse failed (%s), retrying", first_err)
        try:
            response = _llm_call(prompt)
            critique = _parse_critique(response)
        except Exception as second_err:
            logger.error("Critique failed twice: %s", second_err)
            critique = _default_critique("Critique parsing failed, using default score")

    latency_ms = int((time.time() - start_ms) * 1000)

    if lf and state.get("langfuse_trace_id"):
        try:
            trace = lf.trace(id=state["langfuse_trace_id"])
            trace.span(
                name=span_name,
                metadata={
                    "iteration": iteration,
                    "node": "critic",
                    "score": critique.get("overall"),
                    "latency_ms": latency_ms,
                    "output_length": len(output),
                },
            )
        except Exception as lf_err:
            logger.debug("LangFuse span error: %s", lf_err)

    score_history = list(state.get("score_history", []))
    score_history.append(critique["overall"])

    return {
        **state,
        "critique": critique,
        "score_history": score_history,
        "iteration": iteration + 1,
    }
