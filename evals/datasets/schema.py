from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

INTENT = Literal["rag", "sql", "hybrid", "web_fallback", "clarification"]
FEATURE = Literal[
    "baseline",
    "sparse",
    "dense",
    "hybrid",
    "rerank",
    "hyde",
    "crag",
    "self_rag",
    "sql",
    "hybrid_rag_sql",
    "security",
    "wild",
    "clarification",
]

OPTIONAL_DEMO_ONLY_FEATURES = {"dense", "sparse", "security"}


# Note: Golden is part of the evaluation and quality-gate framework.
class Golden(BaseModel):
    """Represent golden within the evaluation and quality-gate framework.

    Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    id: str = Field(..., pattern=r"^q-\d{3}$")
    question: str = Field(..., min_length=1)
    intent: INTENT
    golden_sources: list[str] = Field(default_factory=list)
    acceptable_source_groups: list[list[str]] = Field(default_factory=list)
    golden_answer: str | None = Field(default=None, min_length=1)
    golden_answer_keywords: list[str] = Field(..., min_length=1)
    demonstrates_feature: FEATURE | Literal["self-rag"]
    expected_baseline: Literal["pass", "fail"]
    expected_with_feature: Literal["pass"]
    notes: str
    forbidden_keywords: list[str] = Field(default_factory=list)
    forbidden_sources: list[str] = Field(default_factory=list)
    expected_route: str | None = None

    # Note: Evaluates check expected with feature as a guardrail before later pipeline stages proceed.
    @model_validator(mode="after")
    def check_expected_with_feature(self) -> "Golden":
        """Normalize legacy feature labels and validate required fields."""
        if self.demonstrates_feature == "self-rag":
            self.demonstrates_feature = "self_rag"
        if self.expected_with_feature != "pass":
            raise ValueError("expected_with_feature must be 'pass'")
        return self


# Note: Retrieves load goldens in one place so callers share consistent access behavior.
def load_goldens(path: str | Path) -> list[Golden]:
    """Perform load goldens for the evaluation and quality-gate framework.

    Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected YAML root to be a list, got {type(raw).__name__}")

    goldens = [Golden.model_validate(entry) for entry in raw]

    ids = [g.id for g in goldens]
    if len(ids) != len(set(ids)):
        duplicates = {i for i in ids if ids.count(i) > 1}
        raise ValueError(f"Duplicate golden IDs found: {duplicates}")

    # Warn only for non-demo categories that truly have zero golden entries.
    present_features = {g.demonstrates_feature for g in goldens}
    all_features = set(FEATURE.__args__)  # type: ignore[attr-defined]
    missing = (all_features - OPTIONAL_DEMO_ONLY_FEATURES) - present_features
    if missing:
        import warnings

        warnings.warn(f"No golden entries for features: {missing} (OK if demo-only)")

    return goldens
