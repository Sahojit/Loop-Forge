import re
import logging
from datetime import date

from jinja2.sandbox import SandboxedEnvironment
from jinja2 import TemplateError

logger = logging.getLogger(__name__)

MAX_TEMPLATE_LENGTH = 4000

_INJECTION_PATTERNS = [
    "__class__", "__mro__", "__subclasses__",
    "import", "exec(", "eval(", "os.", "sys.",
]

_DUMMY_CONTEXT = {
    "user_input": "sample task input",
    "calendar_events": ["09:00 - Team standup", "14:00 - Product review"],
    "emails": ["Re: Q3 report", "Action required: invoice"],
    "date_today": date.today().isoformat(),
    "pending_tasks": ["Previous output placeholder"],
    "custom": {},
}

_ENV = SandboxedEnvironment(autoescape=False)


def _check_injection(template: str) -> str | None:
    for pattern in _INJECTION_PATTERNS:
        if pattern in template:
            return pattern
    return None


def validate_template(template: str) -> tuple[bool, str]:
    if len(template) > MAX_TEMPLATE_LENGTH:
        return False, f"Template exceeds {MAX_TEMPLATE_LENGTH} character limit"

    blocked = _check_injection(template)
    if blocked:
        return False, f"Template contains blocked pattern: '{blocked}'"

    try:
        tmpl = _ENV.from_string(template)
        tmpl.render(**_DUMMY_CONTEXT)
        return True, ""
    except TemplateError as e:
        return False, f"Template syntax error: {str(e)}"
    except Exception as e:
        return False, f"Template render error: {str(e)}"


def render_template(template: str, context: dict) -> str:
    safe_context = {
        "user_input": context.get("user_input", ""),
        "calendar_events": context.get("calendar_events", []),
        "emails": context.get("emails", []),
        "date_today": context.get("date_today", date.today().isoformat()),
        "pending_tasks": context.get("pending_tasks", []),
        "custom": context.get("custom", {}),
    }
    tmpl = _ENV.from_string(template)
    return tmpl.render(**safe_context)


def test_render(template: str) -> tuple[bool, str]:
    valid, err = validate_template(template)
    if not valid:
        return False, err
    try:
        tmpl = _ENV.from_string(template)
        rendered = tmpl.render(**_DUMMY_CONTEXT)
        return True, rendered
    except Exception as e:
        return False, str(e)
