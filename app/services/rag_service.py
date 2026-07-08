import json
import re
from statistics import mean

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
from app.services.cost_service import answer_model_cost, format_usd, grader_model_cost, sql_model_cost
from app.services.auto_retrieval import resolve_auto_retrieval


RAG_CACHE_SCHEMA_VERSION = 14
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
_TEMP_SOURCE_PATTERN = re.compile(r"^tmp[a-z0-9_\\-]+\.[A-Za-z0-9]+$")
_LOCAL_CORPUS_PRIORITY_HINTS = (
    "our ",
    "runbook",
    "policy",
    "playbook",
    "incident",
    "alert",
    "alerts",
    "p1",
    "p2",
)
_VAGUE_QUERY_STOPWORDS = {
    "what",
    "is",
    "wrong",
    "why",
    "how",
    "help",
    "issue",
    "problem",
    "the",
    "this",
    "that",
}
_OPERATIONAL_GUIDANCE_HINTS = ("runbook", "policy", "playbook", "procedure", "guidance")
_OPERATIONAL_SOURCE_PATTERN = re.compile(r"(runbook|policy|playbook|procedure)", re.IGNORECASE)
_DASHBOARD_SOURCE_PATTERN = re.compile(r"dashboard", re.IGNORECASE)
_KUBERNETES_CORPUS_SOURCE_PATTERN = re.compile(r"^(concepts|tasks|tutorials|reference)__", re.IGNORECASE)
_ANCHOR_STOPWORDS = {
    "what",
    "which",
    "when",
    "where",
    "why",
    "how",
    "difference",
    "between",
    "compare",
    "kubernetes",
    "cluster",
    "would",
    "should",
    "could",
    "does",
    "mean",
    "that",
    "same",
    "object",
    "into",
    "only",
    "other",
    "container",
    "automatically",
    "read",
    "too",
    "use",
    "using",
    "still",
    "resource",
    "combine",
    "something",
    "else",
    "confidential",
    "sensitive",
    "non",
    "data",
}
_KNOWN_K8S_ENTITIES = (
    "configmap",
    "secret",
    "pod",
    "deployment",
    "statefulset",
    "daemonset",
    "service",
    "ingress",
    "namespace",
    "serviceaccount",
    "rbac",
    "readiness",
    "liveness",
)


def _normalize_confidence_signal(score: float | None) -> float:
    if score is None:
        return 0.0

    value = float(score)
    if value <= 0:
        return 0.0
    if value <= 0.25:
        return min(value / 0.25, 1.0)
    if value <= 1.0:
        return 0.7 + (0.3 * ((value - 0.25) / 0.75))
    return 1.0


def _normalize_reflection_score(score: float | None) -> float:
    if score is None:
        return 0.0

    value = float(score)
    if value <= 0:
        return 0.0
    if value <= 1.0:
        return value
    return min(value / 5.0, 1.0)


def _calculate_confidence(
    *,
    chunks: list,
    top_k: int,
    enable_crag: bool,
    crag_score: float | None,
    reflection_score: float | None,
) -> float:
    if not chunks:
        return 0.0

    effective_top_k = max(top_k, 1)
    coverage = min(len(chunks) / effective_top_k, 1.0)

    normalized_scores = [_normalize_confidence_signal(chunk.score) for chunk in chunks]
    top_quality = normalized_scores[0]
    avg_quality = mean(normalized_scores[: min(3, len(normalized_scores))])

    confidence = (
        0.15
        + (0.35 * top_quality)
        + (0.25 * avg_quality)
        + (0.15 * coverage)
    )

    if enable_crag and crag_score is not None:
        confidence = (0.8 * confidence) + (0.2 * max(0.0, min(float(crag_score), 1.0)))

    if reflection_score is not None:
        confidence = (0.9 * confidence) + (0.1 * _normalize_reflection_score(reflection_score))

    return max(0.0, min(confidence, 1.0))


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


def _normalize_temp_sources(chunks: list) -> list:
    if not chunks:
        return chunks

    temp_sources = {
        chunk.source
        for chunk in chunks
        if isinstance(chunk.source, str) and _TEMP_SOURCE_PATTERN.match(chunk.source)
    }
    non_temp_sources = {
        chunk.source
        for chunk in chunks
        if isinstance(chunk.source, str) and not _TEMP_SOURCE_PATTERN.match(chunk.source)
    }

    if not temp_sources or len(non_temp_sources) != 1:
        return chunks

    canonical_source = next(iter(non_temp_sources))
    normalized = []
    for chunk in chunks:
        if chunk.source in temp_sources:
            chunk = chunk.model_copy(update={"source": canonical_source})
        normalized.append(chunk)
    return normalized


def _prefer_local_corpus(question: str) -> bool:
    lowered = question.lower()
    return any(hint in lowered for hint in _LOCAL_CORPUS_PRIORITY_HINTS)


def _is_vague_query(question: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", question.lower())
    if len(tokens) <= 4:
        return True
    meaningful = [token for token in tokens if token not in _VAGUE_QUERY_STOPWORDS]
    return len(meaningful) <= 2


def _extract_answer_text(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text
        answer = payload.get("answer")
        if isinstance(answer, str) and answer.strip():
            return answer.strip()
    return text


def _prefer_operational_sources(question: str, chunks: list) -> list:
    lowered = question.lower()
    if not any(hint in lowered for hint in _OPERATIONAL_GUIDANCE_HINTS):
        return chunks

    filtered = [
        chunk for chunk in chunks
        if isinstance(chunk.source, str) and _OPERATIONAL_SOURCE_PATTERN.search(chunk.source)
    ]
    return filtered or chunks


def _extract_anchor_terms(question: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", question.lower())
    anchors: list[str] = []
    for token in tokens:
        if token in _ANCHOR_STOPWORDS:
            continue
        if len(token) >= 4 or token in {"pod", "rbac"}:
            if token not in anchors:
                anchors.append(token)
    return anchors


def _extract_question_entities(question: str) -> list[str]:
    lowered = question.lower()
    entities: list[str] = []
    for entity in _KNOWN_K8S_ENTITIES:
        if entity in lowered and entity not in entities:
            entities.append(entity)
    return entities


def _prefer_entity_named_sources(question: str, chunks: list) -> list:
    if not chunks:
        return chunks

    entities = _extract_question_entities(question)
    if not entities:
        return chunks

    named_matches = [
        chunk
        for chunk in chunks
        if isinstance(chunk.source, str)
        and any(entity in chunk.source.lower() for entity in entities)
    ]
    return named_matches or chunks


def _prefer_anchor_matched_sources(question: str, chunks: list) -> list:
    if not chunks:
        return chunks

    anchors = _extract_anchor_terms(question)
    if not anchors:
        return chunks

    scored: list[tuple[int, object]] = []
    matched_count = 0
    for chunk in chunks:
        haystack = f"{chunk.source} {chunk.text[:1500]}".lower()
        overlap = sum(1 for anchor in anchors if anchor in haystack)
        if overlap > 0:
            matched_count += 1
        scored.append((overlap, chunk))

    if matched_count == 0 or matched_count == len(chunks):
        return chunks

    filtered = [chunk for overlap, chunk in scored if overlap > 0]
    return filtered or chunks


def _drop_non_kubernetes_corpus_noise(question: str, chunks: list) -> list:
    if not chunks:
        return chunks

    if "kubernetes" not in question.lower() and not _extract_question_entities(question):
        return chunks

    canonical = [
        chunk
        for chunk in chunks
        if isinstance(chunk.source, str)
        and _KUBERNETES_CORPUS_SOURCE_PATTERN.search(chunk.source)
    ]
    if canonical and len(canonical) < len(chunks):
        return canonical
    return chunks


def _drop_dashboard_catalog_noise(chunks: list) -> list:
    if not chunks:
        return chunks

    non_dashboard = [
        chunk for chunk in chunks
        if not (isinstance(chunk.source, str) and _DASHBOARD_SOURCE_PATTERN.search(chunk.source))
    ]
    if len(non_dashboard) >= 2 and len(non_dashboard) < len(chunks):
        return non_dashboard
    return chunks


def _drop_negative_rerank_tail(chunks: list) -> list:
    if not chunks:
        return chunks

    positive = [
        chunk for chunk in chunks
        if chunk.rerank_score is not None and float(chunk.rerank_score) >= 0.0
    ]
    if len(positive) >= 2:
        return positive
    return chunks


def _ordered_sources(chunks: list) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for chunk in chunks:
        source = str(chunk.source)
        if source not in seen:
            seen.add(source)
            ordered.append(source)
    return ordered


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
    auto_decision = resolve_auto_retrieval(
        question=question,
        search_mode=search_mode,
        enable_rerank=enable_rerank,
        enable_hyde=enable_hyde,
        enable_crag=enable_crag,
        enable_self_reflective=enable_self_reflective,
    )
    search_mode = auto_decision.resolved_search_mode
    enable_rerank = auto_decision.enable_rerank
    enable_hyde = auto_decision.enable_hyde
    enable_crag = auto_decision.enable_crag
    enable_self_reflective = auto_decision.enable_self_reflective
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
        response.cost_saved = format_usd(float(cached.get("estimated_answer_cost_usd", 0.0)))
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
        allow_web_fallback=not (
            _prefer_local_corpus(question)
            or (enable_self_reflective and _is_vague_query(question))
        ),
    )
    chunks = _trim_troubleshooting_noise(chunks, question)
    chunks = _normalize_temp_sources(chunks)
    chunks = _prefer_operational_sources(question, chunks)
    chunks = _drop_non_kubernetes_corpus_noise(question, chunks)
    chunks = _prefer_entity_named_sources(question, chunks)
    chunks = _prefer_anchor_matched_sources(question, chunks)
    chunks = _drop_dashboard_catalog_noise(chunks)
    chunks = _drop_negative_rerank_tail(chunks)

    context = build_spotlighted_context(chunks)
    alias_guidance = _build_alias_guidance(question, chunks)

    system = build_system_prompt()
    total_answer_cost_usd = 0.0


    def _draft(current_question: str) -> str:
        nonlocal total_answer_cost_usd

        guidance_block = f"{alias_guidance}\n\n" if alias_guidance else ""
        user_message = f"Context:\n{context}\n\nQuestion: {current_question}"
        result = generate(system, f"{guidance_block}{user_message}")

        usage = result.get("usage", {})
        total_answer_cost_usd += answer_model_cost(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

        return _extract_answer_text(result["text"])


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

    confidence = _calculate_confidence(
        chunks=chunks,
        top_k=top_k,
        enable_crag=enable_crag,
        crag_score=crag_evaluation.relevance_score if enable_crag else None,
        reflection_score=reflection_score,
    )

    response = ChatResponse(
        answer=uncertainty_prefix + answer,
        sources=_ordered_sources(chunks),
        confidence=confidence,
        cache_hit=False,
        metadata=ResponseMetadata(
            route="rag",
            retrieved_chunks=previews,
            cache_hit=False,
            requested_search_mode=auto_decision.requested_search_mode,
            resolved_search_mode=auto_decision.resolved_search_mode,
            auto_enabled=auto_decision.auto_enabled,
            auto_strategy_reason=auto_decision.auto_strategy_reason,
            auto_applied_flags=auto_decision.auto_applied_flags,
            reflection_iterations=reflection_iterations,
            reflection_score=reflection_score,
            refined_question=refined_question,
            crag_score=crag_evaluation.relevance_score if enable_crag else None,
            crag_label=crag_evaluation.relevance_label if enable_crag else None,
            used_web_fallback=used_web_fallback,
        ),
    )

    if use_cache:
        payload = response.model_dump()
        payload["estimated_answer_cost_usd"] = round(total_answer_cost_usd, 6)
        query_cache.set_rag_answer(question, payload, cache_context)
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
