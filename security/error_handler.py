import uuid
import logging
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse
import sentry_sdk

logger = logging.getLogger(__name__)


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = str(uuid.uuid4())
    task_id = getattr(request.state, "task_id", None)

    logger.error(
        "Unhandled exception | request_id=%s task_id=%s path=%s\n%s",
        request_id,
        task_id,
        request.url.path,
        traceback.format_exc(),
    )

    sentry_sdk.capture_exception(exc)

    return JSONResponse(
        status_code=500,
        content={
            "error": "Task failed",
            "task_id": task_id,
            "request_id": request_id,
        },
    )


async def http_exception_handler(request: Request, exc) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail if isinstance(exc.detail, dict) else {"error": exc.detail},
    )
