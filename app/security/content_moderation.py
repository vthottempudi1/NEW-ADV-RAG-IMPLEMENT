import re

_EMAIL_RE = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d[\d\-\s]{7,}\d)\b")


# Learner note: Encapsulates moderate and redact so this responsibility can be understood, tested, and changed independently.
def moderate_and_redact(text: str) -> tuple[bool, str, str]:
    """Perform moderate and redact for the application security boundary.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    cleaned = text.strip()
    if not cleaned:
        return False, cleaned, "empty_input"

    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", cleaned)
    redacted = _PHONE_RE.sub("[REDACTED_PHONE]", redacted)

    return True, redacted, "ok"
