import re
from typing import Iterable

_KNOWN_SUBJECTS = (
    "ConfigMap",
    "Secret",
    "Pod",
    "Deployment",
    "StatefulSet",
    "DaemonSet",
    "Service",
    "Ingress",
    "Namespace",
    "ServiceAccount",
    "RBAC",
    "Incident Response Runbook",
    "On-Call Escalation Policy",
)
_FOLLOW_UP_MARKERS = (
    "which one",
    "that same",
    "the same",
    "the non-sensitive one",
    "the one that is meant for confidential data",
    "the confidential one",
    "the sensitive one",
    "the other one",
    "would you still use",
    "would you use",
    "if i mounted it",
    "if i exposed it",
    "is it actually",
    "what does it say",
    "what should we do first",
    "what should the team do",
    "what is the first step",
    "how does that help",
    "what happens if",
    "what happens after",
    "after that",
)
_SUBJECT_PATTERN = re.compile(r"\b(" + "|".join(re.escape(item) for item in _KNOWN_SUBJECTS) + r")s?\b", re.IGNORECASE)
_SUBJECT_ALIASES = (
    (
        re.compile(
            r"\b(?:p[0-4][-_ ]+)?(?:on[-_ ]call[-_ ]+)?escalation[-_ ]policy\b",
            re.IGNORECASE,
        ),
        "On-Call Escalation Policy",
    ),
    (
        re.compile(
            r"\bincident(?:[-_ ]response)?[-_ ]runbook\b",
            re.IGNORECASE,
        ),
        "Incident Response Runbook",
    ),
)
_SEVERITY_PATTERN = re.compile(r"\bP[0-4]\b", re.IGNORECASE)
_CONTEXT_PRONOUN_PATTERN = re.compile(
    r"\b(it|that|this|they|them|those)\b",
    re.IGNORECASE,
)


def _normalize_subject(subject: str) -> str:
    """Map a matched subject string (any case, singular or plural) to its canonical
    form from _KNOWN_SUBJECTS. Returns the input unchanged if no known subject matches."""
    lowered = subject.lower()
    for item in _KNOWN_SUBJECTS:
        if item.lower() == lowered or f"{item.lower()}s" == lowered:
            return item
    return subject


def _extract_subjects(text: str) -> list[str]:
    """Find every known Kubernetes/ops subject mentioned in text and return their
    canonical names in first-seen order, de-duplicated. Returns an empty list for
    falsy input."""
    if not text:
        return []
    seen: list[str] = []
    for pattern, subject in _SUBJECT_ALIASES:
        if pattern.search(text) and subject not in seen:
            seen.append(subject)
    for match in _SUBJECT_PATTERN.findall(text):
        subject = _normalize_subject(match)
        if subject not in seen:
            seen.append(subject)
    return seen


def _looks_like_follow_up(question: str) -> bool:
    """Return True if question contains any of the known follow-up phrases (e.g.
    "which one", "the same", "what does it say") that signal it depends on
    context from a prior conversation turn."""
    lowered = question.lower()
    return any(marker in lowered for marker in _FOLLOW_UP_MARKERS) or bool(
        _CONTEXT_PRONOUN_PATTERN.search(question)
    )


def _last_turn_severity(conversation_context: Iterable[dict] | None) -> str | None:
    """Return the most recent P0-P4 severity mentioned in conversation history."""
    turns = list(conversation_context or [])
    for turn in reversed(turns):
        current = turn or {}
        combined = " ".join(
            (
                str(current.get("question", "") or ""),
                str(current.get("answer", "") or ""),
            )
        )
        match = _SEVERITY_PATTERN.search(combined)
        if match:
            return match.group(0).upper()
    return None


def _last_turn_subjects(conversation_context: Iterable[dict] | None) -> tuple[list[str], list[str]]:
    """Extract subjects from the nearest turn that preserves conversation context.

    Source names are included because a successful follow-up may omit the
    document name from both its question and answer while still citing the same
    authoritative document. If the latest turn has no recognizable subject,
    older turns are scanned newest-first within the bounded context window.
    """
    turns = list(conversation_context or [])
    if not turns:
        return [], []
    for turn in reversed(turns):
        current = turn or {}
        prior_question = str(current.get("question", "") or "")
        prior_answer = str(current.get("answer", "") or "")
        prior_sources = " ".join(
            str(source) for source in (current.get("sources", []) or [])
        )
        question_subjects = _extract_subjects(prior_question)
        evidence_subjects = _extract_subjects(
            f"{prior_answer} {prior_sources}"
        )
        if question_subjects or evidence_subjects:
            return question_subjects, evidence_subjects
    return [], []


def _resolve_follow_up_subject(question: str, conversation_context: Iterable[dict] | None) -> str | None:
    """Infer which prior-turn subject a follow-up question ("that one", "it") refers to.

    Checks, in order: an explicit "non-sensitive"/"confidential" hint resolved
    against ConfigMap/Secret subjects seen in the prior turn; whether exactly one
    candidate subject is available (unambiguous); and phrases like "same object"
    or "if I mounted/exposed it" that imply the single most recent subject.
    Returns None if the reference cannot be resolved to a single subject.
    """
    prior_question_subjects, prior_answer_subjects = _last_turn_subjects(conversation_context)
    explicit_operational_subjects = list(
        dict.fromkeys(
            subject
            for subject in prior_question_subjects + prior_answer_subjects
            if subject
            in {"Incident Response Runbook", "On-Call Escalation Policy"}
        )
    )
    available = list(
        dict.fromkeys(
            explicit_operational_subjects
            or prior_answer_subjects
            or prior_question_subjects
        )
    )
    lowered = question.lower()

    if not available:
        return None

    if "non-sensitive" in lowered or "non sensitive" in lowered:
        if "ConfigMap" in prior_question_subjects or "ConfigMap" in prior_answer_subjects:
            return "ConfigMap"
    if any(phrase in lowered for phrase in ("confidential", "sensitive data", "database password", "encrypted by default")):
        if "Secret" in prior_question_subjects or "Secret" in prior_answer_subjects:
            return "Secret"

    if len(available) == 1:
        return available[0]

    if "same object" in lowered or lowered.startswith("if i mounted it") or lowered.startswith("if i exposed it"):
        return available[0]

    return None


def rewrite_follow_up_question(question: str, conversation_context: Iterable[dict] | None = None) -> tuple[str, str | None]:
    """Rewrite an ambiguous follow-up question into a self-contained one using conversation history.

    If the question doesn't look like a follow-up (per _looks_like_follow_up), it
    is returned unchanged with a None subject. Otherwise this resolves which
    subject ("that", "it", "which one") the question refers to from the prior
    turn and substitutes it into known phrase patterns (e.g. "What does it say"
    -> "What does the Secret say"). A special case detects "after that ...
    mitigation fail[s]" and rewrites straight to an escalation-policy question
    regardless of the generic replacement table. If no known phrase matches but a
    subject was resolved, the original question is returned paired with that
    subject so callers can still use it for retrieval context.

    Returns a (question_text, resolved_subject_or_None) tuple.
    """
    cleaned = " ".join((question or "").split())
    if not cleaned or not _looks_like_follow_up(cleaned):
        return cleaned, None

    prior_question_subjects, prior_answer_subjects = _last_turn_subjects(conversation_context)
    lowered = cleaned.lower()
    if lowered.startswith("which one") and len(prior_question_subjects) >= 2:
        pair = " or ".join(prior_question_subjects[:2])
        return cleaned.replace("Which one", f"Which one, {pair},", 1), pair

    subject = _resolve_follow_up_subject(cleaned, conversation_context)
    if not subject:
        if "same resource" in lowered and "Service" in prior_answer_subjects:
            subject = "Service"
        else:
            return cleaned, None

    # A failed mitigation changes the evidence need from runbook triage to the
    # authoritative escalation policy. Make that semantic hand-off explicit so
    # retrieval does not guess from the pronoun "that" or fall back to the web.
    if "after that" in lowered and "mitigation fail" in lowered:
        return (
            "According to the On-Call Escalation Policy, what escalation steps "
            "are required when incident mitigation fails?",
            "On-Call Escalation Policy",
        )

    rewritten = cleaned
    replacements = (
        ("What does it say", f"What does the {subject} say"),
        ("What should we do first", f"According to the {subject}, what should we do first"),
        ("What is the first step", f"According to the {subject}, what is the first step"),
        ("How does that help", f"How does the {subject} help"),
        ("For the non-sensitive one,", f"For the {subject},"),
        ("For the non-sensitive one", f"For the {subject}"),
        ("For the one that is meant for confidential data,", f"For the {subject},"),
        ("For the one that is meant for confidential data", f"For the {subject}"),
        ("Would you use that same object", f"Would you use a {subject}"),
        ("Would you still use that same object", f"Would you still use a {subject}"),
        ("If I mounted it", f"If I mounted a {subject}"),
        ("If I exposed it", f"If I exposed a {subject}"),
        ("is it actually", f"is a {subject} actually"),
        ("that same resource", f"a {subject}"),
    )
    for needle, replacement in replacements:
        if needle in rewritten:
            rewritten = rewritten.replace(needle, replacement, 1)
            return rewritten, subject

    if subject in {"Incident Response Runbook", "On-Call Escalation Policy"} and lowered.startswith(
        ("what should", "what happens", "what does the team")
    ):
        severity = _last_turn_severity(conversation_context)
        qualifier = f" for {severity} incidents" if severity else ""
        return f"According to the {subject}{qualifier}, {cleaned}", subject

    if _CONTEXT_PRONOUN_PATTERN.search(cleaned):
        severity = _last_turn_severity(conversation_context)
        qualifier = f" for {severity} incidents" if severity else ""
        return f"According to the {subject}{qualifier}, {cleaned}", subject

    return cleaned, subject
