# Learner note: Encapsulates count tokens so this responsibility can be understood, tested, and changed independently.
def count_tokens(text: str) -> int:
    """Perform count tokens for the application security boundary.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    return len(text.split())


# Learner note: Encapsulates restructure input so this responsibility can be understood, tested, and changed independently.
def restructure_input(text: str, max_tokens: int) -> tuple[str, str]:
    """Perform restructure input for the application security boundary.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    tokens = text.split()
    if len(tokens) <= max_tokens:
        return text, "unchanged"
    trimmed = " ".join(tokens[:max_tokens])
    return trimmed, "trimmed"
