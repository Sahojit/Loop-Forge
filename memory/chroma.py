import os
import logging
import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

_client: chromadb.ClientAPI | None = None


def get_chroma_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
        _client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
    return _client


def retrieve_similar_strategies(user_id: str, task_description: str, n_results: int = 3) -> list[dict]:
    try:
        client = get_chroma_client()
        collection = client.get_or_create_collection("task_strategies")
        results = collection.query(
            query_texts=[task_description],
            n_results=n_results,
            where={"user_id": user_id},
        )
        strategies = []
        for i, meta in enumerate(results.get("metadatas", [[]])[0]):
            strategies.append({
                "document": results["documents"][0][i] if results.get("documents") else "",
                **meta,
            })
        return strategies
    except Exception as e:
        logger.warning("ChromaDB query failed: %s", e)
        return []


def store_strategy(user_id: str, task_id: str, task_description: str, metadata: dict) -> None:
    try:
        client = get_chroma_client()
        collection = client.get_or_create_collection("task_strategies")
        safe_meta = {k: str(v) for k, v in metadata.items()}
        collection.upsert(
            documents=[task_description[:500]],
            metadatas=[{**safe_meta, "user_id": user_id, "task_id": task_id}],
            ids=[task_id],
        )
    except Exception as e:
        logger.warning("ChromaDB store failed: %s", e)
