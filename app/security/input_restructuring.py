def count_tokens(text: str) -> int:
    return len(text.split())


def restructure_input(text: str, max_tokens: int) -> tuple[str, str]:
    tokens = text.split()
    if len(tokens) <= max_tokens:
        return text, "unchanged"
    trimmed = " ".join(tokens[:max_tokens])
    return trimmed, "trimmed"