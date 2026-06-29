from collections import defaultdict


_usage: dict[str, int] = defaultdict(int)


def check_budget(user_id: str, estimated_tokens: int, max_tokens: int) -> tuple[bool, int]:
    used = _usage[user_id]
    remaining = max(0, max_tokens - used)
    return estimated_tokens <= remaining, remaining


def consume_budget(user_id: str, used_tokens: int) -> None:
    _usage[user_id] += used_tokens


def get_budget_usage() -> dict[str, int]:
    return dict(_usage)


def clear_budget_usage() -> None:
    _usage.clear()