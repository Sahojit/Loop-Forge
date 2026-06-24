import os
import re
from tavily import TavilyClient


_client: TavilyClient | None = None


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        _client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY", ""))
    return _client


def _sanitize(text: str, max_len: int = 500) -> str:
    clean = re.sub(r"<[^>]+>", "", text)
    return clean[:max_len]


def tavily_search(query: str) -> str:
    client = _get_client()
    result = client.search(query=query, max_results=3)
    snippets = []
    for r in result.get("results", []):
        content = _sanitize(r.get("content", ""))
        snippets.append(f"[{r.get('title', '')}]: {content}")
    return "\n\n".join(snippets) if snippets else "No results found."
