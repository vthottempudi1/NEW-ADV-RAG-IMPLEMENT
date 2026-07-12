from urllib.parse import urlparse

from tavily import TavilyClient

from app.config import settings
from app.models import RetrievedChunk

_TRUSTED_WEB_DOMAINS = {
    "kubernetes.io",
    "cilium.io",
    "docs.cilium.io",
    "aws.amazon.com",
    "docs.aws.amazon.com",
    "argo-cd.readthedocs.io",
    "argoproj.github.io",
    "github.com",
    "blog.argoproj.io",
}


# Learner Note: Enterprise web fallback must not treat arbitrary blogs as authoritative evidence.
def _is_trusted_web_source(url: str) -> bool:
    """Return whether a web result belongs to the explicit technical-source allowlist."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if host == "aws.amazon.com" and path.startswith("/blogs/"):
        return False
    if host == "github.com" and not path.startswith(("/cilium/", "/argoproj/")):
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in _TRUSTED_WEB_DOMAINS)


# Learner note: Implements search web, a key retrieval-quality step in the RAG pipeline.
def search_web(question: str, top_k: int = 5) -> list[RetrievedChunk]:
    """Perform search web for the retrieval-augmented generation pipeline.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    if not settings.tavily_api_key:
        raise ValueError("Tavily API key not configured")

    client = TavilyClient(api_key=settings.tavily_api_key)
    result = client.search(
        query=question,
        search_depth="advanced",
        max_results=top_k,
        include_domains=sorted(_TRUSTED_WEB_DOMAINS),
    )

    chunks: list[RetrievedChunk] = []
    for item in result.get("results", []):
        source = item.get("url", "web")
        if not _is_trusted_web_source(source):
            continue
        text = (item.get("content") or item.get("title") or "").strip()
        if not text:
            continue
        chunks.append(
            RetrievedChunk(
                text=text,
                source=source,
                score=0.5,
                retrieval_score=0.5,
            )
        )
    return chunks
