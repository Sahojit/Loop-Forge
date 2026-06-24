import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from auth.middleware import AuthMiddleware
from security.error_handler import global_exception_handler, http_exception_handler
from security.rate_limiter import limiter
from observability.sentry_setup import init_sentry
from api.routes import tasks, auth, health, skills, loops, hooks, notifications


@asynccontextmanager
async def lifespan(app: FastAPI):
    from db.postgres import init_db, close_pool
    from db.redis_client import close_redis

    init_sentry()
    await init_db()
    from db.models import LOOP_STUDIO_TABLES_SQL
    pool = await __import__("db.postgres", fromlist=["get_pool"]).get_pool()
    async with pool.acquire() as _conn:
        await _conn.execute(LOOP_STUDIO_TABLES_SQL)
    yield
    await close_pool()
    await close_redis()


app = FastAPI(
    title="LoopForge",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

app.state.limiter = limiter

allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:8501").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.add_middleware(AuthMiddleware)

app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(skills.router)
app.include_router(loops.router)
app.include_router(hooks.router)
app.include_router(notifications.router)
