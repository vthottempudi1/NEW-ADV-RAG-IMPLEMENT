# Security Policy

**Reviewed:** July 13, 2026 for the Cloud-v2/schema-52 release

## Reporting a vulnerability

Do not open a public issue containing credentials, exploit details, or private data. Report the issue privately to the repository owner through GitHub's private vulnerability-reporting feature. Include affected versions, reproduction steps, impact, and any suggested mitigation.

## Supported version

Security fixes are applied to the current `main` branch. This portfolio project does not currently maintain older release branches.

## Security model

The application implements request validation, JWT authentication, rate limiting, token budgets, input restructuring, pattern-based prompt-injection checks, PII redaction, prompt/context isolation, SQL AST validation with human approval, and output validation. These are defense-in-depth controls, not a certification or guarantee that arbitrary hostile input is safe.

Production credentials are supplied through AWS Secrets Manager. Local `.env` files are for development only and are excluded from Git.

### Nine defensive checkpoints

1. Typed request/model validation.
2. JWT authentication.
3. Per-user rate limiting.
4. Token-budget enforcement.
5. Input restructuring and size control.
6. Prompt-injection and unsafe-input pattern checks.
7. Moderation and lightweight PII redaction.
8. Hardened prompting and untrusted-context isolation.
9. Output validation.

Text-to-SQL adds `sqlglot` AST validation, read-only restrictions, bounded execution, and explicit
human approval as a separate database trust boundary. These checkpoints are controls, not nine
independent products or a compliance certification.

## Operator responsibilities

### Secret-scanning exception

Gitleaks continues to scan Git history with its default rules. A repository-level allowlist applies
only to the retired `evals/reports/results/*.json` path because historical reports quoted public
Kubernetes examples containing placeholder tokens and passwords. Raw reports are no longer tracked.
No application, deployment, environment, task-definition, or documentation path is exempted.

- Rotate all default and demo credentials before deployment.
- Restrict IAM, database, Qdrant, Redis, and S3 access to least privilege.
- Review dependency, secret, and container scan findings before release.
- Require `pip-audit`, Gitleaks, Trivy, tests, and deterministic route/source gates to pass in CI.
- Configure log retention, backup retention, alert notifications, and incident ownership.
- Do not use the current single-tenant design for unrelated customers without tenant-aware authorization, cache namespaces, SQL controls, and vector filters.

## Known limits

Pattern-based injection detection, PII redaction, and output checks do not guarantee safety against
arbitrary hostile input. Higher-risk deployments require a threat model, adversarial testing,
stronger policy controls, tenant-scoped authorization, rotation drills, and incident exercises.
Web fallback must remain limited to explicitly current questions and trusted source allowlists,
with provenance visible in the response.
