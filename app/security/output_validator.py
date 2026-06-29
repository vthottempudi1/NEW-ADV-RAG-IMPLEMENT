import re


_BLOCKED_OUTPUT_PATTERNS = [
    r"(?i)system prompt",
    r"(?i)hidden instructions",
    r"(?i)ignore previous instructions",
    r"(?i)developer message",
]


def validate_output_safe(text: str) -> tuple[bool, str]:
    cleaned = text.strip()
    if not cleaned:
        return False, "empty_output"

    for pattern in _BLOCKED_OUTPUT_PATTERNS:
        if re.search(pattern, cleaned):
            return False, "unsafe_output_detected"

    return True, "ok"