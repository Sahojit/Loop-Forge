from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from jose import JWTError

from auth.jwt import decode_access_token

_PUBLIC_PATHS = {"/health", "/auth/register", "/auth/login", "/auth/refresh", "/docs", "/openapi.json"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"error": "Authentication required"})

        token = auth_header.removeprefix("Bearer ").strip()
        try:
            payload = decode_access_token(token)
            request.state.user_id = payload["sub"]
            request.state.role = payload.get("role", "free")
        except JWTError:
            return JSONResponse(status_code=401, content={"error": "Authentication required"})
        except Exception:
            return JSONResponse(status_code=401, content={"error": "Authentication required"})

        return await call_next(request)
