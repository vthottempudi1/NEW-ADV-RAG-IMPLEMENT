import datetime
import decimal
import json
import uuid
from typing import Any

import psycopg2
from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.config import settings
from app.services.llm_service import generate
from app.services.query_cache_service import query_cache


_FORBIDDEN_SQL_NODES = (
    exp.Alter,
    exp.Command,
    exp.Copy,
    exp.Create,
    exp.Delete,
    exp.Drop,
    exp.Grant,
    exp.Insert,
    exp.Into,
    exp.Merge,
    exp.Revoke,
    exp.Update,
)


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _serialize_value(value) for key, value in row.items()}


def is_select_only(sql: str) -> bool:
    cleaned = sql.strip()
    if not cleaned:
        return False

    try:
        statements = parse(cleaned, read="postgres")
    except ParseError:
        return False

    if len(statements) != 1:
        return False

    statement = statements[0]
    if not isinstance(statement, exp.Query):
        return False

    for forbidden in _FORBIDDEN_SQL_NODES:
        if statement.find(forbidden):
            return False

    return True


class SQLService:
    def __init__(self):
        self._schema_context: str | None = None

    def _build_schema_context(self) -> str:
        if self._schema_context is not None:
            return self._schema_context

        conn = psycopg2.connect(settings.database_url)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
            """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        tables: dict[str, list[str]] = {}
        for table_name, column_name, data_type in rows:
            tables.setdefault(table_name, []).append(f"{column_name} ({data_type})")

        lines = ["Database schema:"]
        for table_name, columns in tables.items():
            lines.append(f"  {table_name}: {', '.join(columns)}")

        self._schema_context = "\n".join(lines)
        return self._schema_context

    def generate_sql(self, question: str) -> dict:
        cached = query_cache.get_sql_generation(question)
        if cached is not None:
            return {
                "sql": cached,
                "explanation": "Loaded from SQL generation cache.",
            }

        schema = self._build_schema_context()
        system = (
            "You are a PostgreSQL expert. "
            "Given a database schema and a user question, generate a safe SELECT query only. "
            "Return JSON with keys: sql, explanation."
        )
        user = f"{schema}\n\nQuestion: {question}\n\nReturn only JSON."

        result = generate(
            system_prompt=system,
            user_message=user,
            model=settings.llm_model_answer,
            temperature=0.0,
        )
        text = result["text"].strip()

        if text.startswith("```"):
            text = "\n".join(text.splitlines()[1:-1]).strip()

        data = json.loads(text)
        payload = {
            "sql": data.get("sql", ""),
            "explanation": data.get("explanation", ""),
        }

        query_cache.set_sql_generation(question, payload["sql"])
        return payload

    def execute_sql(self, sql: str) -> list[dict]:
        if not is_select_only(sql):
            raise ValueError("Only SELECT statements are allowed")

        cached = query_cache.get_sql_result(sql)
        if cached is not None:
            return cached

        conn = psycopg2.connect(settings.database_url)
        cur = conn.cursor()
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchall()
        cur.close()
        conn.close()

        result = [_serialize_row(dict(zip(columns, row, strict=True))) for row in rows]
        query_cache.set_sql_result(sql, result)
        return result
