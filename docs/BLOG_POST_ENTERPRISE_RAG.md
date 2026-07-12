# Building an Enterprise-Style RAG System: From Basic Retrieval to Safe SQL, AWS Deployment, and Production Validation

Most Retrieval-Augmented Generation projects stop at a familiar milestone:

- upload a document
- chunk it
- embed it
- retrieve similar text
- ask an LLM to answer

That is a useful starting point, but it is not enough to represent how enterprise AI systems are expected to behave in the real world.

In production, the hard questions begin after the first demo works:

- How do you answer questions that need both documents and structured data?
- How do you stop generated SQL from becoming unsafe?
- How do you make follow-up questions work naturally?
- How do you choose the right retrieval strategy for different question types?
- How do you deploy the system in the cloud, monitor it, test it, and explain it credibly?

I built this project to answer those questions with a real implementation, not just a conceptual architecture diagram.

The result is an enterprise-style AI assistant that supports:

- document-grounded RAG
- SQL question answering
- hybrid SQL + RAG responses
- human-in-the-loop SQL approval
- backend-owned auto retrieval strategy selection
- advanced retrieval controls such as dense, sparse, hybrid, reranking, HyDE, CRAG, and self-reflective RAG
- AWS deployment with HTTPS, ECS Fargate, RDS, Qdrant Cloud, S3, Route 53, ACM, and CloudWatch
- automated tests, eval workflows, GitHub Actions CI, and live load-test validation

This post explains the project end to end: the problem, design choices, architecture, implementation, deployment, validation, and the engineering lessons that made it much more than a basic RAG demo.

---

## The Problem: Why Basic RAG Was Not Enough

Many AI assistants fail not because the language model is weak, but because the surrounding system is too simple for the problem it is trying to solve.

In enterprise environments, knowledge is fragmented across:

- unstructured documents such as PDFs, runbooks, and internal policies
- structured data stored in databases
- operational terminology that often relies on exact strings such as `ErrImagePull`, `OOMKilled`, or `CrashLoopBackOff`
- follow-up questions where users refer to “that same object” or “the non-sensitive one” instead of repeating a full term

A single retrieval strategy cannot handle all of these cases equally well.

For example:

- “What is the difference between a ConfigMap and a Secret in Kubernetes?” is a document-grounded conceptual comparison.
- “How many P1 incidents were resolved last quarter?” is a database question.
- “How many P1 incidents were resolved last quarter and what does the escalation policy say for P1 incidents?” is a hybrid question.
- “My Kubernetes app keeps restarting, and I am not sure whether the root cause is the liveness probe, OOMKilled, or a bad image. How should I troubleshoot it step by step?” is an ambiguous troubleshooting question that benefits from reflection-oriented retrieval behavior.

If I treated all of these as the same type of query, the system would be weaker, noisier, and much harder to trust.

So the goal of the project became clear:

> Build an enterprise-style AI backend that can route intelligently, retrieve flexibly, answer safely, and be deployed and validated like a real production system.

---

## The Product I Wanted to Build

I was not trying to create a generic chatbot. I wanted a system with clear engineering depth and realistic operational behavior.

The final target scope was:

- answer document questions through RAG
- answer structured questions through SQL
- answer mixed questions through hybrid orchestration
- support manual retrieval controls for demos and debugging
- support automatic retrieval strategy selection for production-style usage
- keep SQL safe through AST validation and explicit approval
- support follow-up context
- expose sources, chunks, and metadata clearly
- run locally and in AWS
- prove correctness and operational quality through tests, evals, and load tests

This product direction influenced every major decision in the codebase.

---

## The High-Level Architecture

At a high level, the system looks like this:

```text
User
  -> Streamlit Frontend
  -> FastAPI Backend
  -> Guardrails + Auth + Budget Controls
  -> Intent Router
  -> LangGraph Orchestration
       -> RAG path
       -> SQL path
       -> Hybrid path
  -> Final grounded response
```

The main components are:

- **FastAPI** for the API layer
- **Streamlit** for the interactive UI
- **LangGraph** for orchestration and interrupt-driven approval flow
- **PostgreSQL** for users and structured operational data
- **Qdrant Cloud** for vector search
- **OpenAI** for embeddings and answer generation
- **S3** for original uploaded document storage
- **CloudWatch** for logs, metrics, alarms, and dashboarding

This separation of responsibilities was deliberate:

- PostgreSQL is good at structured relational data
- Qdrant is good at vector retrieval
- S3 is good at durable file storage
- FastAPI is good at request handling and validation
- LangGraph is good at branching workflows and pauses

That last point matters because this project includes a human approval checkpoint before executing generated SQL.

---

## Why I Did Not Build “Just One Retrieval System”

One of the most important design choices was accepting that different question types require different retrieval behavior.

### Dense Retrieval

Dense retrieval is embedding-based semantic search. It is strongest when the wording is conceptual, paraphrased, or indirect.

Example:

> “How do I make sure my app keeps running even if a server dies?”

This question may never say “high availability,” “replicas,” or “rescheduling,” but dense retrieval can still find relevant content based on meaning.

### Sparse Retrieval

Sparse retrieval is more keyword-oriented. It is valuable when exact tokens matter.

Examples:

- `ErrImagePull`
- `OOMKilled`
- `CrashLoopBackOff`

These terms are so operationally specific that lexical matching is extremely useful.

### Hybrid Retrieval

Hybrid retrieval combines dense and sparse signals. In practice, this became the strongest general-purpose default for my mixed enterprise corpus.

Why? Because real operational questions often need both:

- semantic understanding
- exact technical term matching

### Reranking

Reranking rescored candidate chunks after initial retrieval. This was especially useful when the corpus contained distractor documents or partially relevant text.

### HyDE

HyDE stands for Hypothetical Document Embeddings.

The basic idea is:

1. generate a likely answer-like text
2. embed that synthetic text
3. use it to retrieve more semantically relevant chunks

This is helpful for vague or conceptual questions.

### CRAG

CRAG is used here as a corrective retrieval quality layer.

Instead of assuming retrieval is good enough, the system evaluates how trustworthy the retrieved set looks. That gives the system a way to reason about retrieval quality instead of blindly trusting every retrieval result.

### Self-Reflective RAG (SRAG)

Self-reflective RAG is useful when the question is uncertain, ambiguous, or needs step-by-step troubleshooting logic.

For example:

> “My Kubernetes app keeps restarting, and I am not sure whether the root cause is the liveness probe, OOMKilled, or a bad image.”

This is different from a simple fact lookup. It benefits from a more reflective strategy.

---

## Intent Routing: Why the Assistant Needed More Than One Path

One of the most important backend layers is the intent router.

The system classifies questions into:

- `rag`
- `sql`
- `hybrid`

This logic lives in `app/rag/router.py` and uses practical heuristics:

- SQL hints such as `how many`, `count`, `average`, `highest`
- entity words such as `incidents`, `users`, `cluster`, `SLA`
- RAG hints such as `policy`, `runbook`, `guide`, `Kubernetes`

This enables three distinct behaviors:

### RAG Route

Best for document questions such as:

> “What does our escalation policy say for P1 incidents?”

### SQL Route

Best for structured questions such as:

> “How many P1 incidents were resolved last quarter?”

### Hybrid Route

Best for mixed questions such as:

> “How many P1 incidents were resolved last quarter and what does our escalation policy say for P1 incidents?”

Without routing, the assistant would either overuse SQL, overuse document retrieval, or fail to combine both well.

---

## Why I Added Text-to-SQL and Why I Did Not Trust It Blindly

Many enterprise questions require structured facts, not just document excerpts.

For that reason, I added a Text-to-SQL path that:

- generates SQL from natural language
- validates the SQL
- optionally pauses for approval before execution

But generated SQL can be risky. Even in a read-only system, it should not be trusted casually.

So I used **`sqlglot` AST-based validation** instead of relying only on string filtering.

That allowed the system to enforce rules such as:

- allow safe read-only query shapes
- block destructive operations
- block multi-statement SQL
- reject patterns that are structurally unsafe

This mattered because “read-only” is not something I wanted to enforce through hope. I wanted the application to be able to prove the query shape was acceptable.

---

## Human-in-the-Loop SQL Approval

One of the strongest engineering decisions in the project was to make SQL execution pausable.

When needed, the graph can:

1. generate SQL
2. return a `pending_sql` block to the UI
3. wait for explicit user approval
4. resume execution through `POST /query/sql/execute`

This was built using LangGraph’s interrupt and resume behavior.

It makes the system much more realistic because it acknowledges a real production truth:

> Just because the model can produce SQL does not mean the system should execute it immediately.

This also made the frontend more meaningful. It is not only a chat box. It is a control surface for safe AI-assisted operations.

---

## Follow-Up Context: Making the System Feel Conversational

Another important capability was follow-up question handling.

Users often ask a first question like:

> “What is the difference between a ConfigMap and a Secret in Kubernetes?”

Then they follow up with:

> “For the non-sensitive one, if I inject it as environment variables instead of a volume, will updates show up automatically?”

This follow-up no longer contains all the original nouns. The system has to infer what “the non-sensitive one” refers to.

So I added a conversation-context rewriting layer that can resolve those references before query execution continues.

This improves answer quality significantly because many real users do not restate the full object name every time.

---

## Ingestion: Why Document Upload Had to Be More Than File Storage

I did not want ingestion logic scattered across scripts and route handlers, so I centralized it in `IngestionService`.

The ingestion pipeline does this:

1. accept file bytes or file path
2. compute a SHA-256 content hash
3. skip duplicates if the document was already indexed
4. parse the document
5. chunk the text
6. generate embeddings
7. upsert vectors into Qdrant
8. store the original file through the storage backend
9. persist metadata for future traceability

The content hash step is especially important.

Why? Because duplicate ingestion is a very common practical problem. Two files may have different names and the same content. Without dedupe, the vector store becomes noisier and retrieval quality degrades.

This part of the system is a good example of why enterprise AI work is often about data hygiene as much as model prompting.

---

## Query-Time Caching: What I Cached and Why

This project uses multiple cache tiers, including:

- intent cache
- RAG answer cache
- SQL generation cache
- SQL result cache
- embedding cache

This design supports two goals:

- reduce repeated latency
- lower repeated LLM and infrastructure cost

An important distinction in the system is:

- **document deduplication** is not the same as **query-time caching**

Document dedupe prevents indexing the same content multiple times.

Query caching prevents recomputing the same answer path repeatedly.

Keeping those concerns separate made the system easier to reason about.

---

## Manual Mode vs Auto Mode

One of the most user-visible product decisions was supporting both:

- **Manual mode**
- **Auto mode**

### Manual Mode

Manual mode is useful for demos, debugging, and architecture explanation.

It lets the user explicitly control:

- search mode
- top K
- rerank
- HyDE
- CRAG
- SRAG

This is ideal when I want to show how different retrieval policies behave.

### Auto Mode

Auto mode is meant to behave more like a production assistant.

Instead of forcing the user to understand retrieval theory, the backend chooses the strategy based on the question itself.

This logic lives in `app/rag/auto_retrieval.py`.

It looks for signals such as:

- exact technical tokens
- conceptual wording
- troubleshooting phrases
- uncertainty markers
- action-oriented question patterns
- question vagueness

### Example Auto Decisions

**Short exact-token question**

> `ErrImagePull`

Likely decision:

- sparse
- rerank on
- CRAG on

**Conceptual question**

> “What is the best way to think about service discovery in Kubernetes?”

Likely decision:

- dense
- HyDE on
- rerank on

**Direct object comparison**

> “What is the difference between a ConfigMap and a Secret in Kubernetes?”

Likely decision:

- hybrid
- rerank on
- HyDE off

**Ambiguous troubleshooting question**

> “My Kubernetes app keeps restarting, and I am not sure whether the root cause is the liveness probe, OOMKilled, or a bad image. How should I troubleshoot it step by step?”

Likely decision:

- hybrid
- rerank on
- CRAG on
- SRAG on

### A Useful Debugging Lesson

One live debugging case was the question:

> `how do i scale`

At first glance, that might sound like it should trigger reflection behavior. But under the actual auto policy, it did not activate SRAG.

Why?

Because it is a short operational action query, not an ambiguous troubleshooting query. It lacks strong uncertainty signals and multiple competing causes.

So the system correctly chose:

- hybrid
- rerank on
- CRAG on
- SRAG off

That debugging session helped verify that auto mode was working as designed and that the real issue was the preset content, not the backend logic.

---

## The Frontend: Why It Is More Than a Demo Layer

The Streamlit application is not just a toy shell around the backend.

It exposes several important product behaviors:

- login and registration
- query submission
- manual vs auto retrieval experience
- pending SQL approval
- query history
- admin actions
- sources, chunks, metadata, and raw JSON inspection
- deployment info and backend health

### Active Config

One of the most useful UI sections is **Active Config**.

It shows what the system actually used:

- experience mode
- search mode
- top K
- rerank
- CRAG
- HyDE
- SRAG

That matters because users should be able to see whether:

- they selected something manually
- or the backend resolved it automatically

This is a trust and debugging feature, not just a visual extra.

### Sources and Chunks

The UI also makes it easy to inspect:

- source list
- retrieved chunk previews
- chunk scores
- raw metadata

For AI systems, this level of inspection is critical. Otherwise, users are asked to trust answers they cannot validate.

---

## The Guardrails Layer

I wanted the project to look like a serious AI backend, so safety could not be an afterthought.

The system includes a layered guardrails approach with components such as:

- request validation
- JWT authentication
- rate limiting
- token budgets
- input restructuring
- prompt-injection / unsafe input checks
- moderation and redaction
- output validation

This does not make the system “perfectly safe,” because no AI system is, but it does make it much more credible than a single unguarded prompt pipeline.

---

## LangGraph Orchestration: Why a Graph Was the Right Model

I used LangGraph because the query workflow is not linear.

The system needs to support:

- a pure RAG path
- a pure SQL path
- a hybrid path
- approval pauses and resume behavior

That is much easier to model as a graph than as a single chain of function calls.

The high-level flow in the graph is:

1. classify intent
2. route to RAG, SQL, or hybrid
3. if SQL is involved, generate SQL
4. request approval when needed
5. run SQL after approval
6. if hybrid, combine SQL results and document context
7. finalize response

This was one of the most important architectural decisions in the project because it made the workflow explicit and debuggable.

---

## Deploying the System to AWS

I did not want the project to stop at local success.

So I deployed it to AWS using:

- ECS Fargate
- ECR
- ALB
- Route 53
- ACM
- RDS PostgreSQL
- Qdrant Cloud
- S3
- Secrets Manager
- CloudWatch

### Why ECS Fargate

ECS Fargate gave me production deployment credibility without forcing me to manage EC2 instances or a separate Kubernetes cluster for the application itself.

### Why RDS

The system already depended on PostgreSQL for auth and structured data, so RDS was the natural managed choice.

### Why Qdrant Cloud

I wanted vector search to be production-ready without self-hosting another stateful service.

### Why S3

S3 made sense for storing original uploaded documents durably and cheaply.

### Why CloudWatch

CloudWatch provided:

- log visibility
- alarms
- dashboards
- screenshot-friendly monitoring during load tests

That mattered because I wanted evidence, not just claims, that the deployed system was healthy.

---

## Production Validation: What I Checked After Deployment

A successful deployment is not just “the container started.”

I validated:

- backend health over HTTPS
- frontend reachability over HTTPS
- authentication flow
- document upload
- RAG question path
- SQL question path
- hybrid question path
- SQL approval behavior
- auto mode metadata
- cache-hit behavior

I also validated real infrastructure state such as:

- ECS service health
- target group health
- CloudWatch metrics
- request logs

This gave me confidence that the system was not only working locally but operating correctly in AWS.

---

## CloudWatch Dashboard and Alarms

I created a CloudWatch dashboard called `new-adv-rag-ops`.

It includes:

- manual alarm status
- backend ALB response time
- backend ECS CPU and memory
- RDS CPU and connections
- backend ALB 5xx and request count
- backend target group health
- streamlit ECS CPU
- backend request logs

This dashboard was designed so I could capture screenshots during load tests and use them as operational evidence.

I also worked through an important AWS-specific nuance:

ECS autoscaling creates extra `TargetTracking-service/...` alarms automatically. These are expected and should not be confused with the manually created portfolio/demo alarms.

That was a useful operational lesson because dashboards and alarms can look “messy” if you do not understand which signals are AWS-managed and which are product-managed.

---

## Testing Strategy

I wanted the project to demonstrate engineering discipline, so I built tests around the main risk areas rather than only around trivial success cases.

The suite covers:

- auth
- ingestion dedupe
- auto retrieval policy
- conversation context rewriting
- hybrid routing
- query API behavior
- SQL validation and formatting
- vector-store behavior
- reranking behavior
- source filtering behavior
- eval-smoke workflows

### A Good Example: Auto Retrieval Tests

The auto retrieval tests verify decisions such as:

- sparse for short exact-token queries
- hybrid for policy questions
- dense + HyDE for semantic questions
- hybrid for direct object comparisons
- dense + HyDE + CRAG + SRAG for vague questions
- SRAG for ambiguous troubleshooting questions

That gave me confidence that auto mode was not becoming a hand-wavy feature.

### A Good Example: Query API Tests

The query API tests cover:

- auth requirement
- unsafe input rejection
- auto resolution before graph execution
- follow-up rewriting before graph execution
- approved-cache reuse
- pending SQL approval behavior
- resume after approval
- explicit error handling for missing approval context

That last one was especially important because in real deployments, in-memory approval context can go stale after restarts or redeployments.

---

## GitHub Actions CI and a Real CI Debugging Lesson

I also wired the project into GitHub Actions so the repository itself validated cleanly on push.

The CI workflow runs:

- `pytest -q`
- eval-smoke jobs

One of the most useful engineering lessons came from a CI failure.

The tests passed locally but failed in GitHub Actions because some query API tests still relied on the real Postgres-backed pending SQL store. My local environment masked that dependency.

The fix was to make those tests use an in-memory fake pending-SQL store instead.

That was a very practical reminder that:

> A test is not truly good if it only passes in your local machine’s hidden environment.

After the fix, the suite passed cleanly and the repository was in a much healthier state.

---

## Evaluation Workflows

Besides tests, the project includes evaluation workflows under `evals/`.

Why both tests and evals?

- **tests** verify code correctness and flow behavior
- **evals** help judge AI behavior quality and retrieval strategy performance

The validation runs showed that:

- `hybrid + rerank` is the strongest general-purpose default
- HyDE, CRAG, and SRAG are best treated as conditional tools rather than always-on settings

That was an important product insight because it shaped the final strategy guidance presented in the UI:

- Auto is the best production default
- Manual is useful for retrieval strategy demos
- hybrid + rerank is the strongest manual default
- HyDE is best for semantic/paraphrased queries
- CRAG is useful for weak or uncertain retrieval
- SRAG should be used sparingly because of extra latency

---

## Load Testing the Live System

I did not want to claim production readiness without traffic validation, so I ran k6-based load tests against the live backend.

The tested paths included:

- `/health`
- authenticated RAG flow
- mixed RAG + SQL approval + hybrid flow

### Health Path

The health path was stable and fast:

- 58 requests
- 0% error rate
- ~62.62ms average latency
- ~69.11ms p95 latency

### RAG Path

The RAG path worked functionally and, on a repeated one-minute run, met the configured p95 threshold:

- 0% error rate
- ~4.78s average latency
- ~5.14s p95 latency on the successful repeated run

### Mixed Smoke Path

The mixed flow was the heaviest and most interesting case:

- 0% error rate
- ~10.88s average latency
- ~34.05s p95 latency

This meant:

- correctness was validated
- availability was validated
- end-to-end mixed-flow latency is the main remaining optimization area

That is actually a useful outcome for a serious portfolio project because it shows both strengths and honest next steps.

---

## Observability Evidence During Load Testing

During the load tests, I also verified live infrastructure behavior through CloudWatch and ECS:

- backend ALB response-time spikes were visible during the runs
- backend ECS CPU moved as expected
- target group health remained stable
- backend request logs showed recent request lines during the same windows
- ECS backend service remained active with healthy tasks

This gave the project something many AI demos lack:

**operational evidence**

Not just “the API returned a result,” but “the deployed system behaved predictably under observed traffic.”

---

## The Final User Experience

By the end of the implementation, the frontend supported an experience that made the architecture visible:

- preset queries for hybrid, RAG, SQL, troubleshooting, HyDE-style semantic search, and SRAG-style reflection
- Auto mode for backend-selected retrieval strategy
- Manual mode for explicit retrieval demos
- Active Config panel showing what the system actually used
- source cards
- chunk inspection
- metadata and raw JSON tabs
- pending SQL approval controls
- deployment info and backend health visibility

That matters because a good AI application should not feel like an opaque black box.

Users should be able to inspect:

- where the answer came from
- which route ran
- whether it was cached
- what retrieval configuration was active

---

## What This Project Demonstrates

This project demonstrates more than prompt wiring.

It shows:

- backend architecture for GenAI systems
- multi-route AI design
- retrieval tradeoff awareness
- safe SQL generation patterns
- human-in-the-loop workflow design
- source transparency and explainability
- cloud deployment and observability
- testing, eval, and CI discipline
- live load-test validation

For hiring managers and recruiters, that is the real point.

The value is not only that “an LLM answers questions.”

The value is that the surrounding system was designed to be:

- safer
- more flexible
- more observable
- more deployable
- easier to explain

---

## The Main Engineering Lessons

If I had to summarize the biggest lessons from the project, they would be these:

### 1. RAG is rarely enough by itself

Enterprise questions often need structured data, not only document retrieval.

### 2. Retrieval strategy should depend on question shape

Dense, sparse, hybrid, HyDE, CRAG, and SRAG are tools, not decorations.

### 3. SQL should be treated as a higher-risk path

Validation and approval made the system much more credible.

### 4. Follow-up context matters more than many demos admit

Users do not always repeat the exact noun phrase they used earlier.

### 5. Production evidence matters

CloudWatch dashboards, alarms, logs, ECS status, and load-test results make a big difference in credibility.

### 6. CI failures can reveal hidden local assumptions

Fixing those assumptions is part of building a mature AI backend.

---

## Final Outcome

By the end of the project, I had an enterprise-style AI assistant deployed at:

- `https://api.aiscientificlabs.com`
- `https://rag.aiscientificlabs.com`

It supported:

- document-grounded RAG
- SQL and hybrid routing
- SQL approval
- advanced retrieval strategies
- follow-up context handling
- AWS deployment with HTTPS
- CloudWatch observability
- automated tests
- eval workflows
- GitHub Actions CI
- live load-test validation

The system passed the core functional checks and GitHub Actions validation, and the live load-test results showed that correctness and availability were strong while latency optimization remained the main next improvement area.

That is exactly the kind of result I wanted:

not a perfect fantasy system, but a realistic, explainable, production-minded AI backend that can stand up to technical discussion.

---

## Closing

If you are evaluating AI engineering projects, I think the most important question is no longer:

> “Can this person call an LLM?”

It is:

> “Can this person design, ship, validate, and explain an AI system that behaves credibly under real constraints?”

This project was my answer to that question.

