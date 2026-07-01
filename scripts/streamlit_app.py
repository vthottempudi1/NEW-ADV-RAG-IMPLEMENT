import json
from typing import Any

import httpx
import jwt
import streamlit as st


DEFAULT_API_BASE = "http://localhost:8003"

USE_CASES: dict[str, dict[str, Any]] = {
    "Hybrid Default": {
        "question": "How many P1 incidents breached SLA last month and what is our escalation policy?",
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
        "question": "how do i scale",
        "search_mode": "hybrid",
        "enable_rerank": True,
        "enable_hyde": False,
        "enable_crag": False,
        "enable_self_reflective": True,
        "top_k": 5,
        "label": "Reflection / regeneration",
    },
}


def _init_state() -> None:
    st.session_state.setdefault("api_base", DEFAULT_API_BASE)
    st.session_state.setdefault("token", "")
    st.session_state.setdefault("is_admin", False)
    st.session_state.setdefault("username", "")
    st.session_state.setdefault("last_query_response", None)
    st.session_state.setdefault("pending_sql", None)
    st.session_state.setdefault("query_history", [])
    st.session_state.setdefault("selected_use_case", "Hybrid Default")


def _inject_styles() -> None:
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
            grid-template-columns: repeat(5, minmax(0, 1fr));
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


def _auth_headers() -> dict[str, str]:
    token = st.session_state.get("token", "")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _decode_token(token: str) -> dict[str, Any]:
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


def _handle_login_token(token: str, username: str) -> None:
    payload = _decode_token(token)
    st.session_state["token"] = token
    st.session_state["username"] = username
    st.session_state["is_admin"] = bool(payload.get("is_admin", False))


def _clear_auth() -> None:
    st.session_state["token"] = ""
    st.session_state["username"] = ""
    st.session_state["is_admin"] = False
    st.session_state["pending_sql"] = None


def _request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> tuple[int, Any]:
    url = st.session_state["api_base"].rstrip("/") + path
    headers = _auth_headers()
    with httpx.Client(timeout=timeout) as client:
        response = client.request(
            method,
            url,
            json=json_body,
            files=files,
            headers=headers,
        )
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, response.text


def _badge(label: str, kind: str = "blue") -> str:
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


def _render_surface_header(title: str, caption: str) -> None:
    st.markdown(
        f"""
        <div class="surface">
            <div class="section-title">{title}</div>
            <div class="section-caption">{caption}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_health_card(payload: dict[str, Any]) -> None:
    status = payload.get("status", "unknown")
    active_collection = payload.get("active_collection", "n/a")
    st.sidebar.markdown(
        _badge(f"health: {status}", "green" if status == "ok" else "yellow"),
        unsafe_allow_html=True,
    )
    st.sidebar.caption(f"collection: {active_collection}")


def _render_sidebar() -> None:
    st.sidebar.markdown("## Control Panel")
    st.session_state["api_base"] = st.sidebar.text_input(
        "API Base URL",
        value=st.session_state["api_base"],
    )
    docs_base = st.session_state["api_base"].rstrip("/")
    st.sidebar.caption(f"Swagger: {docs_base}/docs")

    if st.sidebar.button("Ping Backend", use_container_width=True):
        status, data = _request("GET", "/health")
        if status == 200 and isinstance(data, dict):
            _render_health_card(data)
            st.sidebar.success("Backend reachable")
        else:
            st.sidebar.error(f"Health failed: {data}")

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


def _render_hero() -> None:
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


def _render_auth() -> None:
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
                st.error(f"Login failed: {data}")

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
                st.error(f"Registration failed: {data}")


def _render_metrics_row(payload: dict[str, Any]) -> None:
    meta = payload.get("metadata", {}) or {}
    route = str(meta.get("route", "rag")).upper()
    confidence = payload.get("confidence", 0.0)
    cache_hit = payload.get("cache_hit", False)
    sources = payload.get("sources", [])
    cost_saved = payload.get("cost_saved", "$0.00")
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
        </div>
        """,
        unsafe_allow_html=True,
    )


def _format_meta_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _render_metadata_summary(payload: dict[str, Any]) -> None:
    meta = payload.get("metadata", {}) or {}
    summary_items = [
        ("Reflection Score", meta.get("reflection_score")),
        ("Reflection Iterations", meta.get("reflection_iterations")),
        ("Refined Question", meta.get("refined_question")),
        ("CRAG Score", meta.get("crag_score")),
        ("CRAG Label", meta.get("crag_label")),
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


def _render_answer_card(payload: dict[str, Any]) -> None:
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
                st.markdown(f"{idx}. `{source}`")
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
            "reflection_iterations": meta.get("reflection_iterations"),
            "reflection_score": meta.get("reflection_score"),
            "refined_question": meta.get("refined_question"),
            "crag_score": meta.get("crag_score"),
            "crag_label": meta.get("crag_label"),
            "used_web_fallback": meta.get("used_web_fallback"),
        }
        st.json(summary_fields)

    with raw_tab:
        st.json(payload)


def _record_query_history(question: str, payload: dict[str, Any]) -> None:
    meta = payload.get("metadata", {}) or {}
    history = st.session_state.get("query_history", [])
    history.append(
        {
            "question": question,
            "route": meta.get("route", "rag"),
            "cache_hit": payload.get("cache_hit", False),
            "confidence": payload.get("confidence", 0.0),
        }
    )
    st.session_state["query_history"] = history[-20:]


def _submit_sql_approval(approved: bool) -> None:
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
        st.error(f"SQL approval failed ({status}): {data}")


def _render_pending_sql_panel(response: dict[str, Any]) -> None:
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


def _render_query_tab() -> None:
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
        with st.form("query_form"):
            question = st.text_area(
                "Question",
                height=170,
                key="query_question",
            )
            top_k = st.slider("Top K", min_value=1, max_value=20, key="query_top_k")
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
            }
            status, data = _request("POST", "/query", json_body=payload)
            if status == 200 and isinstance(data, dict):
                st.session_state["last_query_response"] = data
                st.session_state["pending_sql"] = data.get("pending_sql")
                _record_query_history(question, data)
                st.success("Query completed")
            else:
                st.error(f"Query failed ({status}): {data}")

    with right:
        st.markdown("### Query Strategy")
        st.markdown(
            "\n".join(
                [
                    "- `hybrid + rerank` is the best default",
                    "- Use `CRAG` for weak or uncertain retrieval",
                    "- Use `HyDE` for semantic / paraphrased queries",
                    "- Use `SRAG` sparingly because of extra latency",
                ]
            )
        )
        st.markdown("### Active Config")
        st.markdown(
            f"""
            <div class="config-grid">
                <div class="config-item">
                    <div class="config-key">Search Mode</div>
                    <div class="config-value">{st.session_state.get("query_search_mode", preset["search_mode"])}</div>
                </div>
                <div class="config-item">
                    <div class="config-key">Top K</div>
                    <div class="config-value">{st.session_state.get("query_top_k", preset["top_k"])}</div>
                </div>
                <div class="config-item">
                    <div class="config-key">Rerank</div>
                    <div class="config-value">{'On' if st.session_state.get("query_enable_rerank", preset["enable_rerank"]) else 'Off'}</div>
                </div>
                <div class="config-item">
                    <div class="config-key">CRAG</div>
                    <div class="config-value">{'On' if st.session_state.get("query_enable_crag", preset["enable_crag"]) else 'Off'}</div>
                </div>
                <div class="config-item">
                    <div class="config-key">HyDE</div>
                    <div class="config-value">{'On' if st.session_state.get("query_enable_hyde", preset["enable_hyde"]) else 'Off'}</div>
                </div>
                <div class="config-item">
                    <div class="config-key">SRAG</div>
                    <div class="config-value">{'On' if st.session_state.get("query_enable_self_reflective", preset["enable_self_reflective"]) else 'Off'}</div>
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


def _render_upload_tab() -> None:
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
            st.error(f"Upload failed ({status}): {data}")


def _render_history_tab() -> None:
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


def _admin_action_request(action: str, username: str) -> tuple[int, Any]:
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


def _render_admin_tab() -> None:
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
                st.error(f"Admin action failed ({status}): {data}")
        else:
            st.info("Choose an action and run it to inspect backend state.")


def main() -> None:
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
