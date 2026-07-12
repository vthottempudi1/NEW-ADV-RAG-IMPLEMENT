from collections import defaultdict

_usage: dict[str, int] = defaultdict(int)


# Learner note: Evaluates check budget as a guardrail before later pipeline stages proceed.
def check_budget(user_id: str, estimated_tokens: int, max_tokens: int) -> tuple[bool, int]:
    """Perform check budget for the application security boundary.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    used = _usage[user_id]
    remaining = max(0, max_tokens - used)
    return estimated_tokens <= remaining, remaining


# Learner note: Persists consume budget consistently so state changes remain controlled and testable.
def consume_budget(user_id: str, used_tokens: int) -> None:
    """Perform consume budget for the application security boundary.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    _usage[user_id] += used_tokens


# Learner note: Retrieves get budget usage in one place so callers share consistent access behavior.
def get_budget_usage() -> dict[str, int]:
    """Perform get budget usage for the application security boundary.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    return dict(_usage)


# Learner note: Clears clear budget usage safely so tests and operations can restore a known state.
def clear_budget_usage() -> None:
    """Perform clear budget usage for the application security boundary.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    _usage.clear()
