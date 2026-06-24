from typing import Any

ROLE_CONFIG: dict[str, dict[str, Any]] = {
    "free": {
        "max_iterations": 2,
        "tasks_per_hour": 5,
        "allowed_tools": ["tavily", "calculator"],
    },
    "pro": {
        "max_iterations": 5,
        "tasks_per_hour": 100,
        "allowed_tools": ["tavily", "calculator", "yfinance", "python_repl"],
    },
    "admin": {
        "max_iterations": 10,
        "tasks_per_hour": None,
        "allowed_tools": ["tavily", "calculator", "yfinance", "python_repl"],
    },
}


def get_role_config(role: str) -> dict[str, Any]:
    if role not in ROLE_CONFIG:
        return ROLE_CONFIG["free"]
    return ROLE_CONFIG[role]


def can_use_tool(role: str, tool: str) -> bool:
    config = get_role_config(role)
    return tool in config["allowed_tools"]


def get_max_iterations(role: str, requested: int | None = None) -> int:
    config = get_role_config(role)
    limit = config["max_iterations"]
    if requested is None:
        return limit
    return min(requested, limit)


def get_tasks_per_hour(role: str) -> int | None:
    return get_role_config(role)["tasks_per_hour"]


def check_permission(role: str, permission: str) -> bool:
    if role == "admin":
        return True
    allowed = {
        "free": {"run_task", "view_own_tasks"},
        "pro": {"run_task", "view_own_tasks", "use_python_repl", "use_yfinance"},
    }
    return permission in allowed.get(role, set())
