import re


_EMAIL_RE = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d[\d\-\s]{7,}\d)\b")


def moderate_and_redact(text: str) -> tuple[bool, str, str]:
    cleaned = text.strip()
    if not cleaned:
        return False, cleaned, "empty_input"

    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", cleaned)
    redacted = _PHONE_RE.sub("[REDACTED_PHONE]", redacted)

    return True, redacted, "ok"