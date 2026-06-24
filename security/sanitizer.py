import re
from fastapi import HTTPException

MAX_INPUT_LENGTH = 2000

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+previous", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"reveal\s+instructions", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"forget\s+your", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"override\s+(your\s+)?instructions", re.IGNORECASE),
]

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


def sanitize_input(text: str) -> str:
    if len(text) > MAX_INPUT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail={"error": "Input validation failed", "code": "INPUT_TOO_LONG"},
        )

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            raise HTTPException(
                status_code=400,
                detail={"error": "Input validation failed", "code": "INVALID_INPUT"},
            )

    return strip_html(text).strip()
