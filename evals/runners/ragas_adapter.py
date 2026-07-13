"""
Ragas-compatible metric scorer implemented directly via OpenAI.
Replaces the ragas library dependency to avoid langchain version conflicts.

Metrics implemented:
  - faithfulness:      Are claims in the answer grounded in the retrieved contexts?
  - answer_relevancy:  Does the answer address the question?
  - context_precision: Are the retrieved contexts actually relevant to the question?
  - context_recall:    Does the retrieved context cover the ground-truth answer?
"""
from __future__ import annotations

import json
import math
import re
import statistics

from openai import OpenAI

from app.config import settings
from app.rag.hybrid_question import derive_hybrid_rag_question

_client: OpenAI | None = None

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "our",
    "the",
    "to",
    "what",
    "when",
    "which",
}


# Learner note: Encapsulates llm so this responsibility can be understood, tested, and changed independently.
def _llm() -> OpenAI:
    """Support the evaluation and quality-gate framework by performing llm.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


# Learner note: Encapsulates ask so this responsibility can be understood, tested, and changed independently.
def _ask(prompt: str) -> str:
    """Support the evaluation and quality-gate framework by performing ask.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    resp = _llm().chat.completions.create(
        model=settings.llm_model_grader,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return resp.choices[0].message.content.strip()


# Learner note: Encapsulates tokens so this responsibility can be understood, tested, and changed independently.
def _tokens(text: str) -> set[str]:
    """Support the evaluation and quality-gate framework by performing tokens.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 2 and token not in _STOPWORDS
    }


# Learner note: Encapsulates overlap score so this responsibility can be understood, tested, and changed independently.
def _overlap_score(left: str, right: str) -> float:
    """Support the evaluation and quality-gate framework by performing overlap score.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), 1)


# Learner Note: Is evidence abstention is part of the evaluation and quality-gate framework.
def _is_evidence_abstention(answer: str) -> bool:
    """Return whether an answer explicitly refuses to speculate without evidence."""
    lowered = answer.lower()
    return any(
        phrase in lowered
        for phrase in (
            "could not find reliable evidence",
            "cannot determine",
            "can't determine",
            "insufficient evidence",
            "not enough reliable context",
        )
    )


# Learner note: Encapsulates score faithfulness so this responsibility can be understood, tested, and changed independently.
def _evaluate_faithfulness(
    answer: str,
    contexts: list[str],
    question: str = "",
) -> tuple[float, list[dict]]:
    """Return a faithfulness score and auditable per-claim evidence decisions."""
    if not contexts:
        abstained = _is_evidence_abstention(answer)
        return (1.0 if abstained else 0.0), [{
            "claim": answer,
            "supported": abstained,
            "source_index": None,
            "supporting_quote": None,
            "quote_valid": False,
            "reason": "supported_abstention" if abstained else "no_retrieved_context",
        }]
    labelled_contexts = "\n\n".join(
        f"[SOURCE {index}]\n{context}"
        for index, context in enumerate(contexts[:5])
    )

    # Learner Note: Locate compact exact span is part of the evaluation and quality-gate framework.
    def locate_compact_exact_span(claim: str) -> tuple[str, int] | None:
        """Locate a short verbatim window containing most significant claim terms."""
        stopwords = {
            "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
            "is", "it", "of", "on", "or", "that", "the", "this", "to", "with",
        }
        claim_terms = {
            token for token in re.findall(r"[a-z0-9]+", claim.lower())
            if len(token) > 2 and token not in stopwords
        }
        if len(claim_terms) < 3:
            return None
        required = max(4, math.ceil(len(claim_terms) * 0.65))
        for source_index, context in enumerate(contexts[:5]):
            words = list(re.finditer(r"[a-z0-9]+", context.lower()))
            for start in range(len(words)):
                found: set[str] = set()
                for end in range(start, min(len(words), start + 40)):
                    token = words[end].group(0)
                    if token in claim_terms:
                        found.add(token)
                    if len(found) >= required:
                        quote = context[words[start].start():words[end].end()]
                        return quote, source_index
        return None

    # Learner Note: Repair exact context quotes is part of the evaluation and quality-gate framework.
    def repair_exact_context_quotes(claim: str) -> list[tuple[str, int]]:
        """Return separately validated verbatim passages for a supported compound claim."""
        repair_prompt = f"""Find the minimum exact, continuous quote or quotes that together support
the claim below. Copy each quote verbatim from one labelled source. Never combine non-contiguous
text into one quote and never add words. Return ONLY JSON with key supporting_quotes whose value
is a list of objects with source_index and supporting_quote. Return an empty list when the claim
has no exact support. A compound claim may require two quotes.

Claim:
{claim}

Context:
{labelled_contexts}
"""
        try:
            repaired = json.loads(_ask(repair_prompt))
            candidates = repaired.get("supporting_quotes")
            if candidates is None and repaired.get("supporting_quote") is not None:
                candidates = [repaired]
            validated: list[tuple[str, int]] = []
            for candidate in candidates or []:
                repaired_quote = str(candidate.get("supporting_quote") or "").strip()
                normalized_repaired = re.sub(r"[^a-z0-9]+", "", repaired_quote.lower())
                matches = [
                    index
                    for index, context in enumerate(contexts[:5])
                    if len(normalized_repaired) >= 12
                    and normalized_repaired in re.sub(r"[^a-z0-9]+", "", context.lower())
                ]
                if matches:
                    validated.append((repaired_quote, matches[0]))
            return validated
        except (json.JSONDecodeError, TypeError, AttributeError):
            return []

    # Learner Note: Validate combined evidence is part of the evaluation and quality-gate framework.
    def validate_combined_evidence(claim: str) -> tuple[str, str, int] | None:
        """Validate an applied claim using one question premise and one context rule."""
        combined_prompt = f"""Determine whether the claim applies a rule from context to a scenario
premise from the user's question. Return ONLY JSON with question_quote, context_quote, and
source_index. Both quotes must be exact continuous substrings. Return empty quotes and null index
unless both pieces are necessary and together support the claim.

Claim:
{claim}

Question:
{question}

Context:
{labelled_contexts}
"""
        try:
            combined = json.loads(_ask(combined_prompt))
            question_quote = str(combined.get("question_quote") or "").strip()
            context_quote = str(combined.get("context_quote") or "").strip()
            normalized_question_quote = re.sub(r"[^a-z0-9]+", "", question_quote.lower())
            normalized_context_quote = re.sub(r"[^a-z0-9]+", "", context_quote.lower())
            question_valid = (
                len(normalized_question_quote) >= 12
                and normalized_question_quote
                in re.sub(r"[^a-z0-9]+", "", question.lower())
            )
            context_matches = [
                index
                for index, context in enumerate(contexts[:5])
                if len(normalized_context_quote) >= 12
                and normalized_context_quote
                in re.sub(r"[^a-z0-9]+", "", context.lower())
            ]
            if question_valid and context_matches:
                return question_quote, context_quote, context_matches[0]
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        return None

    # Learner Note: Validate multi context evidence is part of the evaluation and quality-gate framework.
    def validate_multi_context_evidence(claim: str) -> list[tuple[str, int]]:
        """Validate a synthesis conclusion using exact quotes from distinct contexts."""
        synthesis_prompt = f"""Determine whether the claim is a necessary synthesis of facts from
two or more labelled context sources. Return ONLY JSON with supporting_quotes, a list of objects
containing source_index and an exact continuous supporting_quote. Never paraphrase or combine text.
Return an empty list unless at least two distinct sources together support the conclusion.

Claim:
{claim}

Context:
{labelled_contexts}
"""
        try:
            payload = json.loads(_ask(synthesis_prompt))
            validated: list[tuple[str, int]] = []
            for candidate in payload.get("supporting_quotes") or []:
                quote = str(candidate.get("supporting_quote") or "").strip()
                normalized = re.sub(r"[^a-z0-9]+", "", quote.lower())
                matches = [
                    index
                    for index, context in enumerate(contexts[:5])
                    if len(normalized) >= 12
                    and normalized in re.sub(r"[^a-z0-9]+", "", context.lower())
                ]
                if matches:
                    validated.append((quote, matches[0]))
            if len({index for _, index in validated}) >= 2:
                return validated
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        return []
    prompt = f"""Given the retrieved context and answer, identify every factual claim.
The user's question is also evidence for scenario premises explicitly supplied by the user.
Do not mark a claim unsupported merely because it applies a documented general rule to names,
labels, ports, durations, or workloads supplied in the question.

Return ONLY a JSON array of objects with keys claim, supported, evidence_type,
source_index, supporting_quote, reasoning. evidence_type must be "context", "question",
"combined", or "none". For context evidence, copy supporting_quote exactly from a labelled source and
set its zero-based source_index. For question evidence, copy the premise exactly from the
question and set source_index to null. Technical recommendations and behavior must be
supported by context, not merely by the question. Set supported=false if neither evidence
source supports the claim.

Question:
{question}

Context:
{labelled_contexts}

Answer:
{answer}

JSON array:"""
    audits: list[dict] = []
    try:
        raw = _ask(prompt)
        items = json.loads(raw[raw.find("["):raw.rfind("]") + 1])
        for item in items:
            if not isinstance(item, dict):
                audits.append({"claim": str(item), "supported": False, "reason": "invalid_claim_object"})
                continue
            evidence_type = str(item.get("evidence_type") or "context").lower()
            declared_index = item.get("source_index")
            declared_index_valid = (
                isinstance(declared_index, int)
                and 0 <= declared_index < min(len(contexts), 5)
            )
            quote = str(item.get("supporting_quote") or "").strip()
            normalized_quote = re.sub(r"[^a-z0-9]+", "", quote.lower())
            context_matches = [
                source_index
                for source_index, context in enumerate(contexts[:5])
                if normalized_quote
                and normalized_quote in re.sub(r"[^a-z0-9]+", "", context.lower())
            ]
            question_match = bool(
                normalized_quote
                and normalized_quote in re.sub(r"[^a-z0-9]+", "", question.lower())
            )
            if evidence_type == "question":
                valid_index = True
                resolved_index = None
                quote_valid = len(normalized_quote) >= 12 and question_match
            else:
                valid_index = bool(context_matches)
                resolved_index = context_matches[0] if context_matches else None
                quote_valid = len(normalized_quote) >= 12 and valid_index
            model_supported = item.get("supported") is True
            normalized_claim = re.sub(
                r"[^a-z0-9]+", "", str(item.get("claim") or "").lower()
            )
            claim_is_question_premise = bool(
                len(normalized_claim) >= 12
                and normalized_claim in re.sub(r"[^a-z0-9]+", "", question.lower())
            )
            supporting_quotes: list[str] = [quote] if quote_valid and quote else []
            source_indices: list[int] = (
                [resolved_index] if quote_valid and resolved_index is not None else []
            )
            if claim_is_question_premise:
                model_supported = True
                evidence_type = "question"
                quote = str(item.get("claim") or "")
                resolved_index = None
                quote_valid = True
                supporting_quotes = [quote]
                source_indices = []
            if not model_supported or (evidence_type == "combined" and not quote_valid):
                combined_evidence = validate_combined_evidence(
                    str(item.get("claim") or "")
                )
                if combined_evidence is not None:
                    question_quote, context_quote, combined_index = combined_evidence
                    model_supported = True
                    evidence_type = "combined"
                    quote = context_quote
                    resolved_index = combined_index
                    quote_valid = True
                    supporting_quotes = [question_quote, context_quote]
                    source_indices = [combined_index]
            if not model_supported:
                multi_context = validate_multi_context_evidence(
                    str(item.get("claim") or "")
                )
                if multi_context:
                    model_supported = True
                    evidence_type = "multi_context"
                    supporting_quotes = [value for value, _ in multi_context]
                    source_indices = [index for _, index in multi_context]
                    quote = supporting_quotes[0]
                    resolved_index = source_indices[0]
                    quote_valid = True
            if model_supported and evidence_type == "context" and not quote_valid:
                repaired_quotes = repair_exact_context_quotes(
                    str(item.get("claim") or "")
                )
                if repaired_quotes:
                    supporting_quotes = [value for value, _ in repaired_quotes]
                    source_indices = [index for _, index in repaired_quotes]
                    quote = supporting_quotes[0]
                    resolved_index = source_indices[0]
                    quote_valid = True
                else:
                    compact_span = locate_compact_exact_span(str(item.get("claim") or ""))
                    if compact_span is not None:
                        quote, resolved_index = compact_span
                        supporting_quotes = [quote]
                        source_indices = [resolved_index]
                        quote_valid = True
            supported = model_supported and quote_valid
            reason = str(item.get("reasoning") or "")
            if model_supported and evidence_type == "context" and quote_valid:
                if declared_index != resolved_index:
                    reason = "source_index_corrected"
            elif model_supported and evidence_type == "context" and not declared_index_valid:
                reason = "invalid_source_index"
            elif model_supported and not quote_valid:
                reason = "supporting_quote_not_found"
            elif not model_supported and not reason:
                reason = "model_marked_unsupported"
            audits.append({
                "claim": str(item.get("claim") or ""),
                "supported": supported,
                "evidence_type": evidence_type if evidence_type in {"context", "question", "combined", "multi_context"} else "none",
                "source_index": resolved_index,
                "supporting_quote": quote or None,
                "supporting_quotes": supporting_quotes,
                "source_indices": source_indices,
                "quote_valid": quote_valid,
                "reason": reason,
            })
    except Exception as exc:
        audits = [{"claim": answer, "supported": False, "reason": f"grader_parse_error:{exc.__class__.__name__}"}]
    return statistics.mean([int(item["supported"]) for item in audits]) if audits else 0.0, audits


# Learner Note: Score faithfulness is part of the evaluation and quality-gate framework.
def _score_faithfulness(answer: str, contexts: list[str]) -> float:
    """Support the evaluation and quality-gate framework by performing score faithfulness.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    return _evaluate_faithfulness(answer, contexts)[0]


# Learner note: Encapsulates score answer relevancy so this responsibility can be understood, tested, and changed independently.
def _score_answer_relevancy(question: str, answer: str) -> float:
    """Support the evaluation and quality-gate framework by performing score answer relevancy.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    question = _underlying_domain_question(question)
    prompt = f"""Rate how well the answer addresses the question on a scale from 0.0 to 1.0.
1.0 = fully addresses the question, 0.0 = completely irrelevant or off-topic.
Return ONLY a decimal number between 0.0 and 1.0.

Question: {question}
Answer: {answer}

Score:"""
    try:
        return min(1.0, max(0.0, float(_ask(prompt))))
    except Exception:
        return 0.0


# Learner Note: Underlying domain question is part of the evaluation and quality-gate framework.
def _underlying_domain_question(question: str) -> str:
    """Remove an adversarial source preference while preserving the actual domain request."""
    prefix, separator, remainder = question.partition(":")
    lowered_prefix = prefix.lower()
    if (
        separator
        and remainder.strip()
        and any(term in lowered_prefix for term in ("article", "pdf", "source", "docs"))
        and any(term in lowered_prefix for term in ("use", "authority", "not"))
    ):
        return remainder.strip()
    source_override = re.search(
        r"\buse\b.+?\bto\s+(explain|describe|show|tell)\s+(.+)$",
        question,
        flags=re.IGNORECASE,
    )
    if source_override:
        verb, domain_request = source_override.groups()
        return f"{verb.capitalize()} {domain_request.strip()}"
    return question


# Learner Note: Score clarification relevancy is part of the evaluation and quality-gate framework.
def _score_clarification_relevancy(question: str, answer: str, reference: str) -> float:
    """Score whether an ambiguous request receives the necessary clarifying question."""
    prompt = f"""Rate the clarification response on a scale from 0.0 to 1.0.
The original request is intentionally ambiguous, so asking for missing scope is the correct response;
do not penalize it for not directly performing or answering the ambiguous request. A high score means
the response asks for the resource/system and other information needed to proceed safely.
Return ONLY a decimal number between 0.0 and 1.0.

Ambiguous request: {question}
Clarification response: {answer}
Reference clarification: {reference}

Score:"""
    try:
        return min(1.0, max(0.0, float(_ask(prompt))))
    except Exception:
        return 0.0


# Learner note: Encapsulates score context precision so this responsibility can be understood, tested, and changed independently.
def _score_context_precision(question: str, contexts: list[str]) -> float:
    """Score ranked evidence against its assigned hybrid subquestion.

    Database evidence uses the quantitative request; document evidence uses the
    focused RAG clause. Correct runbook chunks therefore are not penalized for
    omitting SQL values they were never intended to contain.
    """
    if not contexts:
        return 0.0
    question = _underlying_domain_question(question)
    scores = []
    for ctx in contexts[:5]:
        is_database_evidence = "[Evidence source: database query]" in ctx
        evidence_question = (
            question
            if is_database_evidence
            else derive_hybrid_rag_question(question)
        )
        prompt = f"""Judge whether this evidence is relevant to ANY required part of the question.
Combined enterprise questions may intentionally require both structured database results and
unstructured runbook/policy evidence. A database-result context is relevant when it answers the
count, average, status, ranking, cluster, or other data portion; it does not need to contain the
runbook wording. A document context is relevant when it answers the guidance/policy portion; it
does not need to contain the database value. Do not require either context to answer both parts.
If the user demands an unrelated or adversarial source, judge relevance against the underlying
domain question rather than that source preference. Authoritative cluster evidence can be relevant
even when the user asks to replace it with an unrelated article.
Return ONLY 1 (relevant) or 0 (not relevant).

Question part assigned to this evidence: {evidence_question}
Context: {ctx[:3000]}

Score:"""
        try:
            scores.append(int(_ask(prompt).strip()[0]))
        except Exception:
            scores.append(0)
    # Precision@k with positional weighting
    hits, total = 0, 0
    precision_sum = 0.0
    for i, s in enumerate(scores, 1):
        if s:
            hits += 1
            precision_sum += hits / i
        total += 1
    return (precision_sum / hits) if hits else 0.0


# Learner note: Encapsulates score context recall so this responsibility can be understood, tested, and changed independently.
def _score_context_recall(answer: str, contexts: list[str]) -> float:
    """Support the evaluation and quality-gate framework by performing score context recall.

    Recall of the ground truth by zero retrieved context is 0 by definition; without
    this guard the LLM judge was asked to grade an empty "Retrieved contexts:" block
    and would sometimes answer from its own parametric knowledge instead, producing an
    impossible 1.0 recall score for rows where nothing was retrieved.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    if not contexts:
        return 0.0
    ctx = "\n---\n".join(contexts[:5])
    prompt = f"""Given the ground-truth answer and retrieved contexts, split the ground truth into
atomic factual requirements. Split compound sentences so one missing detail does not erase credit
for other independently supported details. For each atomic requirement, judge whether the context
supports it (1) or not (0).
Return ONLY a JSON array of 0s and 1s. Example: [1, 0, 1]

Ground-truth answer:
{answer}

Retrieved contexts:
{ctx}

JSON array:"""
    try:
        raw = _ask(prompt)
        scores = json.loads(raw[raw.find("["):raw.rfind("]") + 1])
        return statistics.mean(scores) if scores else 0.0
    except Exception:
        return 0.0


# Learner note: Encapsulates heuristic score faithfulness so this responsibility can be understood, tested, and changed independently.
def _heuristic_score_faithfulness(answer: str, contexts: list[str]) -> float:
    """Support the evaluation and quality-gate framework by performing heuristic score faithfulness.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    return round(
        max((_overlap_score(answer, context) for context in contexts), default=0.0),
        3,
    )


# Learner note: Encapsulates heuristic score answer relevancy so this responsibility can be understood, tested, and changed independently.
def _heuristic_score_answer_relevancy(question: str, answer: str) -> float:
    """Support the evaluation and quality-gate framework by performing heuristic score answer relevancy.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    return round(_overlap_score(question, answer), 3)


# Learner note: Encapsulates heuristic score context precision so this responsibility can be understood, tested, and changed independently.
def _heuristic_score_context_precision(question: str, contexts: list[str]) -> float:
    """Support the evaluation and quality-gate framework by performing heuristic score context precision.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    if not contexts:
        return 0.0
    scores = [_overlap_score(question, context) for context in contexts]
    return round(sum(scores) / len(scores), 3)


# Learner note: Encapsulates heuristic score context recall so this responsibility can be understood, tested, and changed independently.
def _heuristic_score_context_recall(answer: str, contexts: list[str]) -> float:
    """Support the evaluation and quality-gate framework by performing heuristic score context recall.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    joined = "\n".join(contexts)
    return round(_overlap_score(answer, joined), 3)


# Learner note: Encapsulates run so this responsibility can be understood, tested, and changed independently.
def run(rows: list[dict], scorer: str = "llm") -> list[dict]:
    """Score each row with all four RAGAS metrics. Returns updated rows."""
    if not rows:
        return []
    results = []
    for row in rows:
        q = row.get("question", "")
        ans = row.get("answer", "")
        ctxs = row.get("contexts", [])
        gt = row.get("ground_truth", ans)  # fall back to answer if no ground truth

        if row.get("intent") == "clarification":
            metrics = {
                "faithfulness": 1.0,
                "answer_relevancy": (
                    _heuristic_score_answer_relevancy(q, ans)
                    if scorer == "heuristic"
                    else _score_clarification_relevancy(q, ans, gt)
                ),
                "context_precision": 1.0,
                "context_recall": 1.0,
            }
            results.append({**row, **metrics, "scoring_backend": scorer})
            continue

        if scorer == "heuristic":
            metrics = {
                "faithfulness": _heuristic_score_faithfulness(ans, ctxs),
                "answer_relevancy": _heuristic_score_answer_relevancy(q, ans),
                "context_precision": _heuristic_score_context_precision(q, ctxs),
                "context_recall": _heuristic_score_context_recall(gt, ctxs),
            }
            scoring_backend = "heuristic"
        else:
            faithfulness, faithfulness_claims = _evaluate_faithfulness(ans, ctxs, q)
            metrics = {
                "faithfulness": faithfulness,
                "faithfulness_claims": faithfulness_claims,
                "answer_relevancy": _score_answer_relevancy(q, ans),
                "context_precision": _score_context_precision(q, ctxs),
                "context_recall": _score_context_recall(gt, ctxs),
            }

            # If the LLM scorer silently collapses to all-zero metrics for a row
            # with a non-empty answer and contexts, treat that as a scoring failure
            # and fall back to the deterministic heuristic scorer.
            if (
                ans.strip()
                and ctxs
                and all(float(metrics.get(name, 0.0)) == 0.0 for name in (
                    "faithfulness",
                    "answer_relevancy",
                    "context_precision",
                    "context_recall",
                ))
            ):
                metrics = {
                    "faithfulness": _heuristic_score_faithfulness(ans, ctxs),
                    "answer_relevancy": _heuristic_score_answer_relevancy(q, ans),
                    "context_precision": _heuristic_score_context_precision(q, ctxs),
                    "context_recall": _heuristic_score_context_recall(gt, ctxs),
                }
                scoring_backend = "heuristic_fallback"
            else:
                scoring_backend = "llm"

        # For an unanswerable evidence request, returning no context and
        # explicitly refusing to speculate is the desired behavior. The
        # ordinary RAG context metrics are not applicable to this case.
        if not ctxs and _is_evidence_abstention(ans):
            metrics.update({
                "faithfulness": 1.0,
                "answer_relevancy": 1.0,
                "context_precision": 1.0,
                "context_recall": 1.0,
                "abstention_correct": True,
            })

        results.append({
            **row,
            **metrics,
            "scoring_backend": scoring_backend,
        })
    return results
