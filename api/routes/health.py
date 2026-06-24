import os
from fastapi import APIRouter
from api.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        environment=os.getenv("ENVIRONMENT", "development"),
    )
