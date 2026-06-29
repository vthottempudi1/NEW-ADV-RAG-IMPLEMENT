# New Advanced RAG Implement

Production-minded enterprise RAG backend with security and guardrails, hybrid retrieval, SQL routing, and advanced evaluation-oriented retrieval workflows.

Enterprise-style Advanced RAG system built with FastAPI, Qdrant, PostgreSQL, Redis-style caching, and LangGraph-style routing, with support for Dense, Sparse, Hybrid, HyDE, CRAG, Self-Reflective RAG(SRAG), and reranking workflows.

## Overview

This project is a production-minded Retrieval-Augmented Generation (RAG) backend that combines document retrieval, structured SQL access, security and guardrails, caching, and orchestration.

## Why This Project Matters

Most RAG demos stop at simple document retrieval and answer generation. This project is designed to go further by combining:

- unstructured document retrieval
- structured SQL access
- hybrid routing between retrieval and database queries
- security and guardrails
- caching and operational controls
- evaluation-oriented retrieval strategies such as HyDE, CRAG, and SRAG

That makes it closer to a real enterprise AI backend than a basic chatbot demo.

Core capabilities:

- document upload and ingestion
- duplicate-document detection
- chunking and embedding
- vector search with Qdrant
- SQL routing for structured questions
- hybrid SQL + RAG answering
- JWT authentication
- rate limiting and token budgets
- query and embedding cache
- admin endpoints
- automated tests
- GitHub Actions CI

## Retrieval Strategies

This project supports multiple retrieval and answer-generation strategies during development and evaluation:

- **Dense retrieval**: semantic vector search over embedded chunks
- **Sparse retrieval**: lexical / keyword-oriented retrieval
- **Hybrid retrieval**: combines dense and sparse signals
- **HyDE**: generates a hypothetical answer/document to improve retrieval
- **CRAG**: grades retrieval quality and supports corrective behavior
- **Self-Reflective RAG (SRAG)**: reviews answer quality and can refine generation
- **Reranking**: improves the final ordering of retrieved chunks

These techniques are intentionally exposed as controllable options in development. In production, the better design is to let backend policy decide when to use them based on query type, retrieval quality, latency, and cost.

## Tech Stack

- FastAPI
- Python 3.12
- Qdrant
- PostgreSQL
- Upstash Redis with in-memory fallback
- OpenAI
- LangGraph
- Docker
- Pytest
- GitHub Actions

## Current Status

Implemented and tested:

- document ingestion
- duplicate upload skip
- dense / sparse / hybrid retrieval
- HyDE, CRAG, SRAG, and reranking support
- SQL route
- hybrid route
- auth and admin protection
- rate limiting and token budget controls
- CI pipeline

## Architecture

High-level architecture:

1. **API layer**: FastAPI routes for auth, query, admin, and document upload
2. **Security and guardrails layer**: JWT auth, admin checks, rate limiting, input checks, moderation, output validation, and token budgets
3. **Routing and orchestration layer**: intent routing and graph-based flow for `rag`, `sql`, and `hybrid`
4. **Retrieval layer**: dense, sparse, hybrid, HyDE, CRAG, SRAG, and reranking logic
5. **Data layer**:
   - Qdrant for vector search
   - PostgreSQL for structured data and user records
   - Redis-style cache for query and embedding caching
6. **Observability and operations layer**: cache stats, budget visibility, health checks, and CI

### Architecture Diagram

```text
User / Client
     |
     v
FastAPI API Layer
  |-- /auth
  |-- /documents/upload
  |-- /query
  |-- /admin
     |
     v
Security and Guardrails
  |-- JWT auth
  |-- rate limiting
  |-- input checks
  |-- moderation
  |-- output validation
  |-- token budgets
     |
     v
Router / Graph Orchestration
  |-- RAG route
  |-- SQL route
  |-- Hybrid route
     |
     +------------------------+
     |                        |
     v                        v
Retrieval Layer           SQL Layer
  |-- dense                  |-- schema context
  |-- sparse                 |-- SQL generation
  |-- hybrid                 |-- safe execution
  |-- HyDE
  |-- CRAG
  |-- SRAG
  |-- reranking
     |                        |
     +-----------+------------+
                 |
                 v
            LLM Response
                 |
                 v
        Response + Metadata

Supporting systems:
- Qdrant for vector storage and retrieval
- PostgreSQL for structured data and auth data
- Redis-style cache for query/embedding cache
- GitHub Actions for CI
```

## Project Structure

```text
app/
  api/
  core/
  middleware/
  security/
  services/
  storage/
tests/
.github/workflows/
```

## Request Flow

1. User sends a request to `/query`
2. Auth, rate limit, and guardrail checks run
3. Router selects `rag`, `sql`, or `hybrid`
4. Retrieval and/or SQL execution runs
5. LLM generates the final response
6. Metadata, cache state, and confidence are returned

## Example Use Cases

- enterprise document question answering
- structured data lookup through SQL generation
- hybrid enterprise assistants that combine documents and database records
- domain-specific copilots for regulated industries such as life sciences

## Setup

### 1. Create a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

### 2. Install dependencies

```powershell
pip install -e ".[dev]"
```

### 3. Configure environment

Copy `.env.example` to `.env` and update:

- `OPENAI_API_KEY`
- `DATABASE_URL`
- `QDRANT_URL`
- `QDRANT_COLLECTION`
- `UPSTASH_REDIS_URL` and `UPSTASH_REDIS_TOKEN` if used
- `JWT_SECRET`
- `TAVILY_API_KEY` if using web fallback

### 4. Start infrastructure

```powershell
docker compose up -d
```

This starts:

- PostgreSQL
- Qdrant

### 5. Run the API

```powershell
python -m uvicorn app.main:app --reload --port 8002
```

Open:

- `http://localhost:8002/docs`
- `http://localhost:8002/health`

## API Highlights

Main endpoints:

- `POST /auth/register`
- `POST /auth/login`
- `POST /documents/upload`
- `POST /query`
- `GET /health`

Additional admin endpoints support health checks, cache visibility, budget visibility, and operational inspection.

## Testing

Run tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## CI

GitHub Actions runs the test suite automatically on push and pull request to `main`.

## Future Improvements

- add architecture diagrams or screenshots for `/docs`, ingestion flow, and query flow
- harden SQL validation with AST-based parsing using `sqlglot`
- expand production deployment with container registry and Kubernetes manifests
- add richer observability and cost tracking
- add department-aware multi-tenant controls for enterprise use cases
