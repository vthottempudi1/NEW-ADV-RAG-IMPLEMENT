from Eval import invokers as invoker_module
from Eval.invokers import FixtureInvoker, HttpServiceInvoker
from Eval.ragas_adapter import run as run_ragas
from Eval.schema import load_goldens


def test_fixture_invoker_supports_hybrid_and_sql_goldens():
    goldens = load_goldens("Eval/seed_questions.yaml")
    invoker = FixtureInvoker(goldens)

    hybrid = next(g for g in goldens if g.intent == "hybrid")
    sql = next(g for g in goldens if g.intent == "sql")

    hybrid_resp, hybrid_chunks = invoker.invoke(hybrid.question, {}, hybrid.intent)
    sql_resp, sql_chunks = invoker.invoke(sql.question, {}, sql.intent)

    assert hybrid_resp.metadata.route == "hybrid"
    assert hybrid_resp.sources == hybrid.golden_sources
    assert len(hybrid_chunks) == len(hybrid.golden_sources)

    assert sql_resp.metadata.route == "sql"
    assert sql_resp.sources == sql.golden_sources
    assert len(sql_chunks) == len(sql.golden_sources)


def test_heuristic_ragas_scoring_returns_metric_keys():
    rows = [
        {
            "id": "q-001",
            "question": "What is a Pod in Kubernetes?",
            "answer": "A pod is the smallest deployable unit in Kubernetes and can contain one or more containers.",
            "contexts": [
                "A pod is the smallest deployable unit in Kubernetes. It can run one or more containers in a shared namespace."
            ],
            "ground_truth": "pod, container, namespace",
        }
    ]

    scored = run_ragas(rows, scorer="heuristic")

    assert len(scored) == 1
    metrics = scored[0]
    assert "faithfulness" in metrics
    assert "answer_relevancy" in metrics
    assert "context_precision" in metrics
    assert "context_recall" in metrics
    assert all(0.0 <= metrics[key] <= 1.0 for key in (
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_recall",
    ))


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeHttpClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.closed = False

    def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if not self._responses:
            raise AssertionError(f"No fake HTTP response queued for {url}")
        return self._responses.pop(0)

    def close(self):
        self.closed = True


def test_http_service_invoker_registers_and_invokes_rag(monkeypatch):
    fake_client = _FakeHttpClient(
        [
            _FakeResponse(201, {"token": "fake-token"}),
            _FakeResponse(
                200,
                {
                    "answer": "RAG answer",
                    "sources": ["doc1.pdf"],
                    "confidence": 0.81,
                    "cache_hit": False,
                    "metadata": {
                        "route": "rag",
                        "retrieved_chunks": [
                            {
                                "text": "chunk text",
                                "source": "doc1.pdf",
                                "score": 0.9,
                                "retrieval_score": 0.7,
                                "rerank_score": 0.95,
                            }
                        ],
                    },
                },
            ),
        ]
    )

    monkeypatch.setattr(invoker_module.httpx, "Client", lambda timeout=120.0: fake_client)

    invoker = HttpServiceInvoker("http://backend.example.com")
    response, chunks = invoker.invoke(
        "What is Kubernetes?",
        {"top_k": 3, "search_mode": "hybrid", "enable_rerank": True},
        "rag",
    )
    invoker.close()

    assert response.answer == "RAG answer"
    assert response.sources == ["doc1.pdf"]
    assert len(chunks) == 1
    assert chunks[0].source == "doc1.pdf"
    assert fake_client.calls[0]["url"] == "http://backend.example.com/auth/register"
    assert fake_client.calls[1]["url"] == "http://backend.example.com/query"
    assert fake_client.calls[1]["headers"]["Authorization"] == "Bearer fake-token"
    assert fake_client.closed is True


def test_http_service_invoker_auto_approves_pending_sql(monkeypatch):
    fake_client = _FakeHttpClient(
        [
            _FakeResponse(201, {"token": "fake-token"}),
            _FakeResponse(
                200,
                {
                    "answer": "",
                    "sources": [],
                    "confidence": 0.0,
                    "cache_hit": False,
                    "pending_sql": {
                        "sql": "select count(*) as total_users from users",
                        "query_id": "query-123",
                        "explanation": "Count users.",
                    },
                    "metadata": {"route": "hybrid_sql_pending", "retrieved_chunks": []},
                },
            ),
            _FakeResponse(
                200,
                {
                    "answer": "There are 3 users and the roadmap recommends AI roles.",
                    "sources": ["roadmap.pdf", "database query"],
                    "confidence": 0.85,
                    "cache_hit": False,
                    "metadata": {
                        "route": "hybrid",
                        "retrieved_chunks": [
                            {
                                "text": "roadmap context",
                                "source": "roadmap.pdf",
                                "score": 0.91,
                                "retrieval_score": 0.91,
                                "rerank_score": None,
                            }
                        ],
                        "sql_query": "select count(*) as total_users from users",
                        "sql_rows": [{"total_users": 3}],
                    },
                },
            ),
        ]
    )

    monkeypatch.setattr(invoker_module.httpx, "Client", lambda timeout=120.0: fake_client)

    invoker = HttpServiceInvoker(
        "http://backend.example.com",
        username="eval.user@example.com",
        password="Test123!",
        approve_sql=True,
    )
    response, chunks = invoker.invoke(
        "How many users are there and what does the roadmap say?",
        {"top_k": 5, "search_mode": "hybrid"},
        "hybrid",
    )

    assert response.metadata.route == "hybrid"
    assert response.metadata.sql_query == "select count(*) as total_users from users"
    assert response.metadata.sql_rows == [{"total_users": 3}]
    assert len(chunks) == 1
    assert fake_client.calls[2]["url"] == "http://backend.example.com/query/sql/execute"
    assert fake_client.calls[2]["json"] == {
        "query_id": "query-123",
        "approved": True,
    }
