# Data Handling Policy

## Scope

This policy covers documents uploaded for retrieval, generated embeddings, query text, SQL results, evaluation artifacts, logs, and cached responses.

## Data classification

- Public: published Kubernetes documentation and intentionally public demo material.
- Internal: synthetic operational records, evaluation questions, retrieval traces, and system configuration that contains no secret.
- Confidential: user queries, uploaded private documents, SQL results, and document-derived embeddings.
- Secret: API keys, database credentials, JWT signing material, Redis credentials, and cloud access credentials.

The demo corpus must contain only public or intentionally synthetic data. Production operators are responsible for confirming that they have the right to ingest every document.

## Storage and access

- Production secrets are injected from AWS Secrets Manager; they must never be committed to Git or written to evaluation artifacts.
- Source documents are stored through the configured local or S3 storage backend.
- Embeddings and chunk metadata are stored in Qdrant. Embeddings are treated as confidential because they may reveal information about their source text.
- Structured operational data and pending SQL approvals are stored in PostgreSQL.
- Query caches use Upstash Redis with an in-process fallback. Cache keys are hashed, but cached values may contain confidential answers or SQL results.
- Access to upload, query, administration, and SQL approval paths is controlled through JWT roles and application authorization.

## Logging and evaluation

- Do not log access tokens, passwords, raw secrets, or complete confidential documents.
- Request IDs may be logged for correlation.
- Evaluation output may contain questions, answers, retrieved context, and source names. Store it as confidential unless the corpus is demonstrably public.
- Production evaluation artifacts should record environment and corpus counts, but never credentials or secret ARNs.

## Retention and deletion

This portfolio deployment does not promise a regulatory retention period. Before handling real enterprise data, configure explicit lifecycle rules for S3, CloudWatch Logs, PostgreSQL backups, Qdrant snapshots, Redis TTLs, and evaluation artifacts. A deletion request must remove the original object, derived chunks and embeddings, cached answers, and retained evaluation traces where applicable.

## Prohibited data

Do not ingest regulated health data, payment-card data, government identifiers, export-controlled content, or customer confidential material until organization-specific legal, security, retention, and deletion controls have been approved.

## Incident response

Suspected exposure requires credential rotation, access-log preservation, affected-data identification, cache invalidation, stakeholder notification, and remediation before service restoration.
