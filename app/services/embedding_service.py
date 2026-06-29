from openai import OpenAI

from app.config import settings
from app.services.query_cache_service import query_cache


openai_client = OpenAI(api_key=settings.openai_api_key)


def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    if not texts:
        return []

    model = model or settings.embedding_model

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