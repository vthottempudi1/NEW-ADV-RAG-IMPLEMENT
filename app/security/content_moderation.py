import re

_EMAIL_RE = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d[\d\-\s]{7,}\d)\b")


def moderate_and_redact(text: str) -> tuple[bool, str, str]:
    """Strip whitespace from `text` and mask PII before it flows further into the pipeline.

    Rejects empty input outright. Otherwise replaces email addresses with
    "[REDACTED_EMAIL]" and phone-number-like sequences with "[REDACTED_PHONE]".

    Returns a `(is_allowed, redacted_text, reason)` tuple, where `reason` is
    "empty_input" on rejection or "ok" on success.
    """
    cleaned = text.strip()
    if not cleaned:
        return False, cleaned, "empty_input"

    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", cleaned)
    redacted = _PHONE_RE.sub("[REDACTED_PHONE]", redacted)

    return True, redacted, "ok"
