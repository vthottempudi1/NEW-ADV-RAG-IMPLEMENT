import json
import os
from typing import Any
from urllib.parse import urlparse

import httpx
import jwt
import streamlit as st

DEFAULT_API_BASE = os.getenv("API_BASE_URL", "http://localhost:8003")

USE_CASES: dict[str, dict[str, Any]] = {
    "Hybrid Default": {
        "question": "How many P1 incidents were resolved last quarter and what does our escalation policy say for P1 incidents?",
        "search_mode": "hybrid",
        "enable_rerank": True,
        "enable_hyde": False,
        "enable_crag": True,
        "enable_self_reflective": False,
        "top_k": 5,
        "label": "Best default workflow",
    },
    "RAG Policy": {
        "question": "What does our escalation policy say for P1 incidents?",
        "search_mode": "hybrid",
        "enable_rerank": True,
        "enable_hyde": False,
        "enable_crag": True,
        "enable_self_reflective": False,
        "top_k": 5,
        "label": "Document-grounded policy lookup",
    },
    "SQL Count": {
        "question": "How many P1 incidents were resolved last quarter?",
        "search_mode": "hybrid",
        "enable_rerank": True,
        "enable_hyde": False,
        "enable_crag": True,
        "enable_self_reflective": False,
        "top_k": 5,
        "label": "Structured SQL route",
    },
    "Troubleshooting": {
        "question": "What does ErrImagePull mean and how do I fix it?",
        "search_mode": "hybrid",
        "enable_rerank": True,
        "enable_hyde": False,
        "enable_crag": True,
        "enable_self_reflective": False,
        "top_k": 5,
        "label": "Operational troubleshooting",
    },
    "HyDE Search": {
        "question": "How do I make sure my app keeps running even if a server dies?",
        "search_mode": "hybrid",
        "enable_rerank": True,
        "enable_hyde": True,
        "enable_crag": False,
        "enable_self_reflective": False,
        "top_k": 5,
        "label": "Semantic retrieval expansion",
    },
    "SRAG Reflection": {
        "question": "My Kubernetes app keeps restarting, and I am not sure whether the root cause is the liveness probe, OOMKilled, or a bad image. How should I troubleshoot it step by step?",
        "search_mode": "hybrid",
        "enable_rerank": True,
        "enable_hyde": False,
        "enable_crag": True,
        "enable_self_reflective": True,
        "top_k": 5,
        "label": "Ambiguous troubleshooting with self-reflection",
    },
}


# Learner note: Encapsulates init state so this responsibility can be understood, tested, and changed independently.
def _init_state() -> None:
    """Support the Streamlit presentation layer by performing init state.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    st.session_state.setdefault("api_base", DEFAULT_API_BASE)
    current_api_base = str(st.session_state.get("api_base", "")).strip()
    if DEFAULT_API_BASE and (
        not current_api_base
        or current_api_base.startswith("http://localhost:")
        or current_api_base.startswith("https://localhost:")
        or current_api_base.startswith("http://127.0.0.1:")
        or current_api_base.startswith("https://127.0.0.1:")
    ):
        st.session_state["api_base"] = DEFAULT_API_BASE
    st.session_state.setdefault("token", "")
    st.session_state.setdefault("is_admin", False)
    st.session_state.setdefault("username", "")
    st.session_state.setdefault("last_query_response", None)
    st.session_state.setdefault("pending_sql", None)
    st.session_state.setdefault("query_history", [])
    st.session_state.setdefault("conversation_context", [])
    st.session_state.setdefault("selected_use_case", "Hybrid Default")
    st.session_state.setdefault("query_ui_mode", "Auto")
    st.session_state.setdefault("backend_health", None)


# Learner note: Encapsulates inject styles so this responsibility can be understood, tested, and changed independently.
def _inject_styles() -> None:
    """Support the Streamlit presentation layer by performing inject styles.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    st.markdown(
        """
        <style>
        :root {
            --brand-ink: #153243;
            --brand-teal: #2a9d8f;
            --brand-sand: #f4efe6;
            --brand-gold: #e9c46a;
            --brand-red: #d96c5f;
        }
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
            max-width: 1280px;
        }
        .hero {
            background:
                radial-gradient(circle at top right, rgba(233,196,106,0.22), transparent 34%),
                linear-gradient(135deg, #153243 0%, #1f5b66 52%, #2a9d8f 100%);
            border-radius: 24px;
            padding: 26px 28px 28px 28px;
            color: white;
            margin-bottom: 1.2rem;
            box-shadow: 0 22px 42px rgba(21, 50, 67, 0.18);
            text-align: center;
        }
        .hero-inner {
            max-width: 900px;
            margin: 0 auto;
        }
        .hero-title {
            font-size: 2.35rem;
            font-weight: 800;
            line-height: 1.08;
            margin: 0 0 0.6rem 0;
            letter-spacing: -0.02em;
        }
        .hero-subtitle {
            font-size: 1rem;
            opacity: 0.92;
            margin: 0 auto 1rem auto;
            max-width: 760px;
        }
        .hero-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            justify-content: center;
        }
        .pill {
            display: inline-block;
            background: rgba(255,255,255,0.16);
            border: 1px solid rgba(255,255,255,0.18);
            padding: 6px 12px;
            border-radius: 999px;
            font-size: 0.82rem;
            font-weight: 700;
        }
        .surface {
            background: linear-gradient(180deg, rgba(244,239,230,0.58), rgba(255,255,255,0.95));
            border: 1px solid rgba(21,50,67,0.08);
            border-radius: 20px;
            padding: 18px 18px 14px 18px;
            box-shadow: 0 8px 28px rgba(21,50,67,0.06);
            margin-bottom: 1rem;
        }
        .section-title {
            font-size: 1.05rem;
            font-weight: 800;
            color: var(--brand-ink);
            margin-bottom: 0.2rem;
        }
        .section-caption {
            color: #4b6470;
            font-size: 0.9rem;
            margin-bottom: 0.8rem;
        }
        .metric-strip {
            display: grid;
            grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 12px;
            margin-top: 0.75rem;
        }
        .metric-card {
            background: white;
            border: 1px solid rgba(21,50,67,0.08);
            border-radius: 16px;
            padding: 12px 14px;
        }
        .metric-label {
            font-size: 0.75rem;
            color: #5f7780;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            font-weight: 700;
        }
        .metric-value {
            font-size: 1.05rem;
            color: var(--brand-ink);
            font-weight: 800;
            margin-top: 0.15rem;
        }
        .meta-strip {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
            margin-top: 1rem;
        }
        .meta-card {
            background: rgba(255,255,255,0.96);
            border: 1px solid rgba(21,50,67,0.08);
            border-radius: 14px;
            padding: 10px 12px;
        }
        .meta-label {
            font-size: 0.72rem;
            color: #68808a;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            font-weight: 700;
        }
        .meta-value {
            font-size: 0.98rem;
            color: var(--brand-ink);
            font-weight: 800;
            margin-top: 0.15rem;
            word-break: break-word;
        }
        .small-note {
            color: #627985;
            font-size: 0.82rem;
        }
        .config-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            margin-top: 0.5rem;
        }
        .config-item {
            background: rgba(255,255,255,0.92);
            border: 1px solid rgba(21,50,67,0.08);
            border-radius: 14px;
            padding: 10px 12px;
        }
        .config-key {
            font-size: 0.72rem;
            color: #68808a;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            font-weight: 700;
        }
        .config-value {
            font-size: 0.96rem;
            color: var(--brand-ink);
            font-weight: 800;
            margin-top: 0.15rem;
            word-break: break-word;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# Learner note: Encapsulates auth headers so this responsibility can be understood, tested, and changed independently.
def _auth_headers() -> dict[str, str]:
    """Support the Streamlit presentation layer by performing auth headers.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    token = st.session_state.get("token", "")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


# Learner note: Encapsulates decode token so this responsibility can be understood, tested, and changed independently.
def _decode_token(token: str) -> dict[str, Any]:
    """Support the Streamlit presentation layer by performing decode token.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    try:
        return jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
            },
        )
    except Exception:
        return {}


# Learner note: Encapsulates handle login token so this responsibility can be understood, tested, and changed independently.
def _handle_login_token(token: str, username: str) -> None:
    """Support the Streamlit presentation layer by performing handle login token.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    payload = _decode_token(token)
    st.session_state["token"] = token
    st.session_state["username"] = username
    st.session_state["is_admin"] = bool(payload.get("is_admin", False))


# Learner note: Encapsulates clear auth so this responsibility can be understood, tested, and changed independently.
def _clear_auth() -> None:
    """Support the Streamlit presentation layer by performing clear auth.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    st.session_state["token"] = ""
    st.session_state["username"] = ""
    st.session_state["is_admin"] = False
    st.session_state["pending_sql"] = None


# Learner note: Encapsulates request so this responsibility can be understood, tested, and changed independently.
def _request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> tuple[int, Any]:
    """Support the Streamlit presentation layer by performing request.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    url = st.session_state["api_base"].rstrip("/") + path
    headers = _auth_headers()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(
                method,
                url,
                json=json_body,
                files=files,
                headers=headers,
            )
    except httpx.TimeoutException as exc:
        return 0, {"detail": f"upstream_timeout: backend request timed out. {exc}"}
    except httpx.HTTPError as exc:
        return 0, {"detail": f"backend_connection_failed: {exc.__class__.__name__}: {exc}"}
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, response.text


# Learner note: Encapsulates error text so this responsibility can be understood, tested, and changed independently.
def _error_text(payload: Any) -> str:
    """Support the Streamlit presentation layer by performing error text.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            suffix_parts = []
            if payload.get("status_code") is not None:
                suffix_parts.append(f"status={payload['status_code']}")
            if payload.get("path"):
                suffix_parts.append(f"path={payload['path']}")
            if payload.get("method"):
                suffix_parts.append(f"method={payload['method']}")
            if payload.get("request_id"):
                suffix_parts.append(f"request_id={payload['request_id']}")
            if suffix_parts:
                return f"{detail} ({', '.join(suffix_parts)})"
            return detail
        return json.dumps(payload, indent=2, default=str)
    if isinstance(payload, str):
        lowered = payload.lower()
        if "504 gateway time-out" in lowered:
            return (
                "gateway_timeout: the load balancer reached the backend, but the "
                "backend did not finish in time. Check backend logs, database latency, "
                "or external dependency calls."
            )
        if "503 service temporarily unavailable" in lowered:
            return (
                "service_unavailable: the load balancer does not currently have a "
                "healthy backend target."
            )
    return str(payload)


# Learner note: Encapsulates badge so this responsibility can be understood, tested, and changed independently.
def _badge(label: str, kind: str = "blue") -> str:
    """Support the Streamlit presentation layer by performing badge.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    palette = {
        "blue": ("#dbeafe", "#1e40af"),
        "green": ("#dcfce7", "#166534"),
        "yellow": ("#fef3c7", "#92400e"),
        "purple": ("#f3e8ff", "#6b21a8"),
        "red": ("#fee2e2", "#991b1b"),
    }
    bg, fg = palette.get(kind, palette["blue"])
    return (
        f'<span style="background:{bg};color:{fg};padding:4px 11px;'
        f'border-radius:999px;font-size:12px;font-weight:700;display:inline-block;">{label}</span>'
    )


# Learner note: Encapsulates render surface header so this responsibility can be understood, tested, and changed independently.
def _render_surface_header(title: str, caption: str) -> None:
    """Support the Streamlit presentation layer by performing render surface header.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    st.markdown(
        f"""
        <div class="surface">
            <div class="section-title">{title}</div>
            <div class="section-caption">{caption}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# Learner note: Encapsulates render health card so this responsibility can be understood, tested, and changed independently.
def _render_health_card(payload: dict[str, Any]) -> None:
    """Support the Streamlit presentation layer by performing render health card.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    status = payload.get("status", "unknown")
    active_collection = payload.get("active_collection", "n/a")
    st.sidebar.markdown(
        _badge(f"health: {status}", "green" if status == "ok" else "yellow"),
        unsafe_allow_html=True,
    )
    st.sidebar.caption(f"collection: {active_collection}")
    dependencies = payload.get("dependencies") or {}
    if dependencies:
        st.sidebar.caption("Dependency connectivity")
        for name in ("postgres", "qdrant", "redis", "s3"):
            result = dependencies.get(name, {})
            dependency_status = str(result.get("status", "unknown"))
            latency = result.get("latency_ms")
            color = "green" if dependency_status == "connected" else "yellow"
            latency_label = f" · {latency:.0f} ms" if isinstance(latency, (int, float)) else ""
            st.sidebar.markdown(
                _badge(f"{name}: {dependency_status}{latency_label}", color),
                unsafe_allow_html=True,
            )


# Learner note: Encapsulates load backend health so this responsibility can be understood, tested, and changed independently.
def _load_backend_health(force: bool = False) -> dict[str, Any] | None:
    """Support the Streamlit presentation layer by performing load backend health.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    cached = st.session_state.get("backend_health")
    if cached is not None and not force:
        return cached

    status, data = _request("GET", "/health", timeout=8.0)
    if status == 200 and isinstance(data, dict):
        st.session_state["backend_health"] = data
        return data

    st.session_state["backend_health"] = {
        "status": "unreachable",
        "version": "n/a",
        "active_collection": "n/a",
    }
    return st.session_state["backend_health"]


# Learner note: Encapsulates environment label so this responsibility can be understood, tested, and changed independently.
def _environment_label(api_base: str) -> str:
    """Support the Streamlit presentation layer by performing environment label.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    lowered = api_base.lower()
    if "aiscientificlabs.com" in lowered:
        return "Production"
    if "localhost" in lowered or "127.0.0.1" in lowered:
        return "Local"
    return "Custom"


# Learner note: Encapsulates display source label so this responsibility can be understood, tested, and changed independently.
def _display_source_label(source: str) -> tuple[str, str]:
    """Support the Streamlit presentation layer by performing display source label.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    raw = str(source or "")
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        domain = parsed.netloc.replace("www.", "")
        path = parsed.path.rstrip("/").split("/")[-1] or parsed.netloc
        return f"{domain} / {path}", "External"

    compact = raw.replace("__", " / ").replace(".docx", "").replace(".html", "").replace(".txt", "")
    compact = compact.replace(".pdf", "")
    return compact, "Corpus"


# Learner note: Encapsulates render deployment info so this responsibility can be understood, tested, and changed independently.
def _render_deployment_info() -> None:
    """Support the Streamlit presentation layer by performing render deployment info.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    health = _load_backend_health()
    api_base = st.session_state.get("api_base", "")
    info = {
        "Environment": _environment_label(api_base),
        "API Base": api_base,
        "Backend Health": health.get("status", "unknown") if isinstance(health, dict) else "unknown",
        "Backend Version": health.get("version", "n/a") if isinstance(health, dict) else "n/a",
        "Collection": health.get("active_collection", "n/a") if isinstance(health, dict) else "n/a",
    }
    cards_html = "".join(
        f"""
        <div class="config-item">
            <div class="config-key">{label}</div>
            <div class="config-value">{value}</div>
        </div>
        """
        for label, value in info.items()
    )
    st.markdown("### Deployment Info")
    st.markdown(
        f"""
        <div class="config-grid">
            {cards_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# Learner note: Encapsulates render sidebar so this responsibility can be understood, tested, and changed independently.
def _render_sidebar() -> None:
    """Support the Streamlit presentation layer by performing render sidebar.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    st.sidebar.markdown("## Control Panel")
    st.session_state["api_base"] = st.sidebar.text_input(
        "API Base URL",
        value=st.session_state["api_base"],
    )
    docs_base = st.session_state["api_base"].rstrip("/")
    st.sidebar.caption(f"Swagger: {docs_base}/docs")

    if st.sidebar.button("Ping Backend", use_container_width=True):
        dependency_access = bool(
            st.session_state.get("token") and st.session_state.get("is_admin")
        )
        health_path = "/admin/health" if dependency_access else "/health"
        status, data = _request("GET", health_path, timeout=8.0)
        if status == 200 and isinstance(data, dict):
            st.session_state["backend_health"] = data
            st.sidebar.success(
                "Dependencies checked" if dependency_access else "Backend reachable"
            )
        else:
            st.sidebar.error(f"Health failed: {_error_text(data)}")

    health_payload = st.session_state.get("backend_health")
    if isinstance(health_payload, dict):
        _render_health_card(health_payload)
        if not (st.session_state.get("token") and st.session_state.get("is_admin")):
            st.sidebar.caption("Log in as an admin to check PostgreSQL, Qdrant, Redis, and S3.")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Session")
    if st.session_state["token"]:
        st.sidebar.success(
            f"Logged in as {st.session_state['username']}"
            + (" (admin)" if st.session_state["is_admin"] else "")
        )
        if st.sidebar.button("Logout", use_container_width=True):
            _clear_auth()
            st.rerun()
    else:
        st.sidebar.info("Not logged in")

    history = st.session_state.get("query_history", [])
    if history:
        st.sidebar.markdown("---")
        st.sidebar.markdown("### Recent Queries")
        for item in reversed(history[-5:]):
            st.sidebar.caption(
                f"{item['route'].upper()} | "
                f"{'cache' if item['cache_hit'] else 'fresh'} | "
                f"{item['question'][:42]}"
            )


# Learner note: Encapsulates render hero so this responsibility can be understood, tested, and changed independently.
def _render_hero() -> None:
    """Support the Streamlit presentation layer by performing render hero.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    st.markdown(
        """
        <div class="hero">
            <div class="hero-inner">
                <div class="hero-title">Enterprise Advanced RAG</div>
                <div class="hero-subtitle">
                    Hybrid retrieval, human-in-the-loop SQL approval, layered guardrails,
                    caching, and admin observability in one production-minded workflow.
                </div>
                <div class="hero-pills">
                    <span class="pill">Hybrid + Rerank</span>
                    <span class="pill">CRAG</span>
                    <span class="pill">HyDE</span>
                    <span class="pill">Self-RAG</span>
                    <span class="pill">Text-to-SQL + HITL</span>
                    <span class="pill">sqlglot Safety</span>
                    <span class="pill">9-Layer Guardrails</span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# Learner note: Encapsulates render auth so this responsibility can be understood, tested, and changed independently.
def _render_auth() -> None:
    """Support the Streamlit presentation layer by performing render auth.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    st.markdown("### Authentication")
    left, right = st.columns(2)

    with left:
        st.markdown("#### Login")
        with st.form("login_form"):
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Login", use_container_width=True)
        if submitted:
            status, data = _request(
                "POST",
                "/auth/login",
                json_body={"username": username, "password": password},
            )
            if status == 200 and isinstance(data, dict) and data.get("token"):
                _handle_login_token(data["token"], username)
                st.success("Login successful")
                st.rerun()
            else:
                st.error(f"Login failed: {_error_text(data)}")

    with right:
        st.markdown("#### Register")
        with st.form("register_form"):
            username = st.text_input("Username", key="register_username")
            password = st.text_input("Password", type="password", key="register_password")
            submitted = st.form_submit_button("Register", use_container_width=True)
        if submitted:
            status, data = _request(
                "POST",
                "/auth/register",
                json_body={"username": username, "password": password},
            )
            if status in {200, 201} and isinstance(data, dict) and data.get("token"):
                _handle_login_token(data["token"], username)
                st.success("Registration successful")
                st.rerun()
            else:
                st.error(f"Registration failed: {_error_text(data)}")


# Learner note: Encapsulates render metrics row so this responsibility can be understood, tested, and changed independently.
def _render_metrics_row(payload: dict[str, Any]) -> None:
    """Support the Streamlit presentation layer by performing render metrics row.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    meta = payload.get("metadata", {}) or {}
    route = str(meta.get("route", "rag")).upper()
    confidence = payload.get("confidence", 0.0)
    cache_hit = payload.get("cache_hit", False)
    sources = payload.get("sources", [])
    cost_saved = payload.get("cost_saved", "$0.00")
    llm_cost_saved = payload.get("llm_cost_saved", "$0.00")
    infra_cost_saved = payload.get("infra_cost_saved", "$0.00")
    st.markdown(
        f"""
        <div class="metric-strip">
            <div class="metric-card">
                <div class="metric-label">Route</div>
                <div class="metric-value">{route}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Confidence</div>
                <div class="metric-value">{confidence:.0%}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Cache</div>
                <div class="metric-value">{'Hit' if cache_hit else 'Fresh'}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Sources</div>
                <div class="metric-value">{len(sources)}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Cost Saved</div>
                <div class="metric-value">{cost_saved}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">LLM Saved</div>
                <div class="metric-value">{llm_cost_saved}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Infra Saved</div>
                <div class="metric-value">{infra_cost_saved}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# Learner note: Encapsulates format meta value so this responsibility can be understood, tested, and changed independently.
def _format_meta_value(value: Any) -> str:
    """Support the Streamlit presentation layer by performing format meta value.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


# Learner note: Encapsulates render metadata summary so this responsibility can be understood, tested, and changed independently.
def _render_metadata_summary(payload: dict[str, Any]) -> None:
    """Support the Streamlit presentation layer by performing render metadata summary.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    meta = payload.get("metadata", {}) or {}
    summary_items = [
        ("Reflection Score", meta.get("reflection_score")),
        ("Reflection Iterations", meta.get("reflection_iterations")),
        ("Refined Question", meta.get("refined_question")),
        ("Retrieval Question", meta.get("retrieval_question")),
        ("CRAG Score", meta.get("crag_score")),
        ("CRAG Label", meta.get("crag_label")),
        ("CRAG Relevant Chunks", meta.get("crag_relevant_chunks")),
        ("CRAG Total Chunks", meta.get("crag_total_chunks")),
        ("CRAG Relevant Ratio", meta.get("crag_relevant_ratio")),
        ("Needs Clarification", meta.get("needs_clarification")),
        ("Clarification Type", meta.get("clarification_type")),
        ("Web Fallback", meta.get("used_web_fallback")),
    ]
    visible_items = [item for item in summary_items if item[1] is not None]
    if not visible_items:
        return

    cards_html = "".join(
        f"""
        <div class="meta-card">
            <div class="meta-label">{label}</div>
            <div class="meta-value">{_format_meta_value(value)}</div>
        </div>
        """
        for label, value in visible_items
    )
    st.markdown(
        f"""
        <div class="meta-strip">
            {cards_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# Learner note: Encapsulates render answer card so this responsibility can be understood, tested, and changed independently.
def _render_answer_card(payload: dict[str, Any]) -> None:
    """Support the Streamlit presentation layer by performing render answer card.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    meta = payload.get("metadata", {}) or {}
    sources = payload.get("sources", [])
    chunks = meta.get("retrieved_chunks") or []
    response_tab, sources_tab, chunks_tab, metadata_tab, raw_tab = st.tabs(
        ["Answer", "Sources", "Chunks", "Metadata", "Raw JSON"]
    )

    with response_tab:
        _render_metrics_row(payload)
        _render_metadata_summary(payload)
        st.markdown("#### Final Answer")
        st.write(payload.get("answer", ""))

    with sources_tab:
        if sources:
            for idx, source in enumerate(sources, 1):
                label, kind = _display_source_label(source)
                with st.container(border=True):
                    st.markdown(f"**{idx}. {label}**")
                    st.caption(kind)
                    with st.expander("Raw source", expanded=False):
                        st.code(str(source))
        else:
            st.info("No sources returned.")

    with chunks_tab:
        if chunks:
            for idx, chunk in enumerate(chunks, 1):
                with st.container(border=True):
                    st.markdown(f"**{idx}. {chunk.get('source', '?')}**")
                    score_parts = []
                    if chunk.get("score") is not None:
                        score_parts.append(f"score={chunk.get('score')}")
                    if chunk.get("retrieval_score") is not None:
                        score_parts.append(f"retrieval={chunk.get('retrieval_score')}")
                    if chunk.get("rerank_score") is not None:
                        score_parts.append(f"rerank={chunk.get('rerank_score')}")
                    if score_parts:
                        st.caption(" | ".join(score_parts))
                    st.write(chunk.get("text", ""))
        else:
            st.info("No retrieved chunk previews available.")

    with metadata_tab:
        summary_fields = {
            "route": meta.get("route"),
            "cache_hit": payload.get("cache_hit"),
            "cost_saved": payload.get("cost_saved"),
            "llm_cost_saved": payload.get("llm_cost_saved"),
            "infra_cost_saved": payload.get("infra_cost_saved"),
            "reflection_iterations": meta.get("reflection_iterations"),
            "reflection_score": meta.get("reflection_score"),
            "refined_question": meta.get("refined_question"),
            "crag_score": meta.get("crag_score"),
            "crag_label": meta.get("crag_label"),
            "crag_relevant_chunks": meta.get("crag_relevant_chunks"),
            "crag_total_chunks": meta.get("crag_total_chunks"),
            "crag_relevant_ratio": meta.get("crag_relevant_ratio"),
            "crag_chunk_scores": meta.get("crag_chunk_scores", []),
            "needs_clarification": meta.get("needs_clarification"),
            "clarification_question": meta.get("clarification_question"),
            "clarification_reason": meta.get("clarification_reason"),
            "used_web_fallback": meta.get("used_web_fallback"),
        }
        st.json(summary_fields)

    with raw_tab:
        st.json(payload)


# Learner note: Encapsulates record query history so this responsibility can be understood, tested, and changed independently.
def _record_query_history(question: str, payload: dict[str, Any]) -> None:
    """Support the Streamlit presentation layer by performing record query history.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    meta = payload.get("metadata", {}) or {}
    history = st.session_state.get("query_history", [])
    history.append(
        {
            "question": question,
            "answer": payload.get("answer", ""),
            "sources": payload.get("sources", []),
            "route": meta.get("route", "rag"),
            "cache_hit": payload.get("cache_hit", False),
            "confidence": payload.get("confidence", 0.0),
        }
    )
    st.session_state["query_history"] = history[-20:]
    if payload.get("answer"):
        context_turns = st.session_state.get("conversation_context", [])
        context_turns.append(
            {
                "question": question,
                "answer": payload.get("answer", ""),
                "sources": payload.get("sources", []),
            }
        )
        st.session_state["conversation_context"] = context_turns[-3:]


# Learner note: Encapsulates submit sql approval so this responsibility can be understood, tested, and changed independently.
def _submit_sql_approval(approved: bool) -> None:
    """Support the Streamlit presentation layer by performing submit sql approval.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    pending = st.session_state.get("pending_sql")
    if not pending:
        st.error("No pending SQL approval found.")
        return

    payload = {
        "query_id": pending["query_id"],
        "approved": approved,
    }
    status, data = _request("POST", "/query/sql/execute", json_body=payload)
    if status == 200 and isinstance(data, dict):
        st.session_state["last_query_response"] = data
        st.session_state["pending_sql"] = None
        st.success("SQL approval submitted")
        st.rerun()
    else:
        detail_text = _error_text(data)
        if status == 409 and (
            "sql_approval_context_missing" in detail_text
            or "sql_approval_not_pending" in detail_text
        ):
            st.session_state["pending_sql"] = None
            st.warning(
                "This SQL approval request is no longer valid, usually because the "
                "backend restarted or a deployment replaced the in-memory workflow. "
                "Re-run the query to generate a fresh approval request."
            )
        st.error(f"SQL approval failed ({status}): {_error_text(data)}")


# Learner note: Encapsulates render pending sql panel so this responsibility can be understood, tested, and changed independently.
def _render_pending_sql_panel(response: dict[str, Any]) -> None:
    """Support the Streamlit presentation layer by performing render pending sql panel.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    pending = response["pending_sql"]
    st.markdown("#### SQL Approval Required")
    st.code(pending.get("sql", ""), language="sql")
    if pending.get("explanation"):
        st.caption(pending["explanation"])
    col1, col2 = st.columns(2)
    if col1.button("Approve SQL", use_container_width=True, type="primary"):
        _submit_sql_approval(True)
    if col2.button("Reject SQL", use_container_width=True):
        _submit_sql_approval(False)
    with st.expander("Pending SQL JSON", expanded=False):
        st.json(response)


# Learner note: Encapsulates render query tab so this responsibility can be understood, tested, and changed independently.
def _render_query_tab() -> None:
    """Support the Streamlit presentation layer by performing render query tab.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    chosen = st.selectbox(
        "Preset Query",
        list(USE_CASES.keys()),
        index=list(USE_CASES.keys()).index(st.session_state["selected_use_case"]),
    )
    st.session_state["selected_use_case"] = chosen
    preset = USE_CASES[chosen]

    if st.session_state.get("query_form_seed") != chosen:
        st.session_state["query_question"] = preset["question"]
        st.session_state["query_top_k"] = int(preset["top_k"])
        st.session_state["query_search_mode"] = preset["search_mode"]
        st.session_state["query_enable_rerank"] = bool(preset["enable_rerank"])
        st.session_state["query_enable_hyde"] = bool(preset["enable_hyde"])
        st.session_state["query_enable_crag"] = bool(preset["enable_crag"])
        st.session_state["query_enable_self_reflective"] = bool(
            preset["enable_self_reflective"]
        )
        st.session_state["query_form_seed"] = chosen

    st.markdown(
        f"<div class='small-note'>{preset['label']}</div>",
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.25, 1.0], gap="large")
    with left:
        st.markdown("### Kubernetes IT-Operations Copilot")
        ui_mode = st.radio(
            "Experience Mode",
            ["Auto", "Manual"],
            horizontal=True,
            key="query_ui_mode",
            help="Auto hides retrieval controls and lets the backend choose. Manual exposes full retrieval tuning for side-by-side demo use.",
        )
        if ui_mode == "Auto":
            st.caption(
                "Auto mode uses backend-owned retrieval selection. Manual CRAG/HyDE/SRAG toggles are hidden in this mode."
            )
        with st.form("query_form"):
            question = st.text_area(
                "Question",
                height=170,
                key="query_question",
            )
            top_k = st.slider("Top K", min_value=1, max_value=20, key="query_top_k")
            if ui_mode == "Auto":
                search_mode = "auto"
                enable_rerank = False
                enable_hyde = False
                enable_crag = False
                enable_self_reflective = False
            else:
                search_mode = st.selectbox(
                    "Search Mode",
                    ["dense", "sparse", "hybrid"],
                    key="query_search_mode",
                )
                col1, col2 = st.columns(2)
                with col1:
                    enable_rerank = st.checkbox("Enable Rerank", key="query_enable_rerank")
                    enable_hyde = st.checkbox("Enable HyDE", key="query_enable_hyde")
                with col2:
                    enable_crag = st.checkbox("Enable CRAG", key="query_enable_crag")
                    enable_self_reflective = st.checkbox(
                        "Enable SRAG",
                        key="query_enable_self_reflective",
                    )
            submitted = st.form_submit_button("Run Query", use_container_width=True)

        if submitted:
            payload = {
                "question": question,
                "top_k": top_k,
                "search_mode": search_mode,
                "enable_rerank": enable_rerank,
                "enable_hyde": enable_hyde,
                "enable_crag": enable_crag,
                "enable_self_reflective": enable_self_reflective,
                "conversation_context": st.session_state.get("conversation_context", []),
            }
            status, data = _request("POST", "/query", json_body=payload)
            if status == 200 and isinstance(data, dict):
                st.session_state["last_query_response"] = data
                st.session_state["pending_sql"] = data.get("pending_sql")
                _record_query_history(question, data)
                st.success("Query completed")
            else:
                st.error(f"Query failed ({status}): {_error_text(data)}")

    with right:
        st.markdown("### Query Strategy")
        st.markdown(
            "\n".join(
                [
                    "- `Auto` is the best production default",
                    "- `Manual` is useful for retrieval strategy demos",
                    "- `hybrid + rerank` is the best manual default",
                    "- Use `CRAG` for weak or uncertain retrieval",
                    "- Use `HyDE` for semantic / paraphrased queries",
                    "- Use `SRAG` sparingly because of extra latency",
                ]
            )
        )
        response = st.session_state.get("last_query_response") or {}
        response_meta = response.get("metadata", {}) or {}
        active_ui_mode = st.session_state.get("query_ui_mode", "Auto")
        active_top_k = st.session_state.get("query_top_k", preset["top_k"])
        if active_ui_mode == "Auto" and response_meta.get("auto_enabled"):
            active_search_mode = response_meta.get("resolved_search_mode", "auto")
            active_rerank = "On" if response_meta.get("resolved_enable_rerank") else "Off"
            active_crag = "On" if response_meta.get("resolved_enable_crag") else "Off"
            active_hyde = "On" if response_meta.get("resolved_enable_hyde") else "Off"
            active_srag = "On" if response_meta.get("resolved_enable_self_reflective") else "Off"
        else:
            active_search_mode = (
                "auto"
                if active_ui_mode == "Auto"
                else st.session_state.get("query_search_mode", preset["search_mode"])
            )
            active_rerank = (
                "Backend-managed"
                if active_ui_mode == "Auto"
                else ("On" if st.session_state.get("query_enable_rerank", preset["enable_rerank"]) else "Off")
            )
            active_crag = (
                "Backend-managed"
                if active_ui_mode == "Auto"
                else ("On" if st.session_state.get("query_enable_crag", preset["enable_crag"]) else "Off")
            )
            active_hyde = (
                "Backend-managed"
                if active_ui_mode == "Auto"
                else ("On" if st.session_state.get("query_enable_hyde", preset["enable_hyde"]) else "Off")
            )
            active_srag = (
                "Backend-managed"
                if active_ui_mode == "Auto"
                else ("On" if st.session_state.get("query_enable_self_reflective", preset["enable_self_reflective"]) else "Off")
        )
        _render_deployment_info()
        st.markdown("### Active Config")
        st.markdown(
            f"""
            <div class="config-grid">
                <div class="config-item">
                    <div class="config-key">Experience Mode</div>
                    <div class="config-value">{active_ui_mode}</div>
                </div>
                <div class="config-item">
                    <div class="config-key">Search Mode</div>
                    <div class="config-value">{active_search_mode}</div>
                </div>
                <div class="config-item">
                    <div class="config-key">Top K</div>
                    <div class="config-value">{active_top_k}</div>
                </div>
                <div class="config-item">
                    <div class="config-key">Rerank</div>
                    <div class="config-value">{active_rerank}</div>
                </div>
                <div class="config-item">
                    <div class="config-key">CRAG</div>
                    <div class="config-value">{active_crag}</div>
                </div>
                <div class="config-item">
                    <div class="config-key">HyDE</div>
                    <div class="config-value">{active_hyde}</div>
                </div>
                <div class="config-item">
                    <div class="config-key">SRAG</div>
                    <div class="config-value">{active_srag}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    response = st.session_state.get("last_query_response")
    if response:
        st.markdown("---")
        if response.get("pending_sql"):
            _render_pending_sql_panel(response)
        else:
            _render_answer_card(response)


# Learner note: Encapsulates render upload tab so this responsibility can be understood, tested, and changed independently.
def _render_upload_tab() -> None:
    """Support the Streamlit presentation layer by performing render upload tab.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    st.markdown("### Document Upload")
    st.caption("Corpus ingestion is restricted to admin users.")
    uploaded = st.file_uploader(
        "Choose a file",
        type=["pdf", "txt", "md", "docx"],
    )
    if st.button("Upload Document", use_container_width=True, disabled=uploaded is None):
        if uploaded is None:
            st.error("Select a file first.")
            return
        files = {
            "file": (uploaded.name, uploaded.getvalue(), uploaded.type or "application/octet-stream")
        }
        status, data = _request("POST", "/documents/upload", files=files, timeout=120.0)
        if status == 200 and isinstance(data, dict):
            st.success("Upload processed")
            st.json(data)
        else:
            st.error(f"Upload failed ({status}): {_error_text(data)}")


# Learner note: Encapsulates render history tab so this responsibility can be understood, tested, and changed independently.
def _render_history_tab() -> None:
    """Support the Streamlit presentation layer by performing render history tab.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    st.markdown("### Query History")
    history = st.session_state.get("query_history", [])
    if not history:
        st.info("No queries yet.")
        return

    for item in reversed(history):
        with st.container(border=True):
            st.markdown(f"**{item['question']}**")
            st.caption(
                f"route={item['route']} | "
                f"confidence={item['confidence']:.0%} | "
                f"cache_hit={item['cache_hit']}"
            )


# Learner note: Encapsulates admin action request so this responsibility can be understood, tested, and changed independently.
def _admin_action_request(action: str, username: str) -> tuple[int, Any]:
    """Support the Streamlit presentation layer by performing admin action request.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    if action == "health":
        return _request("GET", "/admin/health")
    if action == "cache_stats":
        return _request("GET", "/admin/cache/stats")
    if action == "runtime_info":
        return _request("GET", "/admin/runtime-info")
    if action == "budgets":
        return _request("GET", "/admin/budgets")
    if action == "clear_all_cache":
        return _request("POST", "/admin/cache/clear", json_body={"tier": "all"})
    return _request("GET", f"/admin/rate-limits/{username}")


# Learner note: Encapsulates render admin tab so this responsibility can be understood, tested, and changed independently.
def _render_admin_tab() -> None:
    """Support the Streamlit presentation layer by performing render admin tab.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    st.markdown("### Admin Console")
    st.caption("Operational inspection for cache, runtime, budgets, and rate limits.")

    left, right = st.columns([1.0, 1.2], gap="large")
    with left:
        action = st.selectbox(
            "Admin Action",
            [
                "health",
                "cache_stats",
                "runtime_info",
                "budgets",
                "clear_all_cache",
                "rate_limit_user",
            ],
        )
        if action == "rate_limit_user":
            username = st.text_input(
                "Username to inspect",
                value=st.session_state.get("username", ""),
            )
        else:
            username = ""

        st.markdown(
            "\n".join(
                [
                    "- `health`: backend dependency status",
                    "- `cache_stats`: tier-level hit/miss counters",
                    "- `runtime_info`: code/runtime diagnostics",
                    "- `budgets`: token budget visibility",
                    "- `clear_all_cache`: reset in-memory cache",
                    "- `rate_limit_user`: inspect current user window",
                ]
            )
        )

        run = st.button("Run Admin Action", use_container_width=True, type="primary")

    with right:
        if run:
            status, data = _admin_action_request(action, username)
            if status == 200:
                st.success("Admin action completed")
                st.json(data)
            else:
                st.error(f"Admin action failed ({status}): {_error_text(data)}")
        else:
            st.info("Choose an action and run it to inspect backend state.")


# Learner note: Orchestrates main, making this function a clear execution boundary for learners and tests.
def main() -> None:
    """Perform main for the Streamlit presentation layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    st.set_page_config(
        page_title="Enterprise Advanced RAG",
        page_icon="AI",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _init_state()
    _inject_styles()
    _render_sidebar()
    _render_hero()

    if not st.session_state["token"]:
        _render_auth()
        return

    query_tab, upload_tab, history_tab, admin_tab = st.tabs(
        ["Query", "Upload", "History", "Admin"]
    )

    with query_tab:
        _render_query_tab()

    with upload_tab:
        if st.session_state["is_admin"]:
            _render_upload_tab()
        else:
            st.info("Admin access required for document upload.")

    with history_tab:
        _render_history_tab()

    with admin_tab:
        if st.session_state["is_admin"]:
            _render_admin_tab()
        else:
            st.info("Admin access required for this tab.")


if __name__ == "__main__":
    main()
