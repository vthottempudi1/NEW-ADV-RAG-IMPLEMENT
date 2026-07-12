"""Unit tests for retrieval-blocking ambiguity detection."""

import pytest

from app.rag.clarification import detect_clarification_need


# Learner Note: Every reproduced OOD failure must pause before retrieving noisy evidence.
@pytest.mark.parametrize(
    "question",
    [
        "How do I scale?",
        "How do I deploy?",
        "How do I restart it?",
        "How do I secure this?",
        "How do I make it faster?",
        "What is the best architecture?",
        "How do I back it up?",
        "How do I monitor it?",
        "Make it bigger.",
        "Why is this slow?",
        "Can you roll it back?",
    ],
)
def test_underspecified_action_requires_clarification(question):
    """Verify that a generic action produces a concrete follow-up prompt."""
    decision = detect_clarification_need(question)

    assert decision is not None
    assert decision.prompt.endswith("?")


# Learner Note: Explicit Kubernetes targets must continue into normal retrieval.
@pytest.mark.parametrize(
    "question",
    [
        "How do I scale a Kubernetes Deployment?",
        "How do I restart a Pod?",
        "How do I monitor a Kubernetes cluster?",
        "How do I secure a Kubernetes Secret?",
    ],
)
def test_specific_kubernetes_action_does_not_require_clarification(question):
    """Verify that a supported target bypasses the clarification gate."""
    assert detect_clarification_need(question) is None


# Learner Note: Test additional underspecified requests require clarification is part of the automated regression suite.
@pytest.mark.parametrize(
    "question",
    [
        "Can you make it respond faster?",
        "Can you make it private?",
        "Can you rotate it now?",
        "Can you revoke it?",
        "What architecture should I use?",
        "What changed?",
        "Can you roll it back?",
    ],
)
def test_additional_underspecified_requests_require_clarification(question):
    """Verify performance, architecture, and change-scope gaps stop before retrieval."""
    assert detect_clarification_need(question) is not None
