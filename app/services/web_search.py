from tavily import TavilyClient

from app.config import settings
from app.models import RetrievedChunk


def search_web(question: str, top_k: int = 5) -> list[RetrievedChunk]:
    if not settings.tavily_api_key:
        raise ValueError("Tavily API key not configured")

    client = TavilyClient(api_key=settings.tavily_api_key)
    result = client.search(
        query=question,
        search_depth="advanced",
        max_results=top_k,
    )

    chunks: list[RetrievedChunk] = []
    for item in result.get("results", []):
        text = (item.get("content") or item.get("title") or "").strip()
        if not text:
            continue
        chunks.append(
            RetrievedChunk(
                text=text,
                source=item.get("url", "web"),
                score=0.5,
                retrieval_score=0.5,
            )
        )
    return chunks