# AWS Deployment Guide

This is the source-of-truth deployment runbook for `new-adv-rag-implement`.

It covers:

1. the current live AWS state
2. the exact deployment sequence
3. validation and smoke-test steps
4. CloudWatch and load-test steps
5. known pitfalls and fixes

Use this together with:

- `WRITEUP.md` for architecture and project narrative
- `REBUILD_FROM_SCRATCH_GUIDE.md` for clean reconstruction order
- `loadtests/results/FINAL_LOADTEST_RESULTS_20260708.md` for the latest validation evidence

## 1. Current Live State

### Core AWS Identifiers

- Region: `us-east-2`
- AWS account ID: `785282204559`
- ECS cluster: `new-adv-rag-cluster`
- Backend ECS service: `backend-service`
- Streamlit ECS service: `streamlit-service`
- Backend task family: `new-adv-rag-backend`
- Streamlit task family: `new-adv-rag-streamlit`
- Current backend task definition: `new-adv-rag-backend:25`
- Current streamlit task definition: `new-adv-rag-streamlit:16`
- Backend ECR repo: `new-adv-rag-backend`
- Streamlit ECR repo: `new-adv-rag-streamlit`
- RDS instance: `new-adv-rag-postgres`
- RDS database: `adv_rag`
- Backend ALB: `backend-alb`
- Streamlit ALB: `streamlit-alb`
- Backend target group: `backend-tg`
- Streamlit target group: `streamlit-tg`
- Backend log group: `/ecs/new-adv-rag-backend`
- Streamlit log group: `/ecs/new-adv-rag-streamlit`
- CloudWatch dashboard: `new-adv-rag-ops`
- S3 bucket: `new-adv-rag-docs-785282204559`

### Public Entry Points

- Backend: `https://api.aiscientificlabs.com`
- Backend health: `https://api.aiscientificlabs.com/health`
- Frontend: `https://rag.aiscientificlabs.com`

### Data / External Services

- Qdrant Cloud endpoint: `https://0071b366-6f79-45cc-aa5a-a196e547aad6.sa-east-1-0.aws.cloud.qdrant.io:6333`
- Qdrant collection: `new_adv_rag_documents`
- Secrets Manager secret: `prod/advrag/backend`

## 2. Deployment Architecture

This deployment uses:

- ECS Fargate for backend and Streamlit
- ECR for container images
- RDS PostgreSQL for users and structured SQL data
- Qdrant Cloud for vectors
- S3 for uploaded files
- Secrets Manager for sensitive config
- CloudWatch Logs for container logs
- CloudWatch Alarms for alerting
- CloudWatch Dashboard for screenshot-friendly monitoring
- Route 53 + ACM + ALB for custom domains and HTTPS

## 3. Prerequisites

Before deployment, make sure you have:

- AWS CLI configured
- Docker Desktop working locally
- permission to create ECR, ECS, ALB, RDS, IAM, Route 53, ACM, S3, Secrets Manager, and CloudWatch resources
- a working OpenAI API key
- a Qdrant Cloud cluster and API key
- optional Upstash Redis credentials

Recommended local check:

```powershell
aws configure
aws sts get-caller-identity
```

Expected region for this project:

- `us-east-2`

## 4. Deployment Sequence

Follow these steps in order. This is the sequence that avoids the most common blockers.

### Step 1: Set Local Variables

```powershell
$AWS_REGION="us-east-2"
$AWS_ACCOUNT_ID="785282204559"
$BACKEND_REPO="new-adv-rag-backend"
$STREAMLIT_REPO="new-adv-rag-streamlit"
$BACKEND_IMAGE="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$BACKEND_REPO"
$STREAMLIT_IMAGE="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$STREAMLIT_REPO"
```

### Step 2: Create ECR Repositories

```powershell
aws ecr create-repository --repository-name $BACKEND_REPO --region $AWS_REGION
aws ecr create-repository --repository-name $STREAMLIT_REPO --region $AWS_REGION
```

Skip this step if they already exist.

### Step 3: Log In To ECR

```powershell
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
```

### Step 4: Build Images

Run from:

```powershell
cd C:\Users\vthot\PORTFOLIO-PROJECTS\ENTERPRISE-ADV-RAG\new-adv-rag-implement
```

Example tag values:

- backend: `v26`
- streamlit: `v16`

Build commands:

```powershell
docker build -t "$BACKEND_IMAGE:v26" -f Dockerfile .
docker build -t "$STREAMLIT_IMAGE:v16" -f Dockerfile.streamlit .
```

Important packaging notes:

- backend runtime dependencies are separated into `requirements.runtime.txt`
- streamlit dependencies are separated into `requirements.streamlit.txt`
- `.dockerignore` excludes caches, tests, large seed directories, and temp files
- build from the `new-adv-rag-implement` directory to avoid copying the wrong Streamlit file from the parent workspace

### Step 5: Push Images

```powershell
docker push "$BACKEND_IMAGE:v26"
docker push "$STREAMLIT_IMAGE:v16"
```

### Step 6: Create RDS PostgreSQL

Create an RDS PostgreSQL instance with:

- DB instance identifier: `new-adv-rag-postgres`
- database name: `adv_rag`
- master username: `postgres`
- port: `5432`

Recommended settings:

- use the same VPC/subnet family as ECS
- enable public access only if you need local pgAdmin or psql access
- allow inbound `5432` only from the minimum required client IPs and ECS SGs

After RDS is up:

1. connect using `psql` or pgAdmin
2. create tables / run migrations
3. verify `users` table exists

### Step 7: Create S3 Bucket

Create:

- `new-adv-rag-docs-785282204559`

Use:

- region `us-east-2`
- general-purpose bucket
- ownership with ACLs disabled

### Step 8: Prepare Qdrant Cloud

Use Qdrant Cloud rather than self-hosting Qdrant on ECS for this deployment.

Required values:

- Qdrant endpoint
- Qdrant API key
- collection name `new_adv_rag_documents`

### Step 9: Create Secrets Manager Secret

Create one JSON secret for the backend, for example:

- `prod/advrag/backend`

Store valid JSON with keys such as:

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `QDRANT_API_KEY`
- `JWT_SECRET`
- `TAVILY_API_KEY`
- `UPSTASH_REDIS_URL`
- `UPSTASH_REDIS_TOKEN`

`DATABASE_URL` should look like:

```text
postgresql://postgres:<password>@<rds-endpoint>:5432/adv_rag
```

Important:

- the secret must be real JSON
- avoid BOM-encoded files if rewriting the secret from PowerShell

### Step 10: Create ECS Cluster

```powershell
aws ecs create-cluster --cluster-name new-adv-rag-cluster --region $AWS_REGION
```

### Step 11: Create IAM Roles

Required roles:

- `ecsTaskExecutionRole`
- `new-adv-rag-backend-task-role`
- `new-adv-rag-streamlit-task-role`

Execution role requirements:

- trust `ecs-tasks.amazonaws.com`
- ECR pull permissions
- CloudWatch logs write permissions
- `secretsmanager:GetSecretValue` for the backend secret

Backend task role requirements:

- trust `ecs-tasks.amazonaws.com`
- S3 write access for `new-adv-rag-docs-785282204559`

Streamlit task role requirements:

- trust `ecs-tasks.amazonaws.com`

### Step 12: Create CloudWatch Log Groups

Create these before launching services:

- `/ecs/new-adv-rag-backend`
- `/ecs/new-adv-rag-streamlit`

If they do not exist, ECS service launch can fail before containers fully start.

### Step 13: Prepare Task Definitions

Files in repo:

- `deploy/ecs/backend-task-definition.json`
- `deploy/ecs/streamlit-task-definition.json`

Backend task definition key values:

- family: `new-adv-rag-backend`
- cpu: `1024`
- memory: `2048`
- container port: `8000`
- log group: `/ecs/new-adv-rag-backend`
- runtime environment includes:
  - `QDRANT_URL`
  - `QDRANT_COLLECTION`
  - `AWS_REGION=us-east-2`
  - `STORAGE_BACKEND=s3`
  - `S3_CACHE_BUCKET=new-adv-rag-docs-785282204559`

Backend container hardening:

- `PYTHONIOENCODING=utf-8`
- `PYTHONUTF8=1`
- `LANG=C.UTF-8`
- `LC_ALL=C.UTF-8`

Streamlit task definition key values:

- family: `new-adv-rag-streamlit`
- cpu: `512`
- memory: `1024`
- container port: `8501`
- log group: `/ecs/new-adv-rag-streamlit`
- environment includes:
  - `STREAMLIT_BROWSER_GATHER_USAGE_STATS=false`
  - `API_BASE_URL=https://api.aiscientificlabs.com`

Important:

- do not leave placeholder or localhost backend URLs in Streamlit task definitions

### Step 14: Register Task Definitions

```powershell
aws ecs register-task-definition --cli-input-json file://deploy/ecs/backend-task-definition.json --region $AWS_REGION
aws ecs register-task-definition --cli-input-json file://deploy/ecs/streamlit-task-definition.json --region $AWS_REGION
```

### Step 15: Create Target Groups

Backend target group:

- name: `backend-tg`
- target type: `ip`
- protocol: `HTTP`
- port: `8000`
- health check path: `/health`
- success code: `200`

Streamlit target group:

- name: `streamlit-tg`
- target type: `ip`
- protocol: `HTTP`
- port: `8501`
- health check path: `/_stcore/health`
- success code: `200`

### Step 16: Create ALBs

Backend ALB:

- name: `backend-alb`
- internet-facing
- listeners:
  - `80` redirect to `443`
  - `443` forward to `backend-tg`

Streamlit ALB:

- name: `streamlit-alb`
- internet-facing
- listeners:
  - `80` redirect to `443`
  - `443` forward to `streamlit-tg`

### Step 17: Create ECS Services

Backend ECS service:

- service name: `backend-service`
- launch type: `Fargate`
- desired count: `1`
- target group: `backend-tg`
- container port: `8000`

Streamlit ECS service:

- service name: `streamlit-service`
- launch type: `Fargate`
- desired count: `1`
- target group: `streamlit-tg`
- container port: `8501`

Critical networking rule:

- ECS service subnets must align with the ALB-enabled AZs
- SG ingress must allow ALB-to-task traffic on `8000` and `8501`

### Step 18: Add HTTPS and Custom Domains

Current production shape:

- DNS hosted in Route 53
- domains registered externally but delegated to Route 53 nameservers
- ACM certificate in `us-east-2`
- certificate covers:
  - `api.aiscientificlabs.com`
  - `rag.aiscientificlabs.com`

Listener / record mapping:

- `api.aiscientificlabs.com` -> backend ALB
- `rag.aiscientificlabs.com` -> streamlit ALB

### Step 19: Force Redeploy After Infrastructure Changes

Whenever you change:

- image tag
- task definition
- secret
- IAM role
- log group
- ALB or target-group config

force a new deployment:

```powershell
aws ecs update-service --cluster new-adv-rag-cluster --service backend-service --task-definition new-adv-rag-backend:<revision> --force-new-deployment --region $AWS_REGION
aws ecs update-service --cluster new-adv-rag-cluster --service streamlit-service --task-definition new-adv-rag-streamlit:<revision> --force-new-deployment --region $AWS_REGION
```

## 5. Post-Deployment Validation

### Health and Basic Reachability

Check:

- `https://api.aiscientificlabs.com/health`
- `https://rag.aiscientificlabs.com`

Expected:

- backend health returns `status=ok`
- frontend loads without localhost references

### Auth and Query Flow

Verify:

1. register a user
2. log in
3. run a RAG question
4. run a SQL question
5. run a hybrid question
6. approve SQL when prompted

Expected:

- RAG works
- SQL approval flow works
- hybrid flow works
- stale approval states return explicit `409` behavior instead of silent ambiguity

### Upload Validation

Upload as admin only.

Expected:

- object stored in S3
- vectors stored in Qdrant
- metadata captures `storage_backend`, `storage_key`, and `storage_url`

### Auto Retrieval Validation

Verify `search_mode="auto"` behavior on deployed backend.

Expected metadata should include:

- `requested_search_mode`
- `resolved_search_mode`
- `auto_enabled`
- `auto_strategy_reason`

## 6. CloudWatch Setup

### Log Groups

- `/ecs/new-adv-rag-backend`
- `/ecs/new-adv-rag-streamlit`

### Manual CloudWatch Alarms

Current custom alarms:

- `backend-alb-5xx`
- `backend-alb-response-time-high`
- `backend-ecs-cpu-high`
- `backend-ecs-memory-high`
- `rds-connections-high`
- `rds-cpu-high`
- `streamlit-ecs-cpu-high`

### ECS Autoscaling Alarms

AWS also creates additional `TargetTracking-service/...` alarms automatically for ECS service autoscaling policies.

These are:

- AWS-managed
- not the same as the manually created portfolio/demo alarms
- expected to appear in the alarm list

Do not treat them as deployment drift.

### CloudWatch Dashboard

Dashboard name:

- `new-adv-rag-ops`

Widgets included:

- manual alarm status
- backend ALB response time
- backend ECS CPU and memory
- RDS CPU and connections
- backend ALB 5xx and requests
- backend target-group health
- streamlit ECS CPU
- backend request logs

## 7. Load Testing Sequence

Run from:

```powershell
cd C:\Users\vthot\PORTFOLIO-PROJECTS\ENTERPRISE-ADV-RAG\new-adv-rag-implement
```

Recommended commands:

```powershell
.\loadtests\run_k6.ps1 -Script "health.js" -Duration "30s" -Vus "2"
.\loadtests\run_k6.ps1 -Script "query_rag.js" -Username "test4@example.com" -Password "test123" -Duration "1m" -Vus "2"
.\loadtests\run_k6.ps1 -Script "mixed_smoke.js" -Username "test4@example.com" -Password "test123" -Duration "1m" -RagVus "1" -SqlVus "1" -HybridVus "1"
```

Optional heavier demo run:

```powershell
.\loadtests\run_k6.ps1 -Script "mixed_smoke.js" -Username "test4@example.com" -Password "test123" -Duration "2m" -RagVus "4" -SqlVus "1" -HybridVus "1"
```

During run:

- open `new-adv-rag-ops`
- enable auto-refresh at `10s`
- capture screenshots during the run and again after the run with a clean custom time window

Saved result summary:

- `loadtests/results/FINAL_LOADTEST_RESULTS_20260708.md`

## 8. Current Validated Outcome

Latest live validation confirmed:

- backend health reachable over HTTPS
- Streamlit reachable over HTTPS
- ECS services at `1 running / 0 pending`
- backend and streamlit services steady-state
- CloudWatch dashboard working for screenshot capture
- health load test passed
- RAG load test passed functionally and met p95 threshold on a repeated run
- mixed smoke passed functionally but exceeded the p95 latency threshold

Interpretation:

- correctness and availability are validated
- latency optimization is the main remaining improvement area

## 9. Common Failure Modes And Fixes

### `AccessDeniedException` For Secrets Manager

Cause:

- `ecsTaskExecutionRole` lacks secret read access

Fix:

- grant `secretsmanager:GetSecretValue` on the backend secret ARN

### `CloudWatch log group does not exist`

Cause:

- ECS task definition references a missing log group

Fix:

- create the log groups before launching the service

### `CannotPullContainerError`

Cause:

- image tag does not exist in the correct ECR repo/region

Fix:

- push the image first
- confirm task definition points to the actual pushed tag

### `503` From ALB

Cause:

- no healthy targets

Fix:

- verify target-group health path, port, subnet alignment, and SG ingress

### `/health` Works But Auth or SQL Times Out

Cause:

- app container is healthy but RDS network path is blocked

Fix:

- verify RDS SG ingress from the ECS service SG

### Streamlit Points To Localhost Or Wrong Backend

Cause:

- stale `API_BASE_URL`
- stale session state
- old image build

Fix:

- set `API_BASE_URL=https://api.aiscientificlabs.com`
- redeploy Streamlit
- verify build context used the correct project folder

### Heavier Requests Fail Even Though Health Is Green

Cause:

- runtime encoding / stdout-stderr issue in container

Fix already applied:

- force UTF-8 environment config
- reconfigure stdout/stderr safely in backend startup

## 10. Useful AWS Commands

Describe services:

```powershell
aws ecs describe-services --cluster new-adv-rag-cluster --services backend-service streamlit-service --region us-east-2
```

List dashboards:

```powershell
aws cloudwatch list-dashboards --region us-east-2
```

Describe alarms:

```powershell
aws cloudwatch describe-alarms --region us-east-2
```

Get caller identity:

```powershell
aws sts get-caller-identity --region us-east-2
```

## 11. Final Deployment Checklist

- ECR repos exist in `us-east-2`
- images built from the correct project directory
- images pushed with the intended tags
- backend secret stored as valid JSON
- execution role can read the secret
- backend task role can write to S3
- log groups exist
- task definitions reference the correct image tags
- ECS services use the correct subnets and SG rules
- target groups are healthy
- backend health works
- frontend loads over HTTPS
- auth and query flows work
- upload works for admin
- Auto mode metadata is correct
- CloudWatch dashboard renders
- load-test evidence is captured

## 12. Bottom Line

This deployment is no longer just "containers running in AWS." It is a repeatable deployment path with HTTPS, real observability, ECS autoscaling, documented validation, and saved evidence from live backend load tests.
