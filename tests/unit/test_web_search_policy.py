from app.rag.web_search import _is_trusted_web_source


# Web evidence requires an explicit authority allowlist.
def test_trusted_web_source_policy_rejects_uncontrolled_publishers():
    """Verify that official sources pass while video, social, and generic blogs fail."""
    assert _is_trusted_web_source("https://kubernetes.io/docs/concepts/overview/components/")
    assert _is_trusted_web_source("https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html")
    assert _is_trusted_web_source("https://docs.cilium.io/en/stable/gettingstarted/")
    assert not _is_trusted_web_source("https://www.youtube.com/watch?v=noise")
    assert not _is_trusted_web_source("https://medium.com/example/noise")
    assert not _is_trusted_web_source("https://dev.to/example/noise")
    assert not _is_trusted_web_source("https://aws.amazon.com/blogs/containers/old-version-news")
    assert not _is_trusted_web_source("https://github.com/untrusted/example")
    assert _is_trusted_web_source("https://github.com/cilium/cilium-cli")
