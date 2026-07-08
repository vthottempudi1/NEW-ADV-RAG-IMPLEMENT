import json
from typing import Any

import psycopg2

from app.config import settings


class PendingSQLStore:
    def __init__(self) -> None:
        self._table_ready = False

    def _connect(self):
        return psycopg2.connect(settings.database_url)

    def _ensure_table(self) -> None:
        if self._table_ready:
            return

        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_sql_approvals (
                query_id TEXT PRIMARY KEY,
                intent TEXT NOT NULL,
                question TEXT NOT NULL,
                generated_sql TEXT NOT NULL,
                explanation TEXT NOT NULL DEFAULT '',
                rag_answer TEXT,
                rag_sources JSONB,
                rag_confidence DOUBLE PRECISION,
                request_context JSONB,
                cost_saved_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                rag_metadata JSONB,
                auto_metadata JSONB,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            ALTER TABLE pending_sql_approvals
            ADD COLUMN IF NOT EXISTS cost_saved_usd DOUBLE PRECISION NOT NULL DEFAULT 0
            """
        )
        cur.execute(
            """
            ALTER TABLE pending_sql_approvals
            ADD COLUMN IF NOT EXISTS request_context JSONB
            """
        )
        cur.execute(
            """
            ALTER TABLE pending_sql_approvals
            ADD COLUMN IF NOT EXISTS auto_metadata JSONB
            """
        )
        conn.commit()
        cur.close()
        conn.close()
        self._table_ready = True

    def save_pending(
        self,
        *,
        query_id: str,
        intent: str,
        question: str,
        generated_sql: str,
        explanation: str,
        rag_answer: str | None = None,
        rag_sources: list[str] | None = None,
        rag_confidence: float | None = None,
        request_context: dict[str, Any] | None = None,
        cost_saved_usd: float = 0.0,
        rag_metadata: dict[str, Any] | None = None,
        auto_metadata: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_table()

        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO pending_sql_approvals (
                query_id,
                intent,
                question,
                generated_sql,
                explanation,
                rag_answer,
                rag_sources,
                rag_confidence,
                request_context,
                cost_saved_usd,
                rag_metadata,
                auto_metadata,
                status,
                resolved_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, 'pending', NULL)
            ON CONFLICT (query_id) DO UPDATE SET
                intent = EXCLUDED.intent,
                question = EXCLUDED.question,
                generated_sql = EXCLUDED.generated_sql,
                explanation = EXCLUDED.explanation,
                rag_answer = EXCLUDED.rag_answer,
                rag_sources = EXCLUDED.rag_sources,
                rag_confidence = EXCLUDED.rag_confidence,
                request_context = EXCLUDED.request_context,
                cost_saved_usd = EXCLUDED.cost_saved_usd,
                rag_metadata = EXCLUDED.rag_metadata,
                auto_metadata = EXCLUDED.auto_metadata,
                status = 'pending',
                resolved_at = NULL
            """,
            (
                query_id,
                intent,
                question,
                generated_sql,
                explanation,
                rag_answer,
                json.dumps(rag_sources or []),
                rag_confidence,
                json.dumps(request_context or {}),
                cost_saved_usd,
                json.dumps(rag_metadata or {}),
                json.dumps(auto_metadata or {}),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()

    def get_pending(self, query_id: str) -> dict[str, Any] | None:
        self._ensure_table()

        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                query_id,
                intent,
                question,
                generated_sql,
                explanation,
                rag_answer,
                rag_sources,
                rag_confidence,
                request_context,
                cost_saved_usd,
                rag_metadata,
                auto_metadata,
                status
            FROM pending_sql_approvals
            WHERE query_id = %s
            """,
            (query_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return None

        data = {
            "query_id": row[0],
            "intent": row[1],
            "question": row[2],
            "generated_sql": row[3],
            "explanation": row[4],
            "rag_answer": row[5],
            "rag_sources": row[6] or [],
            "rag_confidence": row[7],
            "request_context": row[8] or {},
            "cost_saved_usd": row[9] or 0.0,
            "rag_metadata": row[10] or {},
            "auto_metadata": row[11] or {},
            "status": row[12],
        }
        return data if data["status"] == "pending" else None

    def resolve(self, query_id: str, *, status: str) -> None:
        self._ensure_table()

        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE pending_sql_approvals
            SET status = %s, resolved_at = CURRENT_TIMESTAMP
            WHERE query_id = %s
            """,
            (status, query_id),
        )
        conn.commit()
        cur.close()
        conn.close()


pending_sql_store = PendingSQLStore()
