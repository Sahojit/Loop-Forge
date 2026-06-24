import logging
from typing import Any

logger = logging.getLogger(__name__)

_COLLECTION = "skills"


def _collection():
    from memory.chroma import get_chroma_client
    return get_chroma_client().get_or_create_collection(_COLLECTION)


def index_skill(skill_id: str, user_id: str, name: str, description: str, is_public: bool) -> None:
    doc = f"{name}: {description or ''}"
    try:
        _collection().upsert(
            documents=[doc],
            metadatas=[{"user_id": user_id, "skill_name": name, "is_public": str(is_public).lower()}],
            ids=[skill_id],
        )
    except Exception as e:
        logger.warning("Skill index upsert failed: %s", e)


def search_skills(query: str, user_id: str, n_results: int = 10) -> list[dict[str, Any]]:
    try:
        col = _collection()
        results = col.query(
            query_texts=[query],
            n_results=n_results,
            where={"$or": [{"user_id": user_id}, {"is_public": "true"}]},
        )
        hits = []
        for i, meta in enumerate(results.get("metadatas", [[]])[0]):
            hits.append({
                "skill_id": results["ids"][0][i],
                "document": results["documents"][0][i] if results.get("documents") else "",
                "distance": results["distances"][0][i] if results.get("distances") else None,
                **meta,
            })
        return hits
    except Exception as e:
        logger.warning("Skill search failed: %s", e)
        return []


def delete_skill(skill_id: str) -> None:
    try:
        _collection().delete(ids=[skill_id])
    except Exception as e:
        logger.warning("Skill delete from ChromaDB failed: %s", e)
