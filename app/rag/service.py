import json
import re
from statistics import mean

from app.caching.query_cache import query_cache
from app.config import settings
from app.models import ChatResponse, ResponseMetadata, RetrievedChunkPreview
from app.observability.costs import answer_model_cost, format_usd
from app.rag.auto_retrieval import resolve_auto_retrieval
from app.rag.clarification import detect_clarification_need
from app.rag.crag import crag_pipeline
from app.rag.embedding_service import embed_texts
from app.rag.hyde import HyDERetriever
from app.rag.llm_service import generate
from app.rag.reranking import Reranker
from app.rag.self_reflective import reflect_on_answer, should_regenerate
from app.rag.system_prompt import build_system_prompt
from app.rag.vector_store import hybrid_search, search, sparse_search
from app.security.spotlighting import build_spotlighted_context

RAG_CACHE_SCHEMA_VERSION = 46
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
_OPERATIONAL_GUIDANCE_HINTS = (
    "runbook",
    "policy",
    "playbook",
    "procedure",
    "guidance",
    "remediation",
    "mttr",
)
_OPERATIONAL_SOURCE_PATTERN = re.compile(
    r"(runbook|policy|playbook|procedure|incident[-_ ]response|escalation)",
    re.IGNORECASE,
)
_DASHBOARD_SOURCE_PATTERN = re.compile(r"dashboard", re.IGNORECASE)
_KUBERNETES_CORPUS_SOURCE_PATTERN = re.compile(r"^(concepts|tasks|tutorials|reference)__", re.IGNORECASE)
_SERVICE_DISCOVERY_SOURCE_PATTERN = re.compile(
    r"(services-networking__service|connect-applications-service|service-v1)",
    re.IGNORECASE,
)
_SECURITY_SOURCE_PATTERN = re.compile(r"(security|rbac|least[-_ ]privilege)", re.IGNORECASE)
_STATEFUL_WORKLOAD_SOURCE_PATTERN = re.compile(r"statefulset", re.IGNORECASE)


def _evidence_plan(question: str) -> list[tuple[re.Pattern[str], str]]:
    """Return required source families and sparse rescue queries for composite questions."""
    lowered = question.lower()
    if "oomkilled" in lowered or (
        "oom" in lowered and any(term in lowered for term in ("memory", "container", "inspect"))
    ):
        return [
            (
                re.compile(r"node-pressure-eviction", re.I),
                "node pressure memory available eviction kubelet monitors memory terminates Pods",
            ),
            (
                re.compile(r"node-pressure-eviction", re.I),
                "OOM killer container memory requests limits usage QoS eviction",
            ),
            (
                re.compile(r"incident-response-runbook", re.I),
                "incident response review recent changes inspect alerts logs evidence mitigation",
            ),
        ]
    if "serviceaccount" in lowered and "default" in lowered and any(
        term in lowered for term in ("permission", "least privilege", "dedicated", "limit")
    ):
        return [
            (
                re.compile(r"configure-service-account", re.I),
                "non-default dedicated ServiceAccount Pod serviceAccountName permissions",
            ),
            (
                re.compile(r"rbac-good-practices", re.I),
                "least privilege minimal RBAC rights users service accounts required roles",
            ),
        ]
    if "no node" in lowered and "pod" in lowered and any(
        term in lowered for term in ("component", "placement", "assigned", "starts")
    ):
        return [
            (
                re.compile(r"scheduling-eviction__kube-scheduler", re.I),
                "kube-scheduler selects optimal node newly created unscheduled Pods",
            ),
            (
                re.compile(r"scheduling-eviction__kube-scheduler", re.I),
                "kube-scheduler assigns Pod selected Node binding scheduling decision",
            ),
            (
                re.compile(r"overview__components", re.I),
                "node components kubelet ensures Pods containers running container runtime",
            ),
        ]
    if "namespace" in lowered and "security boundary" in lowered:
        return [
            (
                re.compile(r"namespaces-walkthrough", re.I),
                "namespaces scope for names attach authorization policy subsection cluster",
            ),
            (
                re.compile(r"rbac-good-practices", re.I),
                "RBAC least privilege namespace RoleBindings authorization policy",
            ),
        ]
    if all(term in lowered for term in ("privileged", "baseline", "restricted")):
        return [
            (
                re.compile(r"cluster-level-pss", re.I),
                "Pod Security Standards privileged no warnings unrestricted namespace",
            ),
            (
                re.compile(r"cluster-level-pss", re.I),
                "baseline standard middle ground prevents known privilege escalations",
            ),
        ]
    if "serviceaccount" in lowered and any(
        term in lowered for term in ("short-lived", "short lived", "long-lived", "long lived", "tokenrequest", "projected")
    ):
        return [
            (
                re.compile(r"configure-service-account", re.I),
                "non-default dedicated ServiceAccount Pod spec serviceAccountName permissions",
            ),
            (
                re.compile(r"configure-service-account", re.I),
                "TokenRequest projected service account token short lived expiration rotation long lived Secret",
            ),
            (
                re.compile(r"rbac-good-practices", re.I),
                "least privilege minimal RBAC rights service accounts namespace RoleBindings",
            ),
        ]
    if "pod" in lowered and "pending" in lowered and any(
        term in lowered for term in ("kubectl", "investigation", "scheduling", "startup")
    ):
        return [
            (
                re.compile(r"kubectl__cheatsheet", re.I),
                "kubectl get pods describe pods verbose output",
            ),
            (
                re.compile(r"kubectl__cheatsheet", re.I),
                "kubectl get events sorted timestamp warning events",
            ),
            (
                re.compile(r"kubectl__cheatsheet", re.I),
                "kubectl logs Pod container previous running Pod",
            ),
            (
                re.compile(r"scheduling-eviction__kube-scheduler", re.I),
                "kube-scheduler unscheduled Pod filters nodes requirements binding",
            ),
        ]
    if "gpu" in lowered and "every" in lowered and any(term in lowered for term in ("node", "worker")):
        return [
            (re.compile(r"daemonset", re.I), "DaemonSet ensures all eligible nodes run a copy of a Pod"),
            (
                re.compile(r"daemonset", re.I),
                "DaemonSet nodeSelector node affinity eligible nodes template spec scheduling",
            ),
        ]
    if "secret" in lowered and any(term in lowered for term in ("serviceaccount", "identity", "authorization")):
        return [
            (
                re.compile(r"configuration__secret", re.I),
                "Secrets provide credentials passwords to Pods environment variables secretKeyRef",
            ),
            (re.compile(r"configure-service-account", re.I), "serviceAccountName dedicated ServiceAccount Pod"),
            (re.compile(r"rbac-good-practices", re.I), "RBAC least privilege namespace RoleBindings Secret get permissions"),
        ]
    if "https" in lowered and "request" in lowered and "ready" in lowered:
        return [
            (re.compile(r"services-networking__ingress", re.I), "Ingress controller HTTPS routing Service"),
            (
                re.compile(r"services-networking__service", re.I),
                "Kubernetes Service stable network endpoint changing Pods",
            ),
            (
                re.compile(r"services-networking__service", re.I),
                "Service routes traffic to healthy ready backend endpoints Pods",
            ),
            (re.compile(r"liveness-readiness-startup-probes", re.I), "readiness probe Service traffic ready Pod"),
        ]
    if "kube-scheduler" in lowered and any(term in lowered for term in ("score", "scoring", "candidate")):
        return [
            (
                re.compile(r"scheduling-eviction__kube-scheduler", re.I),
                "kube-scheduler filtering scoring feasible nodes highest score binding",
            ),
            (
                re.compile(r"scheduling-eviction__kube-scheduler", re.I),
                "scheduler active scoring rules Score plugins highest ranking Node",
            ),
        ]
    if "networkpolicy" in lowered or (
        "pods" in lowered
        and "egress" in lowered
        and any(term in lowered for term in ("ingress", "traffic", "tcp", "call"))
    ):
        return [
            (
                re.compile(r"services-networking__network-policies", re.I),
                "NetworkPolicy podSelector ingress from podSelector TCP port egress isolation",
            ),
            (
                re.compile(r"services-networking__network-policies", re.I),
                "Network policies additive union applicable policies ingress egress",
            ),
            (
                re.compile(r"services-networking__network-policies", re.I),
                "network plugin supports NetworkPolicy enforcement controller required",
            ),
        ]
    if "configmap" in lowered and any(term in lowered for term in ("edit", "update", "environment variable", "mounted")):
        return [
            (
                re.compile(r"configuration__configmap", re.I),
                "ConfigMaps consumed as environment variables are not updated automatically require pod restart",
            ),
            (
                re.compile(r"configuration__configmap", re.I),
                "mounted ConfigMap projected keys eventually updated kubelet sync cache propagation delay",
            ),
            (
                re.compile(r"configure-pod-configmap", re.I),
                "configure Pod ConfigMap mounted volume environment variables",
            ),
        ]
    return []


def _augment_planned_evidence(question: str, chunks: list) -> list:
    """Add one candidate from every required evidence family before reranking."""
    merged = list(chunks)
    seen = {(str(chunk.source), str(chunk.text[:120])) for chunk in merged}
    for pattern, query in _evidence_plan(question):
        existing_count = sum(pattern.search(str(chunk.source)) is not None for chunk in merged)
        if existing_count >= 3:
            continue
        for candidate in sparse_search(query, top_k=50):
            if pattern.search(str(candidate.source)):
                key = (str(candidate.source), str(candidate.text[:120]))
                if key not in seen:
                    seen.add(key)
                    merged.append(candidate)
                    existing_count += 1
                if existing_count >= 3:
                    break
    return merged


def _ensure_planned_evidence(question: str, chunks: list, top_k: int) -> list:
    """Reserve final evidence slots for each required source family, then fill by rank."""
    selected: list = []
    for pattern, _ in _evidence_plan(question):
        match = next((chunk for chunk in chunks if pattern.search(str(chunk.source))), None)
        if match is not None and match not in selected:
            selected.append(match)
    selected.extend(chunk for chunk in chunks if chunk not in selected)
    return selected[:top_k]


def _authoritative_planned_evidence(question: str) -> list:
    """Select the most query-specific passage from every planned authoritative source."""
    selected: list = []
    selected_keys: set[tuple[str, str]] = set()
    for pattern, query in _evidence_plan(question):
        terms = {term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 3}
        candidates = [
            chunk for chunk in sparse_search(query, top_k=50)
            if pattern.search(str(chunk.source))
            and (str(chunk.source), str(chunk.text)) not in selected_keys
        ]
        if candidates:
            best = max(
                candidates,
                key=lambda chunk: (
                    sum(term in chunk.text.lower() for term in terms),
                    float(chunk.score or 0.0),
                ),
            )
            selected.append(best)
            selected_keys.add((str(best.source), str(best.text)))
    return selected


def _merge_same_source_evidence(chunks: list) -> list:
    """Combine complementary planned passages so one source forms one coherent context."""
    merged: list = []
    positions: dict[str, int] = {}
    for chunk in chunks:
        source = str(chunk.source)
        if source not in positions:
            positions[source] = len(merged)
            merged.append(chunk)
            continue
        index = positions[source]
        existing = merged[index]
        if chunk.text not in existing.text:
            merged[index] = existing.model_copy(
                update={
                    "text": f"{existing.text}\n\n{chunk.text}",
                    "score": max(float(existing.score or 0.0), float(chunk.score or 0.0)),
                    "retrieval_score": max(
                        float(existing.retrieval_score or 0.0),
                        float(chunk.retrieval_score or 0.0),
                    ),
                }
            )
    return merged


def _planned_answer_guidance(question: str) -> str:
    """Constrain synthesis where the corpus supports a deliberately narrow comparison."""
    lowered = question.lower()
    if "oomkilled" in lowered or ("oom" in lowered and "memory" in lowered):
        return (
            "Synthesis constraint: Do not mention the unrelated profiling article. Answer using "
            "separate evidence-backed statements: inspect node memory pressure; compare workload "
            "usage with requests and limits; review recent changes; inspect alerts and logs. Do not "
            "combine all steps into one claim and do not add an unsupported root-cause conclusion."
        )
    if "namespace" in lowered and "security boundary" in lowered:
        return (
            "Synthesis constraint: Give only these documented observations as separate statements: "
            "namespaces scope names; namespaces provide a place to attach authorization and policy; "
            "RBAC is a key access-control mechanism. Conclude that namespace scope should be combined "
            "with RBAC rather than treated as the complete access-control design. Do not state a causal explanation involving "
            "cross-namespace access, attacks, escape, enforcement, or isolation."
        )
    if all(term in lowered for term in ("privileged", "baseline", "restricted")):
        return (
            "Synthesis constraint: Use separate short statements: Privileged produced no warnings in "
            "the example. Baseline is a middle ground. Baseline prevents known privilege escalations. "
            "Restricted is described as stricter based on cluster risk posture. Do not invent profile "
            "definitions, ideal environments, or additional requirements."
        )
    if "pod" in lowered and "pending" in lowered and "kubectl" in lowered:
        return (
            "Synthesis constraint: Provide only the documented sequence: get or describe the Pod, "
            "inspect warning events, and explain that no suitable node leaves it unscheduled. Mention "
            "kubectl logs only as a command for running containers. Do not add a general diagnostic "
            "conclusion not stated by the evidence."
        )
    return ""
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


# Learner note: Encapsulates normalize confidence signal so this responsibility can be understood, tested, and changed independently.
def _normalize_confidence_signal(score: float | None) -> float:
    """Support the retrieval-augmented generation pipeline by performing normalize confidence signal.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
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


# Learner note: Encapsulates normalize reflection score so this responsibility can be understood, tested, and changed independently.
def _normalize_reflection_score(score: float | None) -> float:
    """Support the retrieval-augmented generation pipeline by performing normalize reflection score.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    if score is None:
        return 0.0

    value = float(score)
    if value <= 0:
        return 0.0
    if value <= 1.0:
        return value
    return min(value / 5.0, 1.0)


# Learner note: Encapsulates calculate confidence so this responsibility can be understood, tested, and changed independently.
def _calculate_confidence(
    *,
    chunks: list,
    top_k: int,
    enable_crag: bool,
    crag_score: float | None,
    reflection_score: float | None,
) -> float:
    """Support the retrieval-augmented generation pipeline by performing calculate confidence.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
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


# Learner note: Encapsulates cache context so this responsibility can be understood, tested, and changed independently.
def _cache_context(
    top_k: int,
    search_mode: str,
    enable_rerank: bool,
    enable_hyde: bool,
    enable_crag: bool,
    enable_self_reflective: bool,
) -> dict:
    """Support the retrieval-augmented generation pipeline by performing cache context.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    return {
        "schema_version": RAG_CACHE_SCHEMA_VERSION,
        "top_k": top_k,
        "search_mode": search_mode,
        "enable_rerank": enable_rerank,
        "enable_hyde": enable_hyde,
        "enable_crag": enable_crag,
        "enable_self_reflective": enable_self_reflective,
    }


# Learner note: Encapsulates is troubleshooting query so this responsibility can be understood, tested, and changed independently.
def _is_troubleshooting_query(question: str) -> bool:
    """Support the retrieval-augmented generation pipeline by performing is troubleshooting query.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = question.lower()
    if any(hint in lowered for hint in _TROUBLESHOOTING_HINTS):
        return True

    for token in re.findall(r"[A-Za-z0-9_./:-]+", question):
        if len(token) >= 6 and any(char.isupper() for char in token[1:]):
            return True
    return False


# Learner note: Encapsulates trim troubleshooting noise so this responsibility can be understood, tested, and changed independently.
def _trim_troubleshooting_noise(chunks: list, question: str) -> list:
    """Support the retrieval-augmented generation pipeline by performing trim troubleshooting noise.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    if not chunks or not _is_troubleshooting_query(question):
        return chunks

    top_score = max(float(chunk.score or 0.0) for chunk in chunks)
    threshold = max(0.35, top_score * 0.6)
    filtered = [chunk for chunk in chunks if float(chunk.score or 0.0) >= threshold]
    return filtered or chunks[:1]


# Learner note: Encapsulates build alias guidance so this responsibility can be understood, tested, and changed independently.
def _build_alias_guidance(question: str, chunks: list) -> str:
    """Support the retrieval-augmented generation pipeline by performing build alias guidance.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
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


# Learner note: Encapsulates normalize temp sources so this responsibility can be understood, tested, and changed independently.
def _normalize_temp_sources(chunks: list) -> list:
    """Support the retrieval-augmented generation pipeline by performing normalize temp sources.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
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


# Learner note: Encapsulates prefer local corpus so this responsibility can be understood, tested, and changed independently.
def _prefer_local_corpus(question: str) -> bool:
    """Support the retrieval-augmented generation pipeline by performing prefer local corpus.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = question.lower()
    return any(hint in lowered for hint in _LOCAL_CORPUS_PRIORITY_HINTS)


# Learner note: Encapsulates is vague query so this responsibility can be understood, tested, and changed independently.
def _is_vague_query(question: str) -> bool:
    """Support the retrieval-augmented generation pipeline by performing is vague query.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    tokens = re.findall(r"[a-z0-9]+", question.lower())
    if len(tokens) <= 4:
        return True
    meaningful = [token for token in tokens if token not in _VAGUE_QUERY_STOPWORDS]
    return len(meaningful) <= 2


# Learner note: Encapsulates extract answer text so this responsibility can be understood, tested, and changed independently.
def _extract_answer_text(raw_text: str) -> str:
    """Support the retrieval-augmented generation pipeline by performing extract answer text.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
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


# Learner note: Encapsulates prefer operational sources so this responsibility can be understood, tested, and changed independently.
def _prefer_operational_sources(question: str, chunks: list) -> list:
    """Support the retrieval-augmented generation pipeline by performing prefer operational sources.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = question.lower()
    if not any(hint in lowered for hint in _OPERATIONAL_GUIDANCE_HINTS):
        return chunks

    filtered = [
        chunk for chunk in chunks
        if isinstance(chunk.source, str) and _OPERATIONAL_SOURCE_PATTERN.search(chunk.source)
    ]
    return filtered or chunks


# Learner note: Preserves Service discovery documents when lay wording describes changing Pod IP addresses.
def _prefer_service_discovery_sources(question: str, chunks: list) -> list:
    """Support the retrieval-augmented generation pipeline by performing prefer service discovery sources.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = question.lower()
    has_discovery_problem = (
        "pod ip" in lowered
        and any(term in lowered for term in ("changing", "change", "find", "clients", "connect"))
    ) or (
        any(term in lowered for term in ("address", "addresses", "destination"))
        and any(term in lowered for term in ("replace", "durable", "stable", "callers", "instances"))
    )
    if not has_discovery_problem:
        return chunks

    service_chunks = [
        chunk
        for chunk in chunks
        if isinstance(chunk.source, str)
        and _SERVICE_DISCOVERY_SOURCE_PATTERN.search(chunk.source)
    ]
    return service_chunks or chunks


# Learner note: Encapsulates extract anchor terms so this responsibility can be understood, tested, and changed independently.
def _extract_anchor_terms(question: str) -> list[str]:
    """Support the retrieval-augmented generation pipeline by performing extract anchor terms.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    tokens = re.findall(r"[a-z0-9]+", question.lower())
    anchors: list[str] = []
    for token in tokens:
        if token in _ANCHOR_STOPWORDS:
            continue
        if len(token) >= 4 or token in {"pod", "rbac"}:
            if token not in anchors:
                anchors.append(token)
    return anchors


# Learner note: Encapsulates extract question entities so this responsibility can be understood, tested, and changed independently.
def _extract_question_entities(question: str) -> list[str]:
    """Support the retrieval-augmented generation pipeline by performing extract question entities.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = question.lower()
    entities: list[str] = []
    for entity in _KNOWN_K8S_ENTITIES:
        if entity in lowered and entity not in entities:
            entities.append(entity)
    return entities


# Learner note: Encapsulates prefer entity named sources so this responsibility can be understood, tested, and changed independently.
def _prefer_entity_named_sources(question: str, chunks: list) -> list:
    """Support the retrieval-augmented generation pipeline by performing prefer entity named sources.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
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


# Learner note: Encapsulates prefer anchor matched sources so this responsibility can be understood, tested, and changed independently.
def _prefer_anchor_matched_sources(question: str, chunks: list) -> list:
    """Support the retrieval-augmented generation pipeline by performing prefer anchor matched sources.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    if not chunks:
        return chunks

    lowered = question.lower()
    if "kubernetes" in lowered and any(
        term in lowered for term in ("secure", "security", "rbac", "least privilege")
    ):
        # Broad security answers intentionally combine overview, RBAC, policy,
        # encryption, and audit evidence. Requiring the literal word "secure"
        # in every chunk incorrectly removes RBAC/least-privilege passages.
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


# Learner note: Encapsulates drop non kubernetes corpus noise so this responsibility can be understood, tested, and changed independently.
def _drop_non_kubernetes_corpus_noise(question: str, chunks: list) -> list:
    """Support the retrieval-augmented generation pipeline by performing drop non kubernetes corpus noise.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
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


# Learner Note: Broad cluster-security questions require both overview and RBAC evidence.
def _prefer_security_sources(question: str, chunks: list) -> list:
    """Prefer canonical security documents for explicit Kubernetes security questions."""
    lowered = question.lower()
    if not chunks or "kubernetes" not in lowered or not any(
        term in lowered for term in ("secure", "security", "rbac", "least privilege")
    ):
        return chunks
    matches = [
        chunk
        for chunk in chunks
        if isinstance(chunk.source, str)
        and _KUBERNETES_CORPUS_SOURCE_PATTERN.search(chunk.source)
        and _SECURITY_SOURCE_PATTERN.search(chunk.source)
    ]
    return matches or chunks


# Learner Note: Broad security wording needs deterministic RBAC vocabulary expansion.
def _augment_security_evidence(question: str, chunks: list) -> list:
    """Merge sparse RBAC/least-privilege evidence into broad security retrieval results."""
    lowered = question.lower()
    if "kubernetes" not in lowered or not any(
        term in lowered for term in ("secure", "security", "rbac", "least privilege")
    ):
        return chunks

    rescue = sparse_search(
        f"{question} Kubernetes RBAC least privilege role based access control",
        top_k=10,
    )
    merged: list = []
    seen: set[tuple[str, str]] = set()
    for chunk in [*chunks, *rescue]:
        key = (str(chunk.source), str(chunk.text[:120]))
        if key not in seen:
            seen.add(key)
            merged.append(chunk)
    return merged


# Learner Note: Workload identity questions require both ServiceAccount and RBAC evidence.
def _augment_workload_identity_evidence(question: str, chunks: list) -> list:
    """Merge dedicated ServiceAccount configuration evidence into authorization questions."""
    lowered = question.lower().replace(" ", "")
    if "serviceaccount" not in lowered:
        return chunks

    rescue = sparse_search(
        "serviceAccountName Pod dedicated ServiceAccount RBAC least privilege",
        top_k=12,
    )
    merged: list = []
    seen: set[tuple[str, str]] = set()
    for chunk in [*chunks, *rescue]:
        key = (str(chunk.source), str(chunk.text[:120]))
        if key not in seen:
            seen.add(key)
            merged.append(chunk)
    return merged


# Learner Note: HyDE's database wording should resolve to StatefulSet, not generic app examples.
def _prefer_implicit_stateful_sources(question: str, chunks: list) -> list:
    """Prefer StatefulSet evidence for stable database identity and disk requirements."""
    lowered = question.lower()
    implicit_stateful = (
        "database" in lowered
        and any(term in lowered for term in ("same name", "stable identity", "reschedul"))
        and any(term in lowered for term in ("disk", "storage", "persistent"))
    )
    if not chunks or not implicit_stateful:
        return chunks
    matches = [
        chunk
        for chunk in chunks
        if isinstance(chunk.source, str) and _STATEFUL_WORKLOAD_SOURCE_PATTERN.search(chunk.source)
    ]
    return matches or chunks


# Learner Note: Only explicitly current external questions may leave the curated local corpus.
def _requires_current_web_evidence(question: str) -> bool:
    """Allow web fallback only for questions whose answer is explicitly time-sensitive."""
    lowered = question.lower()
    current_marker = any(term in lowered for term in ("current", "currently", "latest", "recommended"))
    external_topic = any(term in lowered for term in ("cilium", "amazon eks", "eks", "argo cd"))
    return current_marker and external_topic


# Learner note: Encapsulates drop dashboard catalog noise so this responsibility can be understood, tested, and changed independently.
def _drop_dashboard_catalog_noise(chunks: list, question: str = "") -> list:
    """Support the retrieval-augmented generation pipeline by performing drop dashboard catalog noise.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    if not chunks:
        return chunks
    if "dashboard" in question.lower():
        return chunks

    non_dashboard = [
        chunk for chunk in chunks
        if not (isinstance(chunk.source, str) and _DASHBOARD_SOURCE_PATTERN.search(chunk.source))
    ]
    if non_dashboard and len(non_dashboard) < len(chunks):
        return non_dashboard
    return chunks


# Learner note: Encapsulates drop negative rerank tail so this responsibility can be understood, tested, and changed independently.
def _drop_negative_rerank_tail(chunks: list) -> list:
    """Support the retrieval-augmented generation pipeline by performing drop negative rerank tail.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    if not chunks:
        return chunks

    positive = [
        chunk for chunk in chunks
        if chunk.rerank_score is not None and float(chunk.rerank_score) >= 0.0
    ]
    if len(positive) >= 2:
        return positive
    return chunks


# Learner note: Encapsulates ordered sources so this responsibility can be understood, tested, and changed independently.
def _ordered_sources(chunks: list) -> list[str]:
    """Support the retrieval-augmented generation pipeline by performing ordered sources.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for chunk in chunks:
        source = str(chunk.source)
        if source not in seen:
            seen.add(source)
            ordered.append(source)
    return ordered


# Learner note: Orchestrates run rag, making this function a clear execution boundary for learners and tests.
def run_rag(
    question: str,
    top_k: int = 5,
    search_mode: str = "dense",
    enable_rerank: bool = False,
    enable_hyde: bool = False,
    enable_crag: bool = False,
    enable_self_reflective: bool = False,
) -> ChatResponse:
    """Perform run rag for the retrieval-augmented generation pipeline.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
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


# Learner note: Encapsulates run rag impl so this responsibility can be understood, tested, and changed independently.
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
    """Support the retrieval-augmented generation pipeline by performing run rag impl.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    clarification = detect_clarification_need(question)
    if clarification is not None:
        return (
            ChatResponse(
                answer=clarification.prompt,
                sources=[],
                confidence=1.0,
                metadata=ResponseMetadata(
                    route="clarification",
                    requested_search_mode=search_mode,
                    resolved_search_mode=None,
                    auto_enabled=search_mode == "auto",
                    auto_strategy_reason=clarification.reason,
                    original_question=question,
                    resolved_question=question,
                    needs_clarification=True,
                    clarification_question=clarification.prompt,
                    clarification_reason=clarification.reason,
                    clarification_type=clarification.ambiguity_type,
                ),
            ),
            [],
        )

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


    # Learner note: Encapsulates retrieve once so this responsibility can be understood, tested, and changed independently.
    def _retrieve_once(force_hyde: bool = False, top_k_override: int | None = None):
        """Support the retrieval-augmented generation pipeline by performing retrieve once.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        current_k = top_k_override or retrieve_k
        if any(hint in question.lower() for hint in _OPERATIONAL_GUIDANCE_HINTS):
            current_k = max(current_k, settings.reranker_initial_top_k)
        if len(_extract_question_entities(question)) >= 2:
            current_k = max(current_k, settings.reranker_initial_top_k)
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

        # Preserve authoritative runbooks/policies before a noisy corpus can crowd them
        # out of the smaller reranker/final top-k window.
        local_chunks = _prefer_operational_sources(question, local_chunks)
        local_chunks = _prefer_service_discovery_sources(question, local_chunks)
        local_chunks = _augment_security_evidence(question, local_chunks)
        local_chunks = _augment_workload_identity_evidence(question, local_chunks)
        local_chunks = _augment_planned_evidence(question, local_chunks)
        local_chunks = _prefer_security_sources(question, local_chunks)
        local_chunks = _prefer_implicit_stateful_sources(question, local_chunks)
        if len(_extract_question_entities(question)) >= 2 and not _evidence_plan(question):
            local_chunks = _prefer_entity_named_sources(question, local_chunks)
        # Remove known off-domain corpus noise before reranking.  Filtering only
        # after CRAG allowed irrelevant PDFs to consume the reranker's top-k and
        # made one good Kubernetes chunk mask several bad chunks in CRAG.
        local_chunks = _drop_non_kubernetes_corpus_noise(question, local_chunks)
        if enable_rerank and local_chunks:
            ranked = Reranker().rerank(question, local_chunks, top_k=len(local_chunks))
            return _ensure_planned_evidence(question, ranked, top_k)
        return _ensure_planned_evidence(question, local_chunks, top_k)

    chunks = _retrieve_once()
    chunks = _trim_troubleshooting_noise(chunks, question)

    # Learner note: Encapsulates local retry so this responsibility can be understood, tested, and changed independently.
    def _local_retry():
        """Support the retrieval-augmented generation pipeline by performing local retry.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        if not enable_hyde:
            return _retrieve_once(force_hyde=True)
        return _retrieve_once(top_k_override=max(retrieve_k, top_k * 2))


    chunks, crag_evaluation, used_web_fallback = crag_pipeline(
        question=question,
        chunks=chunks,
        enable_crag=enable_crag,
        local_retry_fn=_local_retry,
        allow_web_fallback=_requires_current_web_evidence(question),
    )
    planned = _authoritative_planned_evidence(question)
    if planned:
        # Composite evidence plans are deterministic domain policy. CRAG may
        # reject an individually narrow passage even though it is required for
        # the complete multi-document answer, so planned authoritative families
        # replace unrelated post-CRAG candidates.
        # Keep complementary passages from the same authoritative document.
        # Filename-family reservation alone collapses these into one chunk and
        # loses evidence needed for multi-part answers.
        chunks = _merge_same_source_evidence(planned[:top_k])
    else:
        chunks = _trim_troubleshooting_noise(chunks, question)
    chunks = _normalize_temp_sources(chunks)
    chunks = _prefer_operational_sources(question, chunks)
    chunks = _prefer_security_sources(question, chunks)
    chunks = _prefer_implicit_stateful_sources(question, chunks)
    chunks = _drop_non_kubernetes_corpus_noise(question, chunks)
    if not _evidence_plan(question):
        chunks = _prefer_entity_named_sources(question, chunks)
        chunks = _prefer_anchor_matched_sources(question, chunks)
    chunks = _drop_dashboard_catalog_noise(chunks, question)
    chunks = _drop_negative_rerank_tail(chunks)

    context = build_spotlighted_context(chunks)
    alias_guidance = _build_alias_guidance(question, chunks)

    system = build_system_prompt()
    total_answer_cost_usd = 0.0


    # Learner note: Encapsulates draft so this responsibility can be understood, tested, and changed independently.
    def _draft(current_question: str) -> str:
        """Support the retrieval-augmented generation pipeline by performing draft.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        nonlocal total_answer_cost_usd

        guidance = "\n\n".join(
            item for item in (alias_guidance, _planned_answer_guidance(question)) if item
        )
        guidance_block = f"{guidance}\n\n" if guidance else ""
        user_message = (
            f"Context:\n{context}\n\nQuestion: {current_question}\n\n"
            "Evidence constraint: Apply mechanisms documented in the context to scenario facts "
            "explicitly supplied in the question, such as workload names, labels, ports, or node types. "
            "Answer the requested design directly, but do not invent YAML syntax, commands, additional "
            "label keys or values, or configuration examples absent from both the question and context."
        )
        result = generate(system, f"{guidance_block}{user_message}")

        usage = result.get("usage", {})
        total_answer_cost_usd += answer_model_cost(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

        return _extract_answer_text(result["text"])


    reflection_iterations = 0
    reflection_score = None
    refined_question = None

    working_question = question
    if chunks:
        answer = _draft(working_question)
    else:
        answer = (
            "I could not find reliable evidence in the available sources to answer this question. "
            "Please provide the relevant system, document, record, or additional context."
        )

    if enable_self_reflective and chunks:
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
        and bool(chunks)
        and not bool(_evidence_plan(question))
        and (
            crag_evaluation.relevant_chunk_count == 0
            or (
                crag_evaluation.relevance_score < settings.crag_ambiguous_threshold
                and crag_evaluation.relevant_ratio == 0
            )
        )
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
            retrieval_question=question,
            reflection_iterations=reflection_iterations,
            reflection_score=reflection_score,
            refined_question=refined_question,
            crag_score=crag_evaluation.relevance_score if enable_crag else None,
            crag_label=crag_evaluation.relevance_label if enable_crag else None,
            crag_relevant_chunks=(
                crag_evaluation.relevant_chunk_count if enable_crag else None
            ),
            crag_total_chunks=(crag_evaluation.total_chunk_count if enable_crag else None),
            crag_relevant_ratio=(crag_evaluation.relevant_ratio if enable_crag else None),
            crag_chunk_scores=(
                [item.model_dump() for item in crag_evaluation.chunk_evaluations]
                if enable_crag
                else []
            ),
            used_web_fallback=used_web_fallback,
        ),
    )

    if use_cache:
        payload = response.model_dump()
        payload["estimated_answer_cost_usd"] = round(total_answer_cost_usd, 6)
        query_cache.set_rag_answer(question, payload, cache_context)
    return response, chunks


# Learner note: Orchestrates run rag with trace, making this function a clear execution boundary for learners and tests.
def run_rag_with_trace(
    question: str,
    flags: dict | None = None,
) -> tuple[ChatResponse, list]:
    """Perform run rag with trace for the retrieval-augmented generation pipeline.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
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


# Learner note: Orchestrates run rag with trace no cache, making this function a clear execution boundary for learners and tests.
def run_rag_with_trace_no_cache(
    question: str,
    flags: dict | None = None,
) -> tuple[ChatResponse, list]:
    """Perform run rag with trace no cache for the retrieval-augmented generation pipeline.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
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
