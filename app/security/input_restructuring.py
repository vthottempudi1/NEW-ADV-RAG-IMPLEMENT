def count_tokens(text: str) -> int:
    """Estimate token count as the number of whitespace-separated words in `text`."""
    return len(text.split())


def restructure_input(text: str, max_tokens: int) -> tuple[str, str]:
    """Trim `text` down to at most `max_tokens` whitespace-separated tokens.

    Returns a `(result_text, status)` tuple: `status` is "unchanged" when
    `text` is already within budget, or "trimmed" when it was truncated.
    """
    tokens = text.split()
    if len(tokens) <= max_tokens:
        return text, "unchanged"
    trimmed = " ".join(tokens[:max_tokens])
    return trimmed, "trimmed"
