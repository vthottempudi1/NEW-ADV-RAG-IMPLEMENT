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
)
_SUBJECT_PATTERN = re.compile(r"\b(" + "|".join(re.escape(item) for item in _KNOWN_SUBJECTS) + r")s?\b", re.IGNORECASE)


def _normalize_subject(subject: str) -> str:
    lowered = subject.lower()
    for item in _KNOWN_SUBJECTS:
        if item.lower() == lowered or f"{item.lower()}s" == lowered:
            return item
    return subject


def _extract_subjects(text: str) -> list[str]:
    if not text:
        return []
    seen: list[str] = []
    for match in _SUBJECT_PATTERN.findall(text):
        subject = _normalize_subject(match)
        if subject not in seen:
            seen.append(subject)
    return seen


def _looks_like_follow_up(question: str) -> bool:
    lowered = question.lower()
    return any(marker in lowered for marker in _FOLLOW_UP_MARKERS)


def _last_turn_subjects(conversation_context: Iterable[dict] | None) -> tuple[list[str], list[str]]:
    turns = list(conversation_context or [])
    if not turns:
        return [], []
    last_turn = turns[-1] or {}
    prior_question = str(last_turn.get("question", "") or "")
    prior_answer = str(last_turn.get("answer", "") or "")
    return _extract_subjects(prior_question), _extract_subjects(prior_answer)


def _resolve_follow_up_subject(question: str, conversation_context: Iterable[dict] | None) -> str | None:
    prior_question_subjects, prior_answer_subjects = _last_turn_subjects(conversation_context)
    available = prior_answer_subjects or prior_question_subjects
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

    rewritten = cleaned
    replacements = (
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

    return cleaned, subject
