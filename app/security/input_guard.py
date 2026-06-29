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
    cleaned = text.strip()
    if not cleaned:
        return False, "empty_input"

    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, cleaned):
            return False, "prompt_injection_detected"

    return True, "ok"