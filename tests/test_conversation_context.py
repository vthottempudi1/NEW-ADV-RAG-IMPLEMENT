from app.services.conversation_context import rewrite_follow_up_question


def test_rewrite_follow_up_resolves_configmap_reference():
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


def test_rewrite_follow_up_carries_secret_reference_across_turns():
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


def test_rewrite_follow_up_expands_previous_comparison_pair():
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
