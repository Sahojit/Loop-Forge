from pydantic import BaseModel, EmailStr, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TaskRequest(BaseModel):
    input: str
    max_iterations: int | None = None
    strategy: str = "auto"

    @field_validator("strategy")
    @classmethod
    def valid_strategy(cls, v: str) -> str:
        if v not in ("fast", "thorough", "auto"):
            raise ValueError("strategy must be 'fast', 'thorough', or 'auto'")
        return v


class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str = "Task queued"


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    final_output: str | None = None
    score_history: list[float] = []
    iterations: int = 0
    final_score: float | None = None
    tokens_used: int = 0
    tools_used: list[str] = []
    convergence_status: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str = "1.0.0"
    environment: str
