from __future__ import annotations


# Note: Encapsulates forbidden keywords check so this responsibility can be understood, tested, and changed independently.
def forbidden_keywords_check(answer: str, forbidden: list[str]) -> dict:
    """Check if any forbidden keywords are present in the answer."""
    answer_lower = answer.lower()
    hits = [kw for kw in forbidden if kw.lower() in answer_lower]
    return {"passed": not hits, "hits": hits}


# Note: Fail evaluation when known noisy or disallowed sources survive retrieval.
def forbidden_sources_check(actual: list[str], forbidden: list[str]) -> dict:
    """Return disallowed source patterns found in the final evidence list."""
    hits = [
        source
        for source in actual
        if any(pattern.lower() in source.lower() for pattern in forbidden)
    ]
    return {"passed": not hits, "hits": hits}

# Note: Encapsulates source overlap so this responsibility can be understood, tested, and changed independently.
def source_overlap(actual: list[str], golden: list[str]) -> dict:
    """Check for overlap between actual and golden sources."""
    import os

    # Note: Encapsulates singularize so this responsibility can be understood, tested, and changed independently.
    def _singularize(token: str) -> str:
        """Support the evaluation and quality-gate framework by performing singularize.

        Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        return token[:-1] if token.endswith("s") and len(token) > 3 else token

    # Note: Encapsulates aliases so this responsibility can be understood, tested, and changed independently.
    def _aliases(source: str) -> set[str]:
        """Support the evaluation and quality-gate framework by performing aliases.

        Only the leaf (final `__`-delimited) segment is aliased. Golden filenames share
        generic taxonomy segments like `concepts__workloads__controllers__*` across many
        unrelated entities (DaemonSet, Job, Deployment, ...); aliasing every segment made
        any two documents in the same category match regardless of the actual entity the
        golden source names, which let wrong-document retrievals score as correct.

        Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        lowered_source = source.strip().lower()
        raw = os.path.splitext(os.path.basename(source.strip().lower()))[0]
        parts = [part for part in raw.split("__") if part]
        aliases = {raw}

        if raw in {"database query", "query_results"}:
            aliases.update({"database query", "query_results", "database", "sql"})

        if lowered_source.startswith("http://") or lowered_source.startswith("https://"):
            aliases.update({"tavily_web", "web", "http"})

        leaf = parts[-1] if parts else raw
        aliases.add(leaf)
        aliases.add(_singularize(leaf))
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


# Note: Source recall is part of the evaluation and quality-gate framework.
def source_recall(
    actual: list[str],
    golden: list[str],
    acceptable_groups: list[list[str]] | None = None,
) -> float | None:
    """Return required source-group coverage, supporting authoritative alternatives."""
    if acceptable_groups:
        covered = sum(
            source_overlap(actual, alternatives)["overlap_pct"] > 0.0
            for alternatives in acceptable_groups
        )
        return round(covered / len(acceptable_groups), 3)
    if not golden:
        return None
    return float(source_overlap(actual, golden)["overlap_pct"])


# Note: Measure how much final evidence belongs to an expected source family.
def source_precision(
    actual: list[str],
    golden: list[str],
    acceptable_groups: list[list[str]] | None = None,
) -> float:
    """Return the fraction of final sources matching a required or alternative source."""
    expected = [source for group in (acceptable_groups or []) for source in group] or golden
    if not actual:
        return 1.0 if not expected else 0.0
    if not expected:
        return 0.0
    relevant = sum(
        source_overlap([source], expected)["overlap_pct"] > 0.0 for source in actual
    )
    return round(relevant / len(actual), 3)
