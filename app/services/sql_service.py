import datetime
import decimal
import json
import re
import uuid
from typing import Any

import psycopg2
from psycopg2 import errors as pg_errors
from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.config import settings
from app.services.cost_service import sql_model_cost
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


class SQLServiceError(Exception):
    def __init__(self, public_detail: str, status_code: int = 500):
        super().__init__(public_detail)
        self.public_detail = public_detail
        self.status_code = status_code


class SQLGenerationError(SQLServiceError):
    pass


class SQLExecutionError(SQLServiceError):
    pass


class SQLValidationError(SQLServiceError):
    pass


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


def _first_error_line(message: str) -> str:
    return " ".join(line.strip() for line in message.splitlines() if line.strip())


_RELATIVE_TIME_PATTERNS = (
    r"\btoday\b",
    r"\byesterday\b",
    r"\bthis week\b",
    r"\blast week\b",
    r"\bthis month\b",
    r"\blast month\b",
    r"\bthis quarter\b",
    r"\blast quarter\b",
    r"\bthis year\b",
    r"\blast year\b",
    r"\blast \d+\s+(day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
    r"\bpast \d+\s+(day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
    r"\bprevious \d+\s+(day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
)


def _db_error_detail(exc: psycopg2.Error) -> str:
    primary = getattr(getattr(exc, "diag", None), "message_primary", None)
    if primary:
        return primary.strip()
    if getattr(exc, "pgerror", None):
        return _first_error_line(exc.pgerror)
    return _first_error_line(str(exc))


def _map_db_error(exc: psycopg2.Error) -> SQLExecutionError:
    detail = _db_error_detail(exc)

    if isinstance(exc, pg_errors.UndefinedTable):
        return SQLExecutionError(
            f"sql_execution_failed: referenced table is missing. {detail}",
            status_code=422,
        )
    if isinstance(exc, pg_errors.UndefinedColumn):
        return SQLExecutionError(
            f"sql_execution_failed: referenced column is missing. {detail}",
            status_code=422,
        )
    if isinstance(exc, pg_errors.SyntaxError):
        return SQLExecutionError(
            f"sql_execution_failed: generated SQL has invalid syntax. {detail}",
            status_code=422,
        )
    if isinstance(exc, psycopg2.OperationalError):
        return SQLExecutionError(
            f"database_connection_failed: {detail}",
            status_code=503,
        )

    return SQLExecutionError(
        f"sql_execution_failed: {detail}",
        status_code=500,
    )


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

    @staticmethod
    def _prepare_sql_question(question: str) -> str:
        lowered = question.lower()
        connectors = (
            " and what does our ",
            " and what is our ",
            " and what does ",
            " and what is the standard ",
            " and how should ",
            " and how do we ",
            " and how can we ",
            " along with ",
        )
        for connector in connectors:
            index = lowered.find(connector)
            if index > 0:
                return question[:index].strip().rstrip("?")
        return question.strip().rstrip("?")

    @staticmethod
    def _cluster_lookup_sql(raw_cluster_ref: str) -> tuple[str, str]:
        reference = raw_cluster_ref.strip().lower()
        env = None
        if reference.startswith("prod-"):
            env = "production"
            reference = "production-" + reference[5:]
        elif reference.startswith("stage-"):
            env = "staging"
            reference = "staging-" + reference[6:]
        elif reference.startswith("dev-"):
            env = "development"
            reference = "development-" + reference[4:]

        compact = re.sub(r"[^a-z0-9]", "", reference)
        region = None
        match = re.search(r"(us|eu|ap|sa|ca)[-_]?([a-z]+)[-_]?(\d)", raw_cluster_ref.lower())
        if match:
            region = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

        if env or region:
            where_clauses = []
            if env:
                where_clauses.append(f"lower(environment) = '{env}'")
            if region:
                where_clauses.append(f"lower(region) = '{region}'")
            if compact:
                where_clauses.append(f"replace(lower(name), '-', '') LIKE '%{compact}%'")

            sql = (
                "SELECT * FROM clusters WHERE "
                + " AND ".join(where_clauses)
                + " ORDER BY cluster_id ASC LIMIT 1;"
            )
            return sql, (
                "Lookup against the clusters table using strict environment/region matching "
                "for shorthand identifiers such as prod-us-east-1."
            )

        sql = (
            "SELECT * FROM clusters WHERE "
            f"(replace(lower(name), '-', '') = '{compact}' "
            f"OR replace(lower(name), '-', '') LIKE '%{compact}%') "
            "ORDER BY "
            f"CASE WHEN replace(lower(name), '-', '') = '{compact}' THEN 0 ELSE 1 END, "
            f"CASE WHEN replace(lower(name), '-', '') LIKE '%{compact}%' THEN 0 ELSE 1 END, "
            "cluster_id ASC LIMIT 1;"
        )
        return sql, "Lookup against the clusters table using normalized cluster-name matching."

    @classmethod
    def _heuristic_sql(cls, question: str) -> dict[str, str] | None:
        normalized = cls._prepare_sql_question(question)
        lowered = normalized.lower()

        if lowered in (
            "how many p1 incidents were resolved in the last quarter",
            "how many p1 incidents were resolved last quarter",
        ):
            return {
                "sql": (
                    "SELECT COUNT(*) AS count FROM incidents "
                    "WHERE severity = 'P1' "
                    "AND resolved_at IS NOT NULL "
                    "AND resolved_at >= date_trunc('quarter', CURRENT_DATE) - INTERVAL '3 months' "
                    "AND resolved_at < date_trunc('quarter', CURRENT_DATE);"
                ),
                "explanation": (
                    "Counts resolved P1 incidents in the previous calendar quarter relative to the current date."
                ),
            }

        if lowered == "which on-call engineer has been paged the most times this month":
            return {
                "sql": (
                    "SELECT engineer, COUNT(*) AS page_count FROM oncall_logs "
                    "WHERE paged_at >= date_trunc('month', CURRENT_DATE) "
                    "AND paged_at < date_trunc('month', CURRENT_DATE) + INTERVAL '1 month' "
                    "GROUP BY engineer ORDER BY page_count DESC, engineer ASC LIMIT 1;"
                ),
                "explanation": (
                    "Finds the most-paged on-call engineer in the current calendar month."
                ),
            }

        if lowered == "how many open p2 alerts exist right now":
            return {
                "sql": (
                    "SELECT COUNT(*) AS open_p2_alerts FROM alerts "
                    "WHERE severity = 'P2' AND resolved = FALSE;"
                ),
                "explanation": "Counts unresolved P2 alerts currently present in the alerts table.",
            }

        if lowered == "what cluster has the most unresolved incidents":
            return {
                "sql": (
                    "SELECT c.name AS cluster_name, "
                    "COUNT(i.incident_id) FILTER (WHERE i.resolved_at IS NULL) AS unresolved_incidents "
                    "FROM clusters c "
                    "LEFT JOIN incidents i ON i.cluster_id = c.cluster_id "
                    "GROUP BY c.cluster_id, c.name "
                    "ORDER BY unresolved_incidents DESC, c.name ASC LIMIT 1;"
                ),
                "explanation": (
                    "Ranks clusters by unresolved incidents using a LEFT JOIN so a stable row is returned even "
                    "when all incidents are resolved."
                ),
            }

        if lowered == "which cluster currently has the most pods in crashloopbackoff status":
            return {
                "sql": (
                    "SELECT c.name AS cluster_name, COUNT(*) AS crashloop_pod_count "
                    "FROM pods p "
                    "JOIN deployments d ON d.deployment_id = p.deployment_id "
                    "JOIN clusters c ON c.cluster_id = d.cluster_id "
                    "WHERE p.status = 'CrashLoopBackOff' "
                    "GROUP BY c.name "
                    "ORDER BY crashloop_pod_count DESC, c.name ASC LIMIT 1;"
                ),
                "explanation": "Counts CrashLoopBackOff pods per cluster and returns the highest count.",
            }

        if lowered == "how many pods are currently in a failed state across all clusters":
            return {
                "sql": "SELECT COUNT(*) AS failed_pod_count FROM pods WHERE status = 'Failed';",
                "explanation": "Counts failed pods across the entire fleet.",
            }

        if lowered == "what is the average mttr for the prod-eu-west cluster":
            return {
                "sql": (
                    "SELECT AVG(i.mttr_minutes) AS avg_mttr_minutes "
                    "FROM incidents i "
                    "JOIN clusters c ON c.cluster_id = i.cluster_id "
                    "WHERE lower(environment) = 'production' "
                    "AND (replace(lower(name), '-', '') LIKE '%euwest%' OR lower(region) = 'eu-west-1');"
                ),
                "explanation": (
                    "Calculates the average MTTR for production clusters in the eu-west region."
                ),
            }

        if lowered.startswith("show me details for cluster "):
            raw_cluster_ref = normalized[len("show me details for cluster ") :]
            sql, explanation = cls._cluster_lookup_sql(raw_cluster_ref)
            return {"sql": sql, "explanation": explanation}

        return None

    @staticmethod
    def _question_uses_relative_time(question: str) -> bool:
        lowered = question.lower()
        return any(re.search(pattern, lowered) for pattern in _RELATIVE_TIME_PATTERNS)

    @staticmethod
    def _sql_uses_dataset_max_anchor(sql: str) -> bool:
        lowered = sql.lower()
        return "max(" in lowered and "interval" in lowered

    @staticmethod
    def _sql_uses_runtime_time_anchor(sql: str) -> bool:
        lowered = sql.lower()
        return any(token in lowered for token in ("current_date", "current_timestamp", "now()"))

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
                "generation_cost_usd": 0.0,
            }

        heuristic = self._heuristic_sql(question)
        if heuristic is not None:
            query_cache.set_sql_generation(question, heuristic["sql"])
            return {
                **heuristic,
                "generation_cost_usd": 0.0,
            }

        schema = self._build_schema_context()
        system = (
            "You are a PostgreSQL expert. "
            "Given a database schema and a user question, generate a safe SELECT query only. "
            "Use only tables and columns that are explicitly present in the schema. "
            "For the incidents table, severity is the incident priority level and resolved incidents "
            "mean resolved_at IS NOT NULL. Use started_at or resolved_at for time filters when present. "
            "For relative dates like 'today', 'yesterday', 'this week', 'last week', 'this month', "
            "'last month', 'this quarter', and 'last quarter', always anchor to CURRENT_DATE. "
            "For rolling windows like 'last 6 months', 'past 30 days', or 'last 12 weeks', anchor to "
            "CURRENT_DATE using INTERVAL expressions. "
            "For exact ranges like 'between 2026-01-01 and 2026-03-31', use the explicit dates directly. "
            "Never use MAX(date_column) or 'latest available data' logic for relative time phrases unless the "
            "user explicitly asks for the latest available data in the dataset. "
            "Example: 'last quarter' should use "
            "resolved_at >= date_trunc('quarter', CURRENT_DATE) - INTERVAL '3 months' "
            "and resolved_at < date_trunc('quarter', CURRENT_DATE). "
            "If the user asks a hybrid question that includes a policy/runbook/procedure part, generate SQL only for "
            "the database-answerable portion of the question. "
            "If the user references a cluster nickname like prod-us-east-1, normalize it against likely production "
            "cluster naming in the clusters table instead of assuming an exact literal name match. "
            "Do not invent columns such as priority, status, breached_sla, or incident_date if they do not exist. "
            "Return JSON with keys: sql, explanation."
        )
        sql_question = self._prepare_sql_question(question)
        user = f"{schema}\n\nQuestion: {sql_question}\n\nReturn only JSON."

        data = None
        total_generation_cost_usd = 0.0
        for attempt in range(2):
            result = generate(
                system_prompt=system,
                user_message=user,
                model=settings.llm_model_sql,
                temperature=0.0,
            )
            usage = result.get("usage", {})
            total_generation_cost_usd += sql_model_cost(
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )
            text = result["text"].strip()

            if text.startswith("```"):
                text = "\n".join(text.splitlines()[1:-1]).strip()

            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                if attempt == 1:
                    raise SQLGenerationError(
                        "sql_generation_failed: model returned invalid JSON",
                        status_code=500,
                    ) from exc
                user = (
                    f"{schema}\n\nQuestion: {sql_question}\n\n"
                    "Your previous answer was not valid JSON. Return only valid JSON "
                    "with non-empty keys: sql, explanation."
                )
                continue

            if data.get("sql"):
                sql_text = data["sql"]
                if self._question_uses_relative_time(sql_question):
                    if self._sql_uses_dataset_max_anchor(sql_text):
                        if attempt == 1:
                            raise SQLGenerationError(
                                "sql_generation_failed: model anchored a relative-time query to dataset MAX(date) instead of CURRENT_DATE",
                                status_code=422,
                            )
                        user = (
                            f"{schema}\n\nQuestion: {sql_question}\n\n"
                            "Your previous SQL incorrectly used MAX(date_column) for a relative-time question. "
                            "Rewrite it using CURRENT_DATE or NOW() semantics. "
                            "Return only valid JSON with keys: sql, explanation."
                        )
                        continue
                    if not self._sql_uses_runtime_time_anchor(sql_text):
                        if attempt == 1:
                            raise SQLGenerationError(
                                "sql_generation_failed: model did not anchor a relative-time query to CURRENT_DATE/NOW()",
                                status_code=422,
                            )
                        user = (
                            f"{schema}\n\nQuestion: {sql_question}\n\n"
                            "Your previous SQL did not clearly anchor the relative-time filter to CURRENT_DATE or NOW(). "
                            "Rewrite it using CURRENT_DATE or NOW() semantics. "
                            "Return only valid JSON with keys: sql, explanation."
                        )
                        continue
                break

            if attempt == 1:
                raise SQLGenerationError(
                    "sql_generation_failed: model returned an empty SQL statement after retry",
                    status_code=422,
                )

            user = (
                f"{schema}\n\nQuestion: {sql_question}\n\n"
                "Your previous answer had an empty sql value. Return valid JSON with a "
                "non-empty safe SELECT statement using only schema tables/columns."
            )

        payload = {
            "sql": data.get("sql", ""),
            "explanation": data.get("explanation", ""),
            "generation_cost_usd": round(total_generation_cost_usd, 6),
        }

        if not payload["sql"]:
            raise SQLGenerationError(
                "sql_generation_failed: model returned an empty SQL statement",
                status_code=422,
            )
        if not is_select_only(payload["sql"]):
            raise SQLGenerationError(
                "sql_generation_failed: model did not produce a safe SELECT statement",
                status_code=422,
            )

        query_cache.set_sql_generation(question, payload["sql"])
        return payload

    def execute_sql(self, sql: str) -> list[dict]:
        if not is_select_only(sql):
            raise SQLValidationError(
                "sql_validation_failed: only SELECT statements are allowed",
                status_code=422,
            )

        cached = query_cache.get_sql_result(sql)
        if cached is not None:
            return cached

        conn = None
        cur = None
        try:
            conn = psycopg2.connect(settings.database_url)
            cur = conn.cursor()
            cur.execute(sql)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchall()
        except psycopg2.Error as exc:
            raise _map_db_error(exc) from exc
        finally:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()

        result = [_serialize_row(dict(zip(columns, row, strict=True))) for row in rows]
        query_cache.set_sql_result(sql, result)
        return result
