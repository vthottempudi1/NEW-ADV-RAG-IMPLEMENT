# Reliability, SLO, Backup, and Recovery Policy

## Service objectives

These are initial portfolio targets, not contractual guarantees.

| Indicator | Initial objective | Measurement |
|---|---:|---|
| Backend availability | 99.5% monthly | Successful ALB requests excluding intentional 4xx responses |
| Health endpoint p95 | Under 250 ms | ALB target-response-time metric |
| Warm RAG p95 | Under 8 seconds | Application or k6 request-duration metric |
| Mixed SQL + RAG p95 | Under 20 seconds | End-to-end approval-flow measurement |
| Server error rate | Under 1% over 15 minutes | ALB HTTP 5xx count divided by request count |
| Evaluation completion | 100% infrastructure completion | Completed cases divided by scheduled cases |

The July 2026 validation established good availability and warm-RAG latency, but mixed-flow latency and one evaluation `504` did not meet all objectives. These remain known improvement areas.

## Alert policy

CloudWatch alarms cover ALB 5xx responses and response time, ECS CPU and memory, RDS CPU and connections, and target health. Alerts should be routed to an owned notification channel before treating the deployment as production-operated. Warning alerts should fire before an SLO is exhausted; critical alerts should indicate active customer impact.

## Recovery objectives

- Target RTO: 4 hours for this portfolio environment.
- Target RPO: 24 hours for PostgreSQL and uploaded documents.
- Cache data has no recovery guarantee and must be reconstructable.
- Qdrant vectors must be reproducible from retained source documents; production use should additionally schedule and test snapshots.

## Backup requirements

- Enable automated RDS backups with at least seven days of retention.
- Enable S3 versioning and lifecycle policies for uploaded source documents.
- Export or snapshot the Qdrant collection on a documented schedule.
- Retain deployment configuration and image digests needed for rollback.
- Never consider a backup valid until a restoration exercise succeeds.

## Recovery procedure

1. Identify the failed dependency and freeze writes if corruption is suspected.
2. Restore PostgreSQL to a new instance or point in time.
3. Restore source documents from S3 and Qdrant from a snapshot, or rebuild embeddings from sources.
4. deploy the last known-good immutable backend and UI images.
5. Clear Redis caches to prevent stale or cross-version responses.
6. Run health checks, authentication smoke tests, RAG evaluation smoke, and SQL approval smoke tests.
7. Re-enable traffic and record actual RTO and data loss.

## Multi-AZ and disaster recovery

ECS and ALB can span multiple availability zones, but the repository does not yet prove a complete Multi-AZ database and vector-store design. A higher-assurance deployment should use Multi-AZ RDS, redundant ECS tasks across subnets, a managed Qdrant plan with backups, and a tested regional recovery procedure.
