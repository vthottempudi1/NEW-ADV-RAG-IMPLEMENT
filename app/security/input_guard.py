import re

_INJECTION_PATTERNS = [
    r"(?i)ignore\s+previous",
    r"(?i)ignore\s+all\s+instructions",
    r"(?i)reveal\s+your\s+system\s+prompt",
    r"(?i)show\s+your\s+hidden\s+instructions",
    r"(?i)you\s+are\s+now",
    r"(?i)override\s+previous\s+instructions",
]


def check_input_safe(text: str) -> tuple[bool, str]:
    """Screen user-supplied `text` for prompt-injection attempts before it reaches the LLM.

    Rejects empty input and any text matching a known injection pattern (e.g.
    "ignore previous instructions", "reveal your system prompt", "you are now").
    Returns a `(is_safe, reason)` tuple, where `reason` is "empty_input",
    "prompt_injection_detected", or "ok".
    """
    cleaned = text.strip()
    if not cleaned:
        return False, "empty_input"

    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, cleaned):
            return False, "prompt_injection_detected"

    return True, "ok"
