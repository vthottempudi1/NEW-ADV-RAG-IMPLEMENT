from openai import OpenAI

from app.caching.query_cache import query_cache
from app.config import settings

openai_client = OpenAI(api_key=settings.openai_api_key)


# Learner note: Encapsulates embed texts so this responsibility can be understood, tested, and changed independently.
def embed_texts(
    texts: list[str],
    model: str | None = None,
    *,
    use_cache: bool = True,
) -> list[list[float]]:
    """Perform embed texts for the retrieval-augmented generation pipeline.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
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
