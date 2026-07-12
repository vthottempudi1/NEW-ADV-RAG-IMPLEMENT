# Product Requirements Document

## Product

Enterprise Advanced RAG for Kubernetes IT Operations

## Document Status

- Version: 1.0
- Owner: Product Management
- Partner teams: Applied AI, Backend, Frontend, DevOps, Security, QA
- Implementation reference: `new-adv-rag-implement`

---

## 1. Executive Summary

This project delivers an enterprise-style Retrieval-Augmented Generation platform for Kubernetes and IT-operations assistance. The product is designed to answer infrastructure questions from internal documentation, support structured lookups through SQL, combine document retrieval with SQL-based facts when needed, and do so with stronger safety and observability than a basic chatbot demo.

The product solves a common operational problem: teams have fragmented runbooks, platform docs, troubleshooting notes, and structured operational data, but they lack a safe and reliable assistant that can answer questions quickly without hallucinating, exposing unsafe SQL behavior, or becoming impossible to debug in production.

The proposed solution is a multi-route AI assistant with:

- document-based RAG
- SQL routing for structured questions
- hybrid SQL + RAG responses
- human-in-the-loop SQL approval
- auto retrieval strategy selection
- conditional retrieval enhancements such as reranking, HyDE, CRAG, and self-reflective RAG
- production deployment on AWS with CloudWatch observability and load-test evidence

This document is written in a product-manager style and is intended to capture the product problem, requirements, tradeoffs, success criteria, delivery approach, and solution rationale.

---

## 2. Problem Statement

### 2.1 Business Problem

Operations and platform teams lose time when critical knowledge is distributed across:

- Kubernetes documentation
- internal runbooks
- incident policies
- architectural notes
- structured operational datasets

Traditional search is slow and depends on exact keywords. Generic chatbots are unsafe for enterprise usage because they may answer without grounding, may invent facts, and may not handle structured operational questions correctly.

### 2.2 User Problem

Target users need a system that can:

- answer factual Kubernetes and operations questions from trusted sources
- preserve conversational context across follow-up questions
- distinguish between document questions and structured data questions
- combine document guidance with SQL facts when both are needed
- avoid unsafe SQL execution
- provide source visibility and operational transparency

### 2.3 Why Existing Alternatives Are Not Enough

Basic RAG demos typically stop at:

- upload documents
- chunk text
- retrieve semantically similar chunks
- send prompt to an LLM

That approach is insufficient for enterprise operations because it does not address:

- structured data access
- SQL safety
- approval workflows
- follow-up context handling
- retrieval strategy tuning
- production monitoring
- deployment repeatability
- operational debugging under load

---

## 3. Product Vision

Create a production-minded AI copilot that helps technical users resolve Kubernetes and operations questions faster, more safely, and with clear evidence, while remaining explainable, observable, and deployable in a real cloud environment.

---

## 4. Goals And Non-Goals

### 4.1 Product Goals

1. Answer Kubernetes and IT-operations questions using grounded retrieval.
2. Support SQL-backed answers for structured operational data.
3. Support hybrid answers that combine SQL facts with document context.
4. Preserve context for follow-up questions.
5. Reduce hallucination risk through retrieval policy controls and source-backed answers.
6. Prevent unsafe SQL execution through validation and approval gates.
7. Provide production-ready deployment, observability, and test evidence.

### 4.2 Non-Goals

- full autonomous incident remediation
- unrestricted write-capable database actions
- broad internet search as a primary answer path
- replacing all human judgement for production operations
- general-purpose consumer chatbot behavior

---

## 5. Target Users

### Primary Users

- platform engineers
- DevOps engineers
- SREs
- cloud engineers
- technical leads

### Secondary Users

- hiring managers evaluating the project
- interviewers assessing system design depth
- internal demo stakeholders
- engineering leadership reviewing AI readiness

---

## 6. Jobs To Be Done

Users want to:

- understand Kubernetes concepts quickly
- troubleshoot operational problems with grounded documentation
- answer structured operational questions such as counts, incident summaries, or policy-linked metrics
- ask follow-up questions without restating the entire context
- inspect sources and confidence before trusting the answer
- see that the product is stable, monitored, and production-capable

---

## 7. Core Use Cases

### 7.1 RAG Use Cases

- “What is the difference between a ConfigMap and a Secret in Kubernetes?”
- “If I mount a Secret into only one container in a multi-container Pod, can another container read it?”
- “What does ErrImagePull mean and how do I fix it?”

### 7.2 SQL Use Cases

- “How many P1 incidents were resolved last quarter?”
- “How many users are registered?”

### 7.3 Hybrid Use Cases

- “How many P1 incidents were resolved last quarter and what does the escalation policy say for P1 incidents?”

### 7.4 Follow-Up Context Use Cases

- “Would you use that same object for a database password?”
- “For the non-sensitive one, if I inject it as environment variables instead of a volume, will updates show up automatically?”

### 7.5 Troubleshooting And Reflection Use Cases

- “My Kubernetes app keeps restarting, and I am not sure whether the root cause is the liveness probe, OOMKilled, or a bad image. How should I troubleshoot it step by step?”

---

## 8. Product Requirements

## 8.1 Functional Requirements

### FR1: Authentication And User Access

- users must authenticate before querying protected endpoints
- admin flows must be supported where required

### FR2: Document Ingestion

- system must accept document ingestion
- system must chunk content consistently
- embeddings must be created and stored in vector storage
- document metadata must be retained for source attribution

### FR3: Retrieval Modes

- system must support `dense`, `sparse`, and `hybrid` retrieval
- system must support reranking
- system must support optional HyDE
- system must support optional CRAG
- system must support optional self-reflective RAG

### FR4: Auto Retrieval Selection

- system must support `auto` mode
- auto mode must select retrieval strategy based on query characteristics
- auto mode must expose resolved strategy in metadata

### FR5: Conversational Context

- system must support follow-up questions
- system must rewrite ambiguous references such as “that same object” when enough context exists
- rewritten question metadata must be visible for debugging

### FR6: SQL Routing

- system must classify whether a question is better served by RAG, SQL, or hybrid
- system must generate SQL only for allowed read-only use cases
- system must return SQL answers in a user-facing form

### FR7: Hybrid Routing

- system must support routes where SQL provides facts and retrieval provides policy or documentation context
- final answer must unify both outputs coherently

### FR8: SQL Approval

- system must support a pending approval state before SQL execution
- system must return a `pending_sql` block when approval is required
- system must resume execution only after explicit approval through the approval endpoint

### FR9: Source Transparency

- system must show source files or URLs used in the answer
- frontend must present sources in a readable format

### FR10: Admin Observability

- frontend must surface active retrieval configuration
- deployment information should be visible in the UI
- backend health should be visible in the UI

### FR11: Monitoring

- product must support CloudWatch logs, alarms, and dashboards
- dashboard should be screenshot-friendly during load tests

### FR12: Testing

- product must support unit tests
- product must support evaluation workflows
- product must support load testing

## 8.2 Non-Functional Requirements

### NFR1: Safety

- generated SQL must be read-only
- SQL must be validated structurally rather than only by regex
- system must reject unsafe input and unsafe output patterns

### NFR2: Reliability

- deployed services must expose health endpoints
- ECS services must maintain steady-state tasks
- monitoring and alarms must be configured for major services

### NFR3: Performance

- common questions should return within acceptable interactive latency
- load tests must demonstrate stable operation for smoke-level workloads

### NFR4: Explainability

- responses must expose sources
- metadata should reveal route, retrieval mode, and major decision flags

### NFR5: Maintainability

- repo must be clean enough for GitHub usage
- deployment artifacts and documentation must be version-controlled

### NFR6: Portability

- system must run locally with documented dependencies
- system must also deploy to AWS with documented steps

---

## 9. Success Metrics

### User Metrics

- answer usefulness for core Kubernetes questions
- quality of follow-up handling
- source trustworthiness as perceived by users

### System Metrics

- route correctness across RAG, SQL, and hybrid queries
- retrieval relevance
- low unsafe SQL acceptance rate
- low false approval-context failures
- healthy service uptime

### Product Readiness Metrics

- all automated tests passing
- eval smoke workflows passing
- CloudWatch dashboard operational
- load-test smoke runs captured with evidence

---

## 10. Constraints

- SQL must remain read-only
- production infra must stay cost-conscious
- observability must be simple enough for a solo builder to operate
- project must be credible for interview and portfolio review, not only technically functional

---

## 11. Solution Options Considered

### Option A: Basic Dense RAG Only

#### Benefits

- simple to build
- fast demo path

#### Problems

- weak on keyword-heavy operational terms
- no structured data support
- no approval workflow
- low enterprise credibility

### Option B: RAG + SQL Without Hybrid Or Safety Workflow

#### Benefits

- covers both unstructured and structured data

#### Problems

- unsafe SQL risk
- no approval checkpoint
- limited production confidence

### Option C: Enterprise Multi-Route AI Assistant

#### Includes

- dense, sparse, and hybrid retrieval
- reranking
- HyDE
- CRAG
- self-reflective RAG
- SQL routing
- hybrid routing
- human approval for SQL
- cloud observability

#### Decision

This option was selected because it best matches the product problem: not just answering questions, but answering them with safer routing, stronger grounding, and a production-ready operational model.

---

## 12. Proposed Product Solution

The selected solution is an enterprise-style AI copilot built around:

1. FastAPI backend for core APIs
2. Streamlit frontend for interactive operation
3. LangGraph orchestration for route execution and SQL interruption flow
4. PostgreSQL for structured data and auth storage
5. Qdrant Cloud for vector retrieval
6. OpenAI-powered generation and embeddings
7. Redis-style caching with in-memory fallback
8. AWS ECS Fargate deployment
9. CloudWatch dashboards, alarms, and logs for production observability

This architecture intentionally balances:

- AI capability
- operational safety
- implementation realism
- explainability
- infrastructure manageability

---

## 13. AI Product Strategy

## 13.1 Why This Is An AI Product, Not Just A Search Product

The system is not only retrieving chunks. It also:

- routes by intent
- rewrites follow-up questions
- chooses retrieval strategy in `auto`
- combines SQL and RAG
- applies retrieval quality controls
- supports reflection-oriented troubleshooting cases

## 13.2 Retrieval Strategy Philosophy

The product should not always use every advanced technique. That creates noise, latency, and unnecessary complexity. Instead:

- `hybrid + rerank` is the strongest general manual default
- HyDE is used for semantic or paraphrased queries
- CRAG is used when retrieval confidence needs grounding checks
- SRAG is used sparingly for ambiguous troubleshooting or reflection-heavy queries
- auto mode should choose the simplest strategy that still gives strong grounding

## 13.3 PM View On AI Product Quality

A PM for an AI product should evaluate:

- is the route correct?
- are sources relevant?
- is latency acceptable?
- is the answer safe?
- can the behavior be explained?
- can production support the feature without guesswork?

---

## 14. Current Product Capabilities

### Retrieval

- dense retrieval
- sparse retrieval
- hybrid retrieval
- reranking
- HyDE
- CRAG
- self-reflective RAG
- auto retrieval policy

### Structured Data

- text-to-SQL generation
- AST-based SQL validation through `sqlglot`
- SQL execution only after approval when applicable
- hybrid SQL + RAG response composition

### Conversation

- follow-up subject resolution
- question rewriting for pronoun-like references

### Caching

- intent cache
- RAG answer cache
- SQL generation cache
- SQL result cache
- embedding-related acceleration paths

### Observability

- CloudWatch logs
- CloudWatch alarms
- CloudWatch dashboard
- load-test result artifacts

---

## 15. Tool And Technology Selection

## 15.1 LLM Platform

### Selected

- OpenAI APIs

### Rationale

- strong general language quality
- practical ecosystem support
- suitable for RAG, rewriting, and SQL-generation tasks

## 15.2 Orchestration

### Selected

- LangGraph

### Rationale

- better fit than a simple linear chain
- supports branching, interrupts, and resumption
- useful for human-in-the-loop SQL approval

## 15.3 Vector Database

### Selected

- Qdrant Cloud

### Rationale

- purpose-built vector search
- managed service reduces ops burden
- appropriate for portfolio-grade production deployment

## 15.4 Relational Database

### Selected

- PostgreSQL on RDS

### Rationale

- standard relational engine
- strong SQL support
- realistic production choice for structured operational data

## 15.5 Backend Framework

### Selected

- FastAPI

### Rationale

- clean API development
- good validation model
- straightforward testing

## 15.6 Frontend

### Selected

- Streamlit

### Rationale

- fast interactive delivery
- sufficient for demo, admin, and query workflows
- practical for showcasing AI controls and source inspection

## 15.7 Cache Layer

### Selected

- Upstash Redis pattern with in-memory fallback

### Rationale

- lower repeated cost and latency
- pragmatic resilience during local development

## 15.8 Cloud Platform

### Selected

- AWS

### Rationale

- production credibility
- ECS Fargate reduces cluster management overhead
- CloudWatch provides enough observability for this scope

---

## 16. Infrastructure And Deployment Requirements

## 16.1 Current AWS Deployment Labels

- ECS cluster: `new-adv-rag-cluster`
- backend service: `backend-service`
- streamlit service: `streamlit-service`
- CloudWatch dashboard: `new-adv-rag-ops`
- Qdrant collection: `new_adv_rag_documents`

## 16.2 Deployed Components

- backend API on ECS Fargate
- Streamlit frontend on ECS Fargate
- RDS PostgreSQL
- Qdrant Cloud
- S3-backed document storage path
- Route 53 and ACM for custom domains
- ALB for ingress
- CloudWatch logs, alarms, and dashboards

## 16.3 Product Requirement For Production Readiness

The product must be:

- deployable with HTTPS
- observable with logs and alarms
- testable with live smoke checks
- stable enough for screenshots and demos

---

## 17. Security And Risk Controls

### 17.1 Input Safety

- unsafe prompts should be blocked
- moderation and restructuring layers should reduce prompt abuse

### 17.2 SQL Safety

- SQL must be parsed and validated by AST
- only safe read-only query shapes should pass
- risky operations must never execute

### 17.3 Approval Safety

- SQL approval must be explicit
- stale approval state must return clear `409` behavior

### 17.4 Source Safety

- answers should prefer corpus-backed or explicit approved sources
- noisy chunks should be minimized through retrieval policy and reranking

### 17.5 Access Control

- authenticated query access
- admin-sensitive views separated appropriately

---

## 18. Product UX Requirements

The UI should allow a user to:

- enter a question
- choose or observe retrieval mode
- inspect active configuration
- view sources
- view chunks and raw JSON when needed
- approve pending SQL
- review recent queries
- inspect deployment information and backend health

The UI should also make the system behavior legible, not magical. AI products gain trust when the user can see:

- what route was chosen
- which controls were active
- where the answer came from

---

## 19. Observability Requirements

The PM requirement is not only “the app works.” The PM requirement is “the team can prove it works under real conditions.”

Required observability includes:

- backend logs
- frontend logs where relevant
- ALB error visibility
- RDS metrics
- ECS CPU and memory
- target health
- alarm state visibility

The CloudWatch dashboard should consolidate the main graphs in one place so stakeholders can capture before-and-after screenshots during test runs.

---

## 20. Evaluation And Testing Strategy

## 20.1 Unit And Integration Tests

The product should maintain coverage for:

- routing
- query API
- SQL safety
- follow-up context handling
- retrieval policy behavior
- cache behavior where applicable

## 20.2 AI Evaluation

Evaluation should include:

- baseline profile
- hybrid profile
- hybrid SQL profile
- CRAG-related profile

The goal is not only model score optimization. The goal is regression detection and route-quality monitoring.

## 20.3 Load Testing

Smoke-level k6 tests should cover:

- health endpoint
- RAG query path
- SQL or hybrid behavior where suitable
- mixed path behavior

## 20.4 Manual Product Validation

A PM or QA reviewer should verify:

- pure RAG question
- pure SQL question
- hybrid question
- follow-up question
- ambiguous troubleshooting question
- source transparency
- auto vs manual strategy behavior

---

## 21. Known Tradeoffs

### Tradeoff 1: Streamlit Instead Of A Custom React UI

- faster delivery
- lower frontend engineering complexity
- less polished than a fully custom enterprise UI

### Tradeoff 2: ECS Fargate Instead Of Kubernetes For Hosting

- simpler operational model for this portfolio scope
- enough production realism without managing a cluster

### Tradeoff 3: Conditional Advanced Retrieval Instead Of Always-On

- better latency and lower noise
- requires more policy tuning

### Tradeoff 4: Human Approval For SQL

- stronger safety
- adds friction to some structured workflows

---

## 22. Risks

### Product Risks

- noisy retrieval for short or ambiguous questions
- auto mode may choose a weaker strategy for edge cases
- users may overtrust confidence without reviewing sources

### Technical Risks

- stale SQL approval state across deploys or restarts
- infra drift between local and cloud
- hidden dependency on local services during tests if mocking is incomplete

### Operational Risks

- insufficient alarm coverage
- unclear load-test evidence
- deployment regressions without smoke validation

---

## 23. Mitigations

- expose resolved retrieval configuration in metadata
- keep manual mode for explicit strategy testing
- maintain regression tests for retrieval policy
- keep CI independent from local-only infrastructure
- document deployment and rebuild steps clearly
- use CloudWatch dashboard for operational visibility

---

## 24. Delivery Roadmap

### Phase 1: Core Backend

- FastAPI base
- models
- auth
- initial APIs

### Phase 2: Retrieval Foundation

- chunking
- embeddings
- Qdrant integration
- dense retrieval

### Phase 3: Advanced Retrieval

- sparse retrieval
- hybrid retrieval
- reranking
- HyDE
- CRAG
- SRAG
- auto retrieval policy

### Phase 4: Structured Data Path

- SQL generation
- SQL validation
- SQL execution
- hybrid routing

### Phase 5: Safety And Approval

- human-in-the-loop SQL approval
- stale-state handling
- stronger error contracts

### Phase 6: Product UX

- Streamlit query workflow
- source inspection
- active config visibility
- deployment info card

### Phase 7: Productionization

- Docker
- ECS deployment
- ALB and DNS
- CloudWatch

### Phase 8: Validation

- unit tests
- eval workflows
- load tests
- manual product validation

---

## 25. Acceptance Criteria

The product is considered acceptable when:

1. RAG questions return grounded answers with sources.
2. SQL questions can be answered through a safe and explicit flow.
3. Hybrid questions combine structured facts and document context correctly.
4. Follow-up questions can resolve prior context for representative cases.
5. Auto mode exposes its chosen strategy in metadata.
6. Unsafe SQL does not execute.
7. Cloud deployment is stable and observable.
8. CloudWatch dashboard supports load-test screenshot capture.
9. CI passes consistently without hidden local infra dependencies.
10. Documentation is sufficient for rebuild, deployment, and product explanation.

---

## 26. Open Questions For Future Product Iterations

- should approval state move fully to durable storage for all cases?
- should we add stronger ranking analytics for noisy chunk detection?
- should web fallback be introduced for selected enterprise use cases?
- should frontend evolve from Streamlit to a custom web app later?
- should infra move to Kubernetes if operational scope expands?

---

## 27. How A Product Manager Should Run An AI Project Like This

This section is intentionally practical.

### Step 1: Start With A Real User Problem

Do not start with “use RAG.” Start with:

- who is losing time?
- what decision or task is slow today?
- what knowledge sources are fragmented?
- what failure is expensive if the AI is wrong?

### Step 2: Define The Decision Types

Separate the problem into:

- unstructured knowledge questions
- structured analytics questions
- mixed questions
- high-risk actions requiring approval

That decomposition strongly influences architecture.

### Step 3: Decide What The AI Must Never Do

For this product:

- never run unsafe SQL
- never hide missing approval context
- never pretend unsupported sources are trustworthy

### Step 4: Design Evaluation Early

A PM should define:

- example questions
- follow-up questions
- route expectations
- acceptance criteria
- qualitative and quantitative review methods

### Step 5: Treat Infra As Part Of Product Quality

If production behavior cannot be observed, the product is not ready. AI PM work includes:

- logs
- alarms
- dashboards
- smoke tests
- deployment evidence

### Step 6: Plan For Iterative Retrieval Tuning

Expect to adjust:

- chunking
- retrieval mode defaults
- rerank use
- HyDE use
- CRAG thresholds
- SRAG triggers

### Step 7: Keep Human Trust Visible

Users trust AI products more when they can inspect:

- sources
- route
- active config
- explicit approval checkpoints

That is a product requirement, not just an engineering extra.

---

## 28. Recommendation

Continue positioning this project as an enterprise AI copilot rather than a simple chatbot. The strongest differentiators are:

- multi-route RAG + SQL design
- SQL safety and approval workflow
- follow-up context handling
- conditional advanced retrieval strategies
- AWS deployment and CloudWatch evidence
- CI, eval, and load-test discipline

Those elements make the project more credible as a real product case study and a stronger portfolio artifact.

---

## 29. Related Project Documents

- [README.md](C:/Users/vthot/PORTFOLIO-PROJECTS/ENTERPRISE-ADV-RAG/new-adv-rag-implement/README.md)
- [WRITEUP.md](C:/Users/vthot/PORTFOLIO-PROJECTS/ENTERPRISE-ADV-RAG/new-adv-rag-implement/WRITEUP.md)
- [AWS_DEPLOYMENT.md](C:/Users/vthot/PORTFOLIO-PROJECTS/ENTERPRISE-ADV-RAG/new-adv-rag-implement/AWS_DEPLOYMENT.md)
- [REBUILD_FROM_SCRATCH_GUIDE.md](C:/Users/vthot/PORTFOLIO-PROJECTS/ENTERPRISE-ADV-RAG/new-adv-rag-implement/REBUILD_FROM_SCRATCH_GUIDE.md)
- [loadtests/README.md](C:/Users/vthot/PORTFOLIO-PROJECTS/ENTERPRISE-ADV-RAG/new-adv-rag-implement/loadtests/README.md)

