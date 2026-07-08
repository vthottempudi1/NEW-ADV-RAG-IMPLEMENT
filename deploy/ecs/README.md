# ECS Deployment Scaffold

This folder contains starter deployment artifacts for an AWS shape with:

- `backend` service on ECS/Fargate
- `streamlit` service on ECS/Fargate
- `qdrant` via Qdrant Cloud or a separately managed self-hosted deployment
- `RDS PostgreSQL`, `ElastiCache Redis`, and `S3` as managed services outside ECS

Recommended rollout order:

1. Build and push backend image to ECR.
2. Build and push Streamlit image to ECR.
3. Provision RDS, ElastiCache, and S3.
4. Create ECS task definitions from the templates in this folder.
5. Inject secrets from AWS Secrets Manager or SSM Parameter Store.
6. Place backend and Streamlit behind an ALB.
7. Point backend to Qdrant Cloud or another private Qdrant endpoint.
8. Run the post-deployment smoke test before release.

Files in this folder are templates and require AWS-specific values such as:

- account ID
- region
- image URIs
- subnet IDs
- security group IDs
- secret ARNs
- target collection / DB URLs
