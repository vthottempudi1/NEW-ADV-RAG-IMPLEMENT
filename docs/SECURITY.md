# Security Policy

## Reporting a vulnerability

Do not open a public issue containing credentials, exploit details, or private data. Report the issue privately to the repository owner through GitHub's private vulnerability-reporting feature. Include affected versions, reproduction steps, impact, and any suggested mitigation.

## Supported version

Security fixes are applied to the current `main` branch. This portfolio project does not currently maintain older release branches.

## Security model

The application implements request validation, JWT authentication, rate limiting, token budgets, input restructuring, pattern-based prompt-injection checks, PII redaction, prompt/context isolation, SQL AST validation with human approval, and output validation. These are defense-in-depth controls, not a certification or guarantee that arbitrary hostile input is safe.

Production credentials are supplied through AWS Secrets Manager. Local `.env` files are for development only and are excluded from Git.

## Operator responsibilities

### Secret-scanning exception

Gitleaks continues to scan Git history with its default rules. A repository-level allowlist applies
only to the retired `evals/reports/results/*.json` path because historical reports quoted public
Kubernetes examples containing placeholder tokens and passwords. Raw reports are no longer tracked.
No application, deployment, environment, task-definition, or documentation path is exempted.

- Rotate all default and demo credentials before deployment.
- Restrict IAM, database, Qdrant, Redis, and S3 access to least privilege.
- Review dependency, secret, and container scan findings before release.
- Configure log retention, backup retention, alert notifications, and incident ownership.
- Do not use the current single-tenant design for unrelated customers without tenant-aware authorization, cache namespaces, SQL controls, and vector filters.
