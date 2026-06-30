import re

from app.config import settings
from app.models import ChatResponse, ResponseMetadata, RetrievedChunkPreview
from app.services.system_prompt import build_system_prompt
from app.services.crag import crag_pipeline
from app.services.embedding_service import embed_texts
from app.services.hyde import HyDERetriever
from app.services.llm_service import generate
from app.services.query_cache_service import query_cache
from app.services.reranking import Reranker
from app.services.self_reflective import reflect_on_answer, should_regenerate
from app.services.vector_store import hybrid_search, search, sparse_search
from app.security.spotlighting import build_spotlighted_context


RAG_CACHE_SCHEMA_VERSION = 11
_TROUBLESHOOTING_HINTS = {
    "error",
    "fix",
    "troubleshoot",
    "troubleshooting",
    "debug",
    "runbook",
    "incident",
    "oomkilled",
    "errimagepull",
    "imagepullbackoff",
    "crashloopbackoff",
    "logs",
}
_TROUBLESHOOTING_ALIASES = {
    "errimagepull": ("imagepullbackoff",),
    "imagepullbackoff": ("errimagepull",),
    "oomkilled": ("oom", "out of memory", "eviction"),
    "crashloopbackoff": ("restart", "container restart", "backoff"),
}


def _cache_context(
    top_k: int,
    search_mode: str,
    enable_rerank: bool,
    enable_hyde: bool,
    enable_crag: bool,
    enable_self_reflective: bool,
) -> dict:
    return {
        "schema_version": RAG_CACHE_SCHEMA_VERSION,
        "top_k": top_k,
        "search_mode": search_mode,
        "enable_rerank": enable_rerank,
        "enable_hyde": enable_hyde,
        "enable_crag": enable_crag,
        "enable_self_reflective": enable_self_reflective,
    }


def _is_troubleshooting_query(question: str) -> bool:
    lowered = question.lower()
    if any(hint in lowered for hint in _TROUBLESHOOTING_HINTS):
        return True

    for token in re.findall(r"[A-Za-z0-9_./:-]+", question):
        if len(token) >= 6 and any(char.isupper() for char in token[1:]):
            return True
    return False


def _trim_troubleshooting_noise(chunks: list, question: str) -> list:
    if not chunks or not _is_troubleshooting_query(question):
        return chunks

    top_score = max(float(chunk.score or 0.0) for chunk in chunks)
    threshold = max(0.35, top_score * 0.6)
    filtered = [chunk for chunk in chunks if float(chunk.score or 0.0) >= threshold]
    return filtered or chunks[:1]


def _build_alias_guidance(question: str, chunks: list) -> str:
    lowered_question = question.lower()
    if not chunks or not _is_troubleshooting_query(question):
        return ""

    haystack = " ".join(f"{chunk.source} {chunk.text[:1200]}" for chunk in chunks).lower()
    notes: list[str] = []

    for term, aliases in _TROUBLESHOOTING_ALIASES.items():
        if term not in lowered_question:
            continue
        matched_aliases = [alias for alias in aliases if alias in haystack]
        if matched_aliases:
            alias_text = ", ".join(dict.fromkeys(matched_aliases))
            notes.append(
                f"If the context mentions {alias_text} while the user asked about {term}, "
                "treat that as relevant troubleshooting evidence and explain the relationship clearly."
            )

    if not notes:
        return ""

    return "Troubleshooting note:\n- " + "\n- ".join(notes)


def run_rag(
    question: str,
    top_k: int = 5,
    search_mode: str = "dense",
    enable_rerank: bool = False,
    enable_hyde: bool = False,
    enable_crag: bool = False,
    enable_self_reflective: bool = False,
) -> ChatResponse:
    response, _ = _run_rag_impl(
        question=question,
        top_k=top_k,
        search_mode=search_mode,
        enable_rerank=enable_rerank,
        enable_hyde=enable_hyde,
        enable_crag=enable_crag,
        enable_self_reflective=enable_self_reflective,
        use_cache=True,
    )
    return response


def _run_rag_impl(
    question: str,
    top_k: int = 5,
    search_mode: str = "dense",
    enable_rerank: bool = False,
    enable_hyde: bool = False,
    enable_crag: bool = False,
    enable_self_reflective: bool = False,
    use_cache: bool = True,
) -> tuple[ChatResponse, list]:
    cache_context = _cache_context(
        top_k,
        search_mode,
        enable_rerank,
        enable_hyde,
        enable_crag,
        enable_self_reflective,
    )
    cached = query_cache.get_rag_answer(question, cache_context) if use_cache else None

    if cached is not None:
        response = ChatResponse(**cached)
        response.cache_hit = True
        response.metadata.cache_hit = True
        return response, []

    retrieve_k = settings.reranker_initial_top_k if enable_rerank else top_k


    def _retrieve_once(force_hyde: bool = False, top_k_override: int | None = None):
        current_k = top_k_override or retrieve_k
        if enable_hyde or force_hyde:
            local_chunks = HyDERetriever().retrieve(question, top_k=current_k, mode=search_mode)
        elif search_mode == "sparse":
            local_chunks = sparse_search(question, top_k=current_k)
        elif search_mode == "hybrid":
            query_embedding = embed_texts([question])[0]
            local_chunks = hybrid_search(query_embedding, question, top_k=current_k)
        else:
            query_embedding = embed_texts([question])[0]
            local_chunks = search(query_embedding, top_k=current_k)

        if enable_rerank and local_chunks:
            return Reranker().rerank(question, local_chunks, top_k=top_k)
        return local_chunks[:top_k]

    chunks = _retrieve_once()
    chunks = _trim_troubleshooting_noise(chunks, question)

    def _local_retry():
        if not enable_hyde:
            return _retrieve_once(force_hyde=True)
        return _retrieve_once(top_k_override=max(retrieve_k, top_k * 2))


    chunks, crag_evaluation, used_web_fallback = crag_pipeline(
        question=question,
        chunks=chunks,
        enable_crag=enable_crag,
        local_retry_fn=_local_retry,
    )
    chunks = _trim_troubleshooting_noise(chunks, question)

    context = build_spotlighted_context(chunks)
    alias_guidance = _build_alias_guidance(question, chunks)

    system = build_system_prompt()

    def _draft(current_question: str) -> str:
        guidance_block = f"{alias_guidance}\n\n" if alias_guidance else ""
        user_message = f"{guidance_block}Context:\n{context}\n\nQuestion: {current_question}"
        return generate(system, user_message)["text"]

    working_question = question
    answer = _draft(working_question)

    reflection_iterations = 0
    reflection_score = None
    refined_question = None

    if enable_self_reflective:
        while True:
            reflection = reflect_on_answer(
                question=working_question,
                answer=answer,
                context=context,
            )
            reflection_score = reflection.reflection_score

            if not should_regenerate(reflection, reflection_iterations):
                break

            refined_question = reflection.refined_question or working_question
            working_question = refined_question
            answer = _draft(working_question)
            reflection_iterations += 1

    previews = [
        RetrievedChunkPreview(
            text=chunk.text,
            source=chunk.source,
            score=chunk.score,
            retrieval_score=chunk.retrieval_score,
            rerank_score=chunk.rerank_score,
        )
        for chunk in chunks
    ]

    uncertainty_prefix = ""
    if (
        enable_crag
        and not used_web_fallback
        and crag_evaluation.relevance_score < settings.crag_relevance_threshold
    ):
        uncertainty_prefix = (
            "I may not have enough reliable context to answer this fully. "
            "Based on the available information:\n\n"
        )

    response = ChatResponse(
        answer=uncertainty_prefix + answer,
        sources=list({chunk.source for chunk in chunks}),
        confidence=0.7 if chunks else 0.0,
        cache_hit=False,
        metadata=ResponseMetadata(
            route="rag",
            retrieved_chunks=previews,
            cache_hit=False,
            reflection_iterations=reflection_iterations,
            reflection_score=reflection_score,
            refined_question=refined_question,
            crag_score=crag_evaluation.relevance_score if enable_crag else None,
            crag_label=crag_evaluation.relevance_label if enable_crag else None,
            used_web_fallback=used_web_fallback,
        ),
    )

    if use_cache:
        query_cache.set_rag_answer(question, response.model_dump(), cache_context)
    return response, chunks


def run_rag_with_trace(
    question: str,
    flags: dict | None = None,
) -> tuple[ChatResponse, list]:
    flags = flags or {}
    return _run_rag_impl(
        question=question,
        top_k=flags.get("top_k", 5),
        search_mode=flags.get("search_mode", "dense"),
        enable_rerank=flags.get("enable_rerank", False),
        enable_hyde=flags.get("enable_hyde", False),
        enable_crag=flags.get("enable_crag", False),
        enable_self_reflective=flags.get("enable_self_reflective", False),
        use_cache=True,
    )


def run_rag_with_trace_no_cache(
    question: str,
    flags: dict | None = None,
) -> tuple[ChatResponse, list]:
    flags = flags or {}
    return _run_rag_impl(
        question=question,
        top_k=flags.get("top_k", 5),
        search_mode=flags.get("search_mode", "dense"),
        enable_rerank=flags.get("enable_rerank", False),
        enable_hyde=flags.get("enable_hyde", False),
        enable_crag=flags.get("enable_crag", False),
        enable_self_reflective=flags.get("enable_self_reflective", False),
        use_cache=False,
    )
