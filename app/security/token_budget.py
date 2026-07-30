from collections import defaultdict

_usage: dict[str, int] = defaultdict(int)


def check_budget(user_id: str, estimated_tokens: int, max_tokens: int) -> tuple[bool, int]:
    """Check whether `user_id` has enough remaining daily token budget for `estimated_tokens`.

    Returns a `(within_budget, remaining_tokens)` tuple, where `remaining_tokens`
    is `max_tokens` minus tokens already consumed (floored at 0).
    """
    used = _usage[user_id]
    remaining = max(0, max_tokens - used)
    return estimated_tokens <= remaining, remaining


def consume_budget(user_id: str, used_tokens: int) -> None:
    """Add `used_tokens` to `user_id`'s running in-memory token usage total."""
    _usage[user_id] += used_tokens


def get_budget_usage() -> dict[str, int]:
    """Return a snapshot copy of per-user token usage tracked so far."""
    return dict(_usage)


def clear_budget_usage() -> None:
    """Reset all tracked per-user token usage to empty (used by tests/operators)."""
    _usage.clear()
