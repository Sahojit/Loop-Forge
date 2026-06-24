import os
import logging

from huggingface_hub import InferenceClient
from groq import Groq

from core.state import GraphState

logger = logging.getLogger(__name__)

HF_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct"
GROQ_MODEL = "llama-3.1-8b-instant"

_REFINER_SYSTEM = """You are a precise output refiner. You will receive:
1. The original task
2. The current output
3. A structured critique with specific reasoning per dimension

Your job is to produce an improved version of the output that DIRECTLY addresses the critique.
Do not restate the critique. Just produce the improved output.
"""


def _build_prompt(task: str, output: str, critique: dict) -> str:
    reasoning = critique.get("reasoning", {})
    critique_text = "\n".join(
        f"- {dim.capitalize()} (score {critique.get(dim, '?')}/10): {reasoning.get(dim, 'No detail')}"
        for dim in ("factuality", "completeness", "clarity", "task_alignment")
    )
    return (
        f"{_REFINER_SYSTEM}\n\n"
        f"Task: {task}\n\n"
        f"Current Output:\n{output}\n\n"
        f"Critique:\n{critique_text}\n\n"
        f"Overall score: {critique.get('overall', '?')}/10\n\n"
        f"Improved Output:"
    )


def _call_groq(prompt: str) -> tuple[str, int]:
    client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    chat = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=512,
    )
    text = chat.choices[0].message.content or ""
    usage = chat.usage
    tokens = (usage.prompt_tokens + usage.completion_tokens) if usage else len(text.split())
    return text, tokens


def _call_hf(prompt: str) -> tuple[str, int]:
    client = InferenceClient(token=os.getenv("HUGGINGFACE_API_KEY", ""))
    response = client.text_generation(
        prompt,
        model=HF_MODEL,
        max_new_tokens=512,
        temperature=0.5,
    )
    tokens = len(prompt.split()) + len(response.split())
    return response, tokens


def _llm_call(prompt: str) -> tuple[str, int]:
    try:
        return _call_groq(prompt)
    except Exception as groq_err:
        logger.warning("Groq refiner call failed, falling back to HuggingFace: %s", groq_err)
        return _call_hf(prompt)


def refiner_node(state: GraphState) -> GraphState:
    task = state["input"]
    output = state.get("execution_output", "")
    critique = state.get("critique", {})
    tokens_used = state.get("tokens_used", 0)

    prompt = _build_prompt(task, output, critique)
    tokens_before = tokens_used

    refined, step_tokens = _llm_call(prompt)
    tokens_used += step_tokens
    token_delta = tokens_used - tokens_before

    logger.debug("Refiner token delta: %d", token_delta)

    return {
        **state,
        "refined_output": refined.strip(),
        "execution_output": refined.strip(),
        "tokens_used": tokens_used,
    }
