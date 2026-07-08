from __future__ import annotations

def forbidden_keywords_check(answer: str, forbidden: list[str]) -> dict:
    """Check if any forbidden keywords are present in the answer."""
    answer_lower = answer.lower()
    hits = [kw for kw in forbidden if kw.lower() in answer_lower]
    return {"passed": not hits, "hits": hits}

def source_overlap(actual: list[str], golden: list[str]) -> dict:
    """Check for overlap between actual and golden sources."""
    import os
    import re

    def _singularize(token: str) -> str:
        return token[:-1] if token.endswith("s") and len(token) > 3 else token

    def _aliases(source: str) -> set[str]:
        lowered_source = source.strip().lower()
        raw = os.path.splitext(os.path.basename(source.strip().lower()))[0]
        parts = [part for part in raw.split("__") if part]
        aliases = {raw}

        if lowered_source.startswith("http://") or lowered_source.startswith("https://"):
            aliases.update({"tavily_web", "web", "http"})

        for part in parts:
            aliases.add(part)
            aliases.add(_singularize(part))

        for part in parts:
            for token in re.split(r"[^a-z0-9]+", part):
                if token:
                    aliases.add(token)
                    aliases.add(_singularize(token))

        aliases.add(_singularize(raw))
        return {alias for alias in aliases if alias}

    actual_aliases: dict[str, set[str]] = {source: _aliases(source) for source in actual}
    golden_aliases: dict[str, set[str]] = {source: _aliases(source) for source in golden}

    matched: set[str] = set()
    missed: list[str] = []

    for golden_source, golden_set in golden_aliases.items():
        found = False
        for actual_set in actual_aliases.values():
            if golden_set & actual_set:
                found = True
                matched.update(golden_set & actual_set)
                break
        if not found:
            missed.append(os.path.splitext(os.path.basename(golden_source.strip().lower()))[0])

    return {
        "overlap_pct": round((len(golden) - len(missed)) / max(len(golden), 1), 3) if golden else 0.0,
        "matched": sorted(matched),
        "missed": sorted(missed),
    }
