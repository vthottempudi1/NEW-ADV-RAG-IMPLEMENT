from app.rag.conversation_context import rewrite_follow_up_question


# Note: Verifies test rewrite follow up resolves configmap reference so future changes cannot silently break this expected behavior.
def test_rewrite_follow_up_resolves_configmap_reference():
    """Verify that rewrite follow up resolves configmap reference.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    rewritten, subject = rewrite_follow_up_question(
        "For the non-sensitive one, if I inject it as environment variables instead of a volume, will updates show up automatically?",
        [
            {
                "question": "What is the difference between a ConfigMap and a Secret in Kubernetes?",
                "answer": "A ConfigMap stores non-sensitive configuration. A Secret stores sensitive data.",
                "sources": ["configmap.html", "secret.txt"],
            }
        ],
    )

    assert subject == "ConfigMap"
    assert rewritten.startswith("For the ConfigMap")


# Note: Verifies test rewrite follow up carries secret reference across turns so future changes cannot silently break this expected behavior.
def test_rewrite_follow_up_carries_secret_reference_across_turns():
    """Verify that rewrite follow up carries secret reference across turns.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    rewritten, subject = rewrite_follow_up_question(
        "Would you use that same object for a database password?",
        [
            {
                "question": "For the one that is meant for confidential data, is it actually encrypted by default?",
                "answer": "In Kubernetes, Secrets are not encrypted by default unless encryption at rest is configured.",
                "sources": ["secret.txt"],
            }
        ],
    )

    assert subject == "Secret"
    assert rewritten == "Would you use a Secret for a database password?"


# Note: Verifies test rewrite follow up expands previous comparison pair so future changes cannot silently break this expected behavior.
def test_rewrite_follow_up_expands_previous_comparison_pair():
    """Verify that rewrite follow up expands previous comparison pair.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    rewritten, subject = rewrite_follow_up_question(
        "Which one would you use for a database, and why?",
        [
            {
                "question": "How does a StatefulSet differ from a Deployment for stateful applications?",
                "answer": "A StatefulSet keeps stable identity and storage, while a Deployment is for interchangeable stateless Pods.",
                "sources": ["statefulset.docx", "deployment.txt"],
            }
        ],
    )

    assert subject == "StatefulSet or Deployment"
    assert rewritten == "Which one, StatefulSet or Deployment, would you use for a database, and why?"


# Note: Verifies a follow-up keeps the incident runbook subject instead of becoming a context-free query.
def test_rewrite_follow_up_preserves_incident_runbook_context():
    """Verify that rewrite follow up preserves incident runbook context.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    rewritten, subject = rewrite_follow_up_question(
        "What does it say to do first?",
        [
            {
                "question": "What does our Incident Response Runbook require for P2 alerts?",
                "answer": "The Incident Response Runbook begins with severity and impact triage.",
            }
        ],
    )

    assert subject == "Incident Response Runbook"
    assert rewritten == "What does the Incident Response Runbook say to do first?"


# Note: Verifies escalation-policy follow-ups retain their authoritative document context.
def test_rewrite_follow_up_preserves_escalation_policy_context():
    """Verify that rewrite follow up preserves escalation policy context.

    Note:
        This regression test protects an expected production behavior from silent changes.
    """
    rewritten, subject = rewrite_follow_up_question(
        "What is the first step?",
        [
            {
                "question": "What does our On-Call Escalation Policy require for P1 incidents?",
                "answer": "The On-Call Escalation Policy requires immediate acknowledgement.",
            }
        ],
    )

    assert subject == "On-Call Escalation Policy"
    assert rewritten.startswith("According to the On-Call Escalation Policy")


# Note: Test operational after that follow up stays on runbook is part of the automated regression suite.
def test_operational_after_that_follow_up_stays_on_runbook():
    """Procedural pronouns must not escape to noisy web retrieval."""
    rewritten, subject = rewrite_follow_up_question(
        "What should we do after that if mitigation fails?",
        [
            {
                "question": "What does our incident response runbook say to do first?",
                "answer": "Establish severity and begin mitigation.",
                "sources": ["incident-response-runbook.html"],
            }
        ],
    )

    assert subject == "On-Call Escalation Policy"
    assert rewritten == (
        "According to the On-Call Escalation Policy, what escalation steps "
        "are required when incident mitigation fails?"
    )
