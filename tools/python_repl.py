import io
import sys
import re
import contextlib
from typing import Any

_BLOCKED_PATTERNS = [
    r"\bimport\s+os\b",
    r"\bimport\s+subprocess\b",
    r"\bimport\s+sys\b",
    r"\b__import__\b",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bopen\s*\(",
    r"\bshutil\b",
    r"\bpickle\b",
    r"\bsocket\b",
    r"\bgetattr\s*\(",
    r"\bsetattr\s*\(",
    r"\bdelattr\s*\(",
    r"\bcompile\s*\(",
    r"__builtins__",
    r"__globals__",
    r"__class__",
]

_SAFE_GLOBALS: dict[str, Any] = {
    "__builtins__": {
        "print": print,
        "len": len,
        "range": range,
        "enumerate": enumerate,
        "zip": zip,
        "map": map,
        "filter": filter,
        "sorted": sorted,
        "sum": sum,
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "int": int,
        "float": float,
        "str": str,
        "bool": bool,
        "list": list,
        "dict": dict,
        "set": set,
        "tuple": tuple,
        "isinstance": isinstance,
        "type": type,
    }
}


def python_repl(code: str) -> str:
    if len(code) > 1000:
        return "Error: code exceeds 1000 character limit"

    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, code):
            return f"Error: blocked pattern detected"

    stdout_buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_buf):
            local_vars: dict[str, Any] = {}
            exec(code, dict(_SAFE_GLOBALS), local_vars)  # noqa: S102
        output = stdout_buf.getvalue()
        return output[:500] if output else "Executed successfully (no output)"
    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)[:200]}"
