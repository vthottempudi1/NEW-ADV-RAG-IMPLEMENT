from openai import OpenAI

from app.caching.query_cache import query_cache
from app.config import settings

openai_client = OpenAI(api_key=settings.openai_api_key)


def embed_texts(
    texts: list[str],
    model: str | None = None,
    *,
    use_cache: bool = True,
) -> list[list[float]]:
    """Embed a list of texts via OpenAI, using the query cache to skip repeat work.

    Returns `[]` immediately for empty input. When `use_cache` is False, all
    texts are sent to OpenAI in a single request. Otherwise each text is first
    looked up in the embedding cache; cache misses are batched (512 per
    request, OpenAI's limit) into `openai_client.embeddings.create` calls and
    the results are written back to the cache before being merged with the
    cache hits, preserving the original input order.
    """
    if not texts:
        return []

    model = model or settings.embedding_model

    if not use_cache:
        response = openai_client.embeddings.create(input=texts, model=model)
        return [item.embedding for item in response.data]

    results: list[list[float] | None] = [None] * len(texts)
    miss_indices: list[int] = []
    miss_texts: list[str] = []

    for i, text in enumerate(texts):
        cached = query_cache.get_embedding(text)
        if cached is not None:
            results[i] = cached
        else:
            miss_indices.append(i)
            miss_texts.append(text)

    if miss_texts:
        batch_size = 512
        for start in range(0, len(miss_texts), batch_size):
            batch_texts = miss_texts[start:start + batch_size]
            batch_indices = miss_indices[start:start + batch_size]

            response = openai_client.embeddings.create(
                input=batch_texts,
                model=model,
            )

            for idx_in_batch, item in enumerate(response.data):
                original_idx = batch_indices[idx_in_batch]
                vector = item.embedding
                results[original_idx] = vector
                query_cache.set_embedding(batch_texts[idx_in_batch], vector)

    return [vector for vector in results if vector is not None]
