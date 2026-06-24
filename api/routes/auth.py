import uuid
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from jose import JWTError

from api.schemas import RegisterRequest, LoginRequest, RefreshRequest, TokenResponse
from auth.jwt import (
    hash_password,
    verify_password,
    hash_token,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from db.postgres import get_pool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(body: RegisterRequest):
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM users WHERE email = $1", body.email
        )
        if existing:
            raise HTTPException(status_code=409, detail={"error": "Email already registered"})

        user_id = str(uuid.uuid4())
        hashed = hash_password(body.password)
        await conn.execute(
            "INSERT INTO users (id, email, hashed_password, role) VALUES ($1, $2, $3, $4)",
            user_id, body.email, hashed, "free",
        )
    return {"message": "Registration successful", "user_id": user_id}


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, hashed_password, role FROM users WHERE email = $1", body.email
        )
        if not row or not verify_password(body.password, row["hashed_password"]):
            raise HTTPException(status_code=401, detail={"error": "Invalid credentials"})

        user_id = str(row["id"])
        role = row["role"]
        token_data = {"sub": user_id, "role": role}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        token_hash = hash_token(refresh_token)
        expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

        await conn.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES ($1, $2, $3)",
            user_id, token_hash, expires_at,
        )

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest):
    try:
        payload = decode_refresh_token(body.refresh_token)
    except JWTError:
        raise HTTPException(status_code=401, detail={"error": "Authentication required"})

    user_id = payload.get("sub")
    token_hash = hash_token(body.refresh_token)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id FROM refresh_tokens
               WHERE token_hash = $1 AND user_id = $2
               AND revoked = FALSE AND expires_at > NOW()""",
            token_hash, user_id,
        )
        if not row:
            raise HTTPException(status_code=401, detail={"error": "Authentication required"})

        await conn.execute(
            "UPDATE refresh_tokens SET revoked = TRUE WHERE token_hash = $1 AND user_id = $2",
            token_hash, user_id,
        )

        user_row = await conn.fetchrow(
            "SELECT role FROM users WHERE id = $1", user_id
        )
        role = user_row["role"] if user_row else "free"

        token_data = {"sub": user_id, "role": role}
        new_access = create_access_token(token_data)
        new_refresh = create_refresh_token(token_data)
        new_hash = hash_token(new_refresh)
        expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

        await conn.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES ($1, $2, $3)",
            user_id, new_hash, expires_at,
        )

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)
