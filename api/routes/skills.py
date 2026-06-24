import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, field_validator

from security.sanitizer import sanitize_input
from core.skills import validate_template, test_render
from memory.skills_search import index_skill, search_skills, delete_skill as chroma_delete

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/skills", tags=["skills"])


class SkillCreate(BaseModel):
    name: str
    description: str = ""
    prompt_template: str
    tool_tags: list[str] = []
    is_public: bool = False

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name cannot be empty")
        return v.strip()


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    prompt_template: str | None = None
    tool_tags: list[str] | None = None
    is_public: bool | None = None


@router.post("", status_code=201)
async def create_skill(body: SkillCreate, request: Request):
    user_id: str = request.state.user_id
    sanitize_input(body.name)
    sanitize_input(body.prompt_template)

    valid, err = validate_template(body.prompt_template)
    if not valid:
        raise HTTPException(status_code=400, detail={"error": err})

    from db.postgres import get_pool
    pool = await get_pool()
    skill_id = str(uuid.uuid4())

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO skills (id, user_id, name, description, prompt_template, tool_tags, is_public)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            skill_id, user_id, body.name, body.description,
            body.prompt_template, body.tool_tags, body.is_public,
        )

    index_skill(skill_id, user_id, body.name, body.description, body.is_public)
    return {"skill_id": skill_id, "message": "Skill created"}


@router.get("")
async def list_skills(request: Request, page: int = 1, page_size: int = 20):
    user_id: str = request.state.user_id
    offset = (page - 1) * page_size

    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, name, description, tool_tags, is_public, version, created_at, updated_at
               FROM skills WHERE user_id = $1
               ORDER BY updated_at DESC LIMIT $2 OFFSET $3""",
            user_id, page_size, offset,
        )
        total = await conn.fetchval("SELECT COUNT(*) FROM skills WHERE user_id = $1", user_id)

    return {
        "skills": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/search")
async def search(q: str, request: Request):
    user_id: str = request.state.user_id
    sanitize_input(q)
    results = search_skills(q, user_id)
    return {"results": results, "query": q}


@router.get("/{skill_id}")
async def get_skill(skill_id: str, request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM skills WHERE id = $1 AND user_id = $2",
            skill_id, user_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail={"error": "Skill not found"})
    return dict(row)


@router.put("/{skill_id}")
async def update_skill(skill_id: str, body: SkillUpdate, request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    pool = await get_pool()

    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM skills WHERE id = $1 AND user_id = $2", skill_id, user_id,
        )
        if not existing:
            raise HTTPException(status_code=404, detail={"error": "Skill not found"})

        new_template = body.prompt_template or existing["prompt_template"]
        if body.prompt_template:
            sanitize_input(body.prompt_template)
            valid, err = validate_template(body.prompt_template)
            if not valid:
                raise HTTPException(status_code=400, detail={"error": err})

        await conn.execute(
            """UPDATE skills SET
               name=COALESCE($1, name),
               description=COALESCE($2, description),
               prompt_template=COALESCE($3, prompt_template),
               tool_tags=COALESCE($4, tool_tags),
               is_public=COALESCE($5, is_public),
               version=version+1,
               updated_at=NOW()
               WHERE id=$6 AND user_id=$7""",
            body.name, body.description, body.prompt_template,
            body.tool_tags, body.is_public, skill_id, user_id,
        )
        updated = await conn.fetchrow(
            "SELECT name, description, is_public FROM skills WHERE id = $1", skill_id,
        )

    index_skill(skill_id, user_id, updated["name"], updated["description"] or "", updated["is_public"])
    return {"skill_id": skill_id, "message": "Skill updated"}


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(skill_id: str, request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM skills WHERE id = $1 AND user_id = $2", skill_id, user_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail={"error": "Skill not found"})
    chroma_delete(skill_id)


@router.post("/{skill_id}/test")
async def test_skill(skill_id: str, request: Request):
    user_id: str = request.state.user_id
    from db.postgres import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT prompt_template FROM skills WHERE id = $1 AND user_id = $2",
            skill_id, user_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail={"error": "Skill not found"})

    ok, result = test_render(row["prompt_template"])
    if not ok:
        return {"success": False, "error": result}
    return {"success": True, "rendered_prompt": result}
