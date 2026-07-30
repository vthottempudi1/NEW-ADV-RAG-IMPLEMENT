import re

_BLOCKED_OUTPUT_PATTERNS = [
    r"(?i)system prompt",
    r"(?i)hidden instructions",
    r"(?i)ignore previous instructions",
    r"(?i)developer message",
]


def validate_output_safe(text: str) -> tuple[bool, str]:
    """Check generated `text` for leaked system-prompt or instruction-override content.

    Rejects empty output and any text matching a blocked pattern (e.g. mentions
    of "system prompt", "hidden instructions", "developer message", or attempts
    to have the model ignore prior instructions). Returns a `(is_safe, reason)`
    tuple, where `reason` is "empty_output", "unsafe_output_detected", or "ok".
    """
    cleaned = text.strip()
    if not cleaned:
        return False, "empty_output"

    for pattern in _BLOCKED_OUTPUT_PATTERNS:
        if re.search(pattern, cleaned):
            return False, "unsafe_output_detected"

    return True, "ok"
