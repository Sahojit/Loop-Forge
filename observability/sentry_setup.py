import os
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.celery import CeleryIntegration


def init_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("ENVIRONMENT", "development"),
        integrations=[FastApiIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
        before_send=_scrub_event,
    )


def _scrub_event(event: dict, hint: dict) -> dict:
    if "request" in event:
        event["request"].pop("data", None)
        event["request"].pop("query_string", None)
    return event
