import os
import re
import logging
from typing import Any

from huggingface_hub import InferenceClient
from groq import Groq

from core.state import GraphState
from tools.search import tavily_search
from tools.calculator import calculate
from tools.python_repl import python_repl
from tools.yfinance_tool import get_market_data

logger = logging.getLogger(__name__)

TOKEN_BUDGET = int(os.getenv("TOKEN_BUDGET_PER_TASK", "8000"))
HF_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct"
GROQ_MODEL = "llama-3.1-8b-instant"


class BudgetExceededError(Exception):
    pass


_TOOL_REGISTRY = {
    "tavily": tavily_search,
    "calculator": calculate,
    "python_repl": python_repl,
    "yfinance": get_market_data,
}

_TOOL_DESCRIPTIONS = {
    "tavily": "Search the web. Input: search query string.",
    "calculator": "Evaluate a math expression. Input: expression string.",
    "python_repl": "Run sandboxed Python code. Input: Python code string.",
    "yfinance": "Get stock market data. Input: ticker symbol (e.g. AAPL).",
}

_REACT_SYSTEM = """You are a precise reasoning agent using the ReAct pattern.
For each step, output EXACTLY one of:

Thought: <your reasoning>
Action: <tool_name>
Input: <tool input>

OR when done:

Thought: <final reasoning>
Final Answer: <your answer>

Available tools: {tools}

Rules:
- Use only the listed tools
- Each Action must be immediately followed by Input
- After receiving an Observation, continue reasoning
- Stop when you have enough information for a Final Answer
"""


def _build_prompt(task: str, tools: list[str], history: str) -> str:
    tool_desc = "\n".join(
        f"- {t}: {_TOOL_DESCRIPTIONS[t]}" for t in tools if t in _TOOL_DESCRIPTIONS
    )
    system = _REACT_SYSTEM.format(tools=tool_desc)
    return f"{system}\n\nTask: {task}\n\n{history}"


def _call_groq(prompt: str) -> tuple[str, int]:
    client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    chat = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
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
        temperature=0.7,
    )
    estimated_tokens = len(prompt.split()) + len(response.split())
    return response, estimated_tokens


def _llm_call(prompt: str) -> tuple[str, int]:
    try:
        return _call_groq(prompt)
    except Exception as groq_err:
        logger.warning("Groq call failed, falling back to HuggingFace: %s", groq_err)
        return _call_hf(prompt)


def _parse_action(text: str) -> tuple[str | None, str | None]:
    action_match = re.search(r"Action:\s*(\w+)", text)
    input_match = re.search(r"Input:\s*(.+?)(?=\n(?:Thought|Action|Final Answer)|$)", text, re.DOTALL)
    action = action_match.group(1).strip() if action_match else None
    inp = input_match.group(1).strip() if input_match else None
    return action, inp


def _sanitize_observation(text: str) -> str:
    clean = re.sub(r"<[^>]+>", "", text)
    return clean[:500]


def executor_node(state: GraphState) -> GraphState:
    task_input = state["refined_output"] if state.get("refined_output") else state["input"]
    allowed_tools = state.get("allowed_tools", ["tavily", "calculator"])
    tokens_used = state.get("tokens_used", 0)
    tools_used = list(state.get("tools_used", []))

    history = ""
    max_steps = 4

    for step in range(max_steps):
        prompt = _build_prompt(task_input, allowed_tools, history)
        response, step_tokens = _llm_call(prompt)
        tokens_used += step_tokens

        if tokens_used > TOKEN_BUDGET:
            raise BudgetExceededError(
                f"Token budget of {TOKEN_BUDGET} exceeded at step {step}"
            )

        history += response + "\n"

        if "Final Answer:" in response:
            final = re.search(r"Final Answer:\s*(.+)", response, re.DOTALL)
            output = final.group(1).strip() if final else response
            return {
                **state,
                "execution_output": output,
                "tokens_used": tokens_used,
                "tools_used": tools_used,
                "status": "running",
            }

        action, inp = _parse_action(response)
        if action and inp:
            tool_fn = _TOOL_REGISTRY.get(action)
            if tool_fn and action in allowed_tools:
                tools_used.append(action)
                raw_obs = tool_fn(inp)
                observation = _sanitize_observation(str(raw_obs))
            else:
                observation = f"Tool '{action}' is not available."
            history += f"Observation: {observation}\n"
        else:
            break

    return {
        **state,
        "execution_output": history.strip(),
        "tokens_used": tokens_used,
        "tools_used": tools_used,
        "status": "running",
    }
