# Enterprise Advanced RAG Commands Runbook

This is the PowerShell-first setup, development, testing, Docker, data-service,
AWS deployment, verification, rollback, and GitHub runbook for this repository.

Run commands from:

```powershell
cd C:\Users\vthot\PORTFOLIO-PROJECTS\ENTERPRISE-ADV-RAG\new-adv-rag-implement
```

Replace example usernames, passwords, resource IDs, and image tags. Never commit
`.env`, API keys, bearer tokens, database passwords, or downloaded AWS secrets.

## 1. Prerequisites

Required tools:

- Git
- Python 3.12
- Docker Desktop
- AWS CLI v2
- PowerShell 5.1 or newer
- k6 for load tests

Check installations:

```powershell
git --version
python --version
docker version
docker compose version
aws --version
k6 version
```

Optional Windows installation commands:

```powershell
winget install --id Git.Git
winget install --id Python.Python.3.12
winget install --id Docker.DockerDesktop
winget install --id Amazon.AWSCLI
winget install --id GrafanaLabs.k6
```

Restart PowerShell after installing command-line tools.

## 2. Clone and Enter the Repository

```powershell
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd new-adv-rag-implement
git status
git branch --show-current
```

For an existing checkout:

```powershell
git fetch origin
git pull --ff-only origin main
```

Do not pull over uncommitted work without reviewing `git status` first.

## 3. Create the Python Environment

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Verify imports:

```powershell
python -c "import app.main; import app.rag.service; import app.sql.service; print('imports-ok')"
```

Leave the environment later with:

```powershell
deactivate
```

## 4. Configure Local Environment Variables

Create the local file:

```powershell
Copy-Item .env.example .env
notepad .env
```

Minimum local values:

```dotenv
OPENAI_API_KEY=<YOUR_OPENAI_KEY>
DATABASE_URL=postgresql://postgres:postgres@localhost:5434/adv_rag
QDRANT_URL=http://localhost:6334
QDRANT_COLLECTION=new_adv_rag_documents
QDRANT_API_KEY=
UPSTASH_REDIS_URL=<OPTIONAL_UPSTASH_REST_URL>
UPSTASH_REDIS_TOKEN=<OPTIONAL_UPSTASH_TOKEN>
JWT_SECRET=<GENERATE_A_LONG_RANDOM_VALUE>
TAVILY_API_KEY=<OPTIONAL_TAVILY_KEY>
STORAGE_BACKEND=local
AWS_REGION=us-east-2
```

Generate a development JWT secret:

```powershell
$bytes = New-Object byte[] 48
[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
[Convert]::ToBase64String($bytes)
```

Confirm the secrets file is ignored:

```powershell
git check-ignore .env
git status --short
```

## 5. Static Validation and Unit/Integration Tests

Activate the virtual environment first, then run:

```powershell
.\.venv\Scripts\python.exe scripts\add_learner_docs.py
.\.venv\Scripts\python.exe -m ruff check app evals Eval scripts ui tests
.\.venv\Scripts\python.exe -m compileall -q app evals Eval scripts ui tests
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

Expected current regression result: `83 passed` or more as tests are added.

Run individual layers:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit -q
.\.venv\Scripts\python.exe -m pytest tests\integration -q
.\.venv\Scripts\python.exe -m pytest tests\contract -q
```

Run one file or test:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_rag_source_filtering.py -q
.\.venv\Scripts\python.exe -m pytest tests\integration\test_query_api.py::test_query_hybrid_returns_combined_response -q
```

Build the distributable wheel:

```powershell
New-Item -ItemType Directory -Force .cache\wheels | Out-Null
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir .cache\wheels
```

## 6. Start Local PostgreSQL and Qdrant

Start only infrastructure:

```powershell
docker compose up -d postgres qdrant
docker compose ps
```

View logs:

```powershell
docker compose logs --tail=100 postgres
docker compose logs --tail=100 qdrant
```

Stop containers without deleting data volumes:

```powershell
docker compose stop
```

Do not use `docker compose down -v` unless you intentionally want to destroy local volumes.

## 7. PostgreSQL Migrations and Seed Data

The seed script reads migrations from `db/migrations`.

Important: `003_seed_k8s_ops.sql` recreates operational demo tables. Never run it
against a production database. Verify `DATABASE_URL` before continuing.

Run local migrations and demo users without document ingestion:

```powershell
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5434/adv_rag"
.\.venv\Scripts\python.exe scripts\seed_db.py --no-ingest
```

Open a local SQL shell:

```powershell
docker compose exec postgres psql -U postgres -d adv_rag
```

Exit `psql` with `\q`.

List tables and row counts:

```powershell
docker compose exec postgres psql -U postgres -d adv_rag -c "\dt"
docker compose exec postgres psql -U postgres -d adv_rag -c "SELECT COUNT(*) FROM users;"
docker compose exec postgres psql -U postgres -d adv_rag -c "SELECT COUNT(*) FROM incidents;"
docker compose exec postgres psql -U postgres -d adv_rag -c "SELECT COUNT(*) FROM alerts;"
```

Useful read-only checks:

```powershell
docker compose exec postgres psql -U postgres -d adv_rag -c "SELECT severity, COUNT(*) FROM incidents GROUP BY severity ORDER BY severity;"
docker compose exec postgres psql -U postgres -d adv_rag -c "SELECT severity, resolved, COUNT(*) FROM alerts GROUP BY severity, resolved ORDER BY severity, resolved;"
docker compose exec postgres psql -U postgres -d adv_rag -c "SELECT name, region, environment FROM clusters ORDER BY name LIMIT 20;"
```

Safe update pattern: inspect, use a transaction, update a specific key, verify, commit.

```powershell
docker compose exec postgres psql -U postgres -d adv_rag -c "SELECT alert_id, severity, resolved FROM alerts WHERE alert_id = 1;"
docker compose exec postgres psql -U postgres -d adv_rag -c "BEGIN; UPDATE alerts SET resolved = TRUE WHERE alert_id = 1 RETURNING alert_id, severity, resolved; COMMIT;"
```

Update deployment replicas only after identifying the exact row:

```powershell
docker compose exec postgres psql -U postgres -d adv_rag -c "SELECT deployment_id, name, namespace, replicas FROM deployments WHERE deployment_id = 1;"
docker compose exec postgres psql -U postgres -d adv_rag -c "BEGIN; UPDATE deployments SET replicas = 3 WHERE deployment_id = 1 RETURNING deployment_id, name, replicas; COMMIT;"
```

Resolve an incident with an explicit MTTR:

```powershell
docker compose exec postgres psql -U postgres -d adv_rag -c "SELECT incident_id, severity, started_at, resolved_at FROM incidents WHERE incident_id = 1;"
docker compose exec postgres psql -U postgres -d adv_rag -c "BEGIN; UPDATE incidents SET resolved_at = now(), mttr_minutes = GREATEST(1, EXTRACT(EPOCH FROM (now() - started_at))::int / 60) WHERE incident_id = 1 AND resolved_at IS NULL RETURNING incident_id, resolved_at, mttr_minutes; COMMIT;"
```

Back up local PostgreSQL:

```powershell
New-Item -ItemType Directory -Force .cache\backups | Out-Null
docker compose exec postgres pg_dump -U postgres -d adv_rag -Fc -f /tmp/adv_rag.dump
docker compose cp postgres:/tmp/adv_rag.dump .cache\backups\adv_rag.dump
```

## 8. Qdrant Health and Collection Checks

Local health and collections:

```powershell
curl.exe -fsS http://localhost:6334/healthz
curl.exe -fsS http://localhost:6334/collections
curl.exe -fsS http://localhost:6334/collections/new_adv_rag_documents
```

Count indexed points:

```powershell
$body = @{ exact = $true } | ConvertTo-Json
Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:6334/collections/new_adv_rag_documents/points/count" `
    -ContentType "application/json" `
    -Body $body
```

For Qdrant Cloud, use environment variables and never print the API key:

```powershell
$headers = @{ "api-key" = $env:QDRANT_API_KEY }
Invoke-RestMethod -Uri "$env:QDRANT_URL/collections" -Headers $headers
```

## 9. Upstash Redis: Ping, Inspect, and Clear

Load credentials into the current PowerShell process without echoing them:

```powershell
$env:UPSTASH_REDIS_URL = "https://<YOUR_DATABASE>.upstash.io"
$env:UPSTASH_REDIS_TOKEN = "<YOUR_TOKEN>"
```

Ping Upstash through its REST API:

```powershell
$headers = @{ Authorization = "Bearer $env:UPSTASH_REDIS_TOKEN" }
Invoke-RestMethod `
    -Method Post `
    -Uri "$env:UPSTASH_REDIS_URL/ping" `
    -Headers $headers
```

Expected response contains `PONG`.

Check database size:

```powershell
Invoke-RestMethod `
    -Method Post `
    -Uri "$env:UPSTASH_REDIS_URL/dbsize" `
    -Headers $headers
```

Preferred cache clear: use the authenticated application admin endpoint so only
application cache keys and statistics are handled through application policy.

```powershell
$ApiBase = "http://localhost:8003"
$AdminUsername = "<ADMIN_USERNAME>"
$AdminPassword = "<ADMIN_PASSWORD>"

$login = Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiBase/auth/login" `
    -ContentType "application/json" `
    -Body (@{ username=$AdminUsername; password=$AdminPassword } | ConvertTo-Json)

$adminHeaders = @{ Authorization = "Bearer $($login.token)" }

Invoke-RestMethod `
    -Method Get `
    -Uri "$ApiBase/admin/cache/stats" `
    -Headers $adminHeaders

Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiBase/admin/cache/clear" `
    -Headers $adminHeaders `
    -ContentType "application/json" `
    -Body (@{ tier="all"; reset_stats=$true } | ConvertTo-Json)
```

Clear only one RAG answer:

```powershell
$cacheContext = @{
    schema_version = 29
    top_k = 5
    search_mode = "hybrid"
    enable_rerank = $true
    enable_hyde = $false
    enable_crag = $true
    enable_self_reflective = $false
}

$body = @{
    tier = "rag_answer"
    question = "What does our escalation policy say for P1 incidents?"
    cache_context = $cacheContext
    reset_stats = $false
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiBase/admin/cache/clear" `
    -Headers $adminHeaders `
    -ContentType "application/json" `
    -Body $body
```

Emergency full Upstash clear deletes every key in that database, including keys
owned by other applications. Use only with an isolated project database:

```powershell
$confirmation = Read-Host "Type FLUSH-UPSTASH to delete every Redis key"
if ($confirmation -ne "FLUSH-UPSTASH") { throw "Cancelled" }

Invoke-RestMethod `
    -Method Post `
    -Uri "$env:UPSTASH_REDIS_URL/flushdb" `
    -Headers $headers
```

## 10. Run Backend and Frontend Without Docker

Terminal 1:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload
```

Terminal 2:

```powershell
.\.venv\Scripts\Activate.ps1
$env:API_BASE_URL = "http://localhost:8003"
streamlit run ui\streamlit\app.py --server.port 8501
```

Health checks:

```powershell
curl.exe -fsS http://localhost:8003/health
curl.exe -fsS http://localhost:8501/_stcore/health
```

Open:

- Backend docs: `http://localhost:8003/docs`
- Frontend: `http://localhost:8501`

## 11. Build and Run Docker Images

Validate Compose:

```powershell
docker compose config --quiet
```

Build directly:

```powershell
docker build -f infra/docker/backend.Dockerfile -t new-adv-rag-backend:local .
docker build -f infra/docker/streamlit.Dockerfile -t new-adv-rag-streamlit:local .
```

Build and start through Compose:

```powershell
docker compose build app streamlit
docker compose up -d
docker compose ps
```

Wait for model imports during the first backend startup, then verify:

```powershell
curl.exe -fsS http://localhost:8003/health
curl.exe -fsS http://localhost:8501/_stcore/health
docker compose logs --tail=150 app
docker compose logs --tail=100 streamlit
```

Rebuild after code changes:

```powershell
docker compose up -d --build app streamlit
```

## 12. Authentication and Manual API Tests

Register a disposable local user:

```powershell
$ApiBase = "http://localhost:8003"
$Username = "new.user.$([guid]::NewGuid().ToString('N').Substring(0,8))@example.com"
$Password = "Test123!"

$registration = Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiBase/auth/register" `
    -ContentType "application/json" `
    -Body (@{ username=$Username; password=$Password } | ConvertTo-Json)

$authHeaders = @{ Authorization = "Bearer $($registration.token)" }
```

RAG question:

```powershell
$query = @{
    question = "What does our escalation policy say for P1 incidents?"
    top_k = 5
    search_mode = "hybrid"
    enable_rerank = $true
    enable_hyde = $false
    enable_crag = $true
    enable_self_reflective = $false
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiBase/query" `
    -Headers $authHeaders `
    -ContentType "application/json" `
    -Body $query
```

The same API is available with an explicit version prefix:

```powershell
Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiBase/api/v1/query" `
    -Headers $authHeaders `
    -ContentType "application/json" `
    -Body $query
```

Run all maintained frontend presets and SQL approval checks:

```powershell
powershell -ExecutionPolicy Bypass `
    -File scripts\live_preset_smoke.ps1 `
    -ApiBase http://localhost:8003
```

## 13. Evaluation Commands

List available profiles:

```powershell
.\.venv\Scripts\python.exe -c "from evals.runners.profiles import PROFILES; print(*PROFILES, sep=chr(10))"
```

Cheap deterministic CI smoke:

```powershell
.\.venv\Scripts\python.exe -m evals.runners.run `
    --profile hybrid `
    --filter hybrid `
    --mode fixture `
    --scorer heuristic `
    --output evals/reports/results/manual_fixture_hybrid.json
```

Local service evaluation against local PostgreSQL and Qdrant:

```powershell
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5434/adv_rag"
$env:QDRANT_URL = "http://localhost:6334"

.\.venv\Scripts\python.exe -m evals.runners.run `
    --profile "hybrid+rerank+crag" `
    --mode local `
    --ids q-029,q-030,q-031,q-032 `
    --scorer llm `
    --environment local `
    --true-documents 50 `
    --noisy-documents 324 `
    --output evals/reports/results/manual_hybrid_sql_local.json
```

Deployed AWS evaluation:

```powershell
.\.venv\Scripts\python.exe -m evals.runners.run `
    --profile "hybrid+rerank+crag" `
    --mode http `
    --api-base https://api.aiscientificlabs.com `
    --ids q-029,q-030,q-031,q-032 `
    --scorer llm `
    --environment aws `
    --true-documents 50 `
    --noisy-documents 324 `
    --output evals/reports/results/manual_hybrid_sql_aws.json
```

LLM evaluation uses paid API calls. Do not confuse fixture heuristic metrics with
production LLM-judge metrics.

## 14. Load Tests

Health-only local test:

```powershell
.\loadtests\run_k6.ps1 `
    -Script "health.js" `
    -BaseUrl "http://localhost:8003" `
    -Duration "10s" `
    -Vus "3"
```

Authenticated RAG test:

```powershell
.\loadtests\run_k6.ps1 `
    -Script "query_rag.js" `
    -BaseUrl "http://localhost:8003" `
    -Username "<TEST_USERNAME>" `
    -Password "<TEST_PASSWORD>" `
    -Duration "30s" `
    -Vus "1"
```

Small mixed test:

```powershell
.\loadtests\run_k6.ps1 `
    -Script "mixed_smoke.js" `
    -BaseUrl "http://localhost:8003" `
    -Username "<TEST_USERNAME>" `
    -Password "<TEST_PASSWORD>" `
    -Duration "30s" `
    -RagVus "1" `
    -SqlVus "1" `
    -HybridVus "1"
```

HTTP 429 responses mean the configured per-user rate limiter was reached. Use
deliberate pacing or separate authorized load-test identities when measuring capacity.

## 15. Configure AWS CLI

```powershell
aws configure
aws sts get-caller-identity
aws configure get region
```

Project deployment variables:

```powershell
$AWS_REGION = "us-east-2"
$AWS_ACCOUNT_ID = "785282204559"
$ECS_CLUSTER = "new-adv-rag-cluster"
$BACKEND_SERVICE = "backend-service"
$STREAMLIT_SERVICE = "streamlit-service"
$TAG = "$(Get-Date -Format yyyyMMdd-HHmm)-release"

$REGISTRY = "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
$BACKEND_IMAGE = "$REGISTRY/new-adv-rag-backend:$TAG"
$STREAMLIT_IMAGE = "$REGISTRY/new-adv-rag-streamlit:$TAG"
```

Use a new immutable tag for every deployment. Do not overwrite a known-good tag.

## 16. AWS Preflight

```powershell
aws sts get-caller-identity --region $AWS_REGION
aws ecr describe-repositories --region $AWS_REGION
aws ecs describe-services `
    --cluster $ECS_CLUSTER `
    --services $BACKEND_SERVICE $STREAMLIT_SERVICE `
    --region $AWS_REGION
```

Record current rollback task definitions:

```powershell
$PREVIOUS_BACKEND_TASK = aws ecs describe-services `
    --cluster $ECS_CLUSTER `
    --services $BACKEND_SERVICE `
    --region $AWS_REGION `
    --query "services[0].taskDefinition" `
    --output text

$PREVIOUS_STREAMLIT_TASK = aws ecs describe-services `
    --cluster $ECS_CLUSTER `
    --services $STREAMLIT_SERVICE `
    --region $AWS_REGION `
    --query "services[0].taskDefinition" `
    --output text

$PREVIOUS_BACKEND_TASK
$PREVIOUS_STREAMLIT_TASK
```

Verify required Secrets Manager key names without printing values:

```powershell
aws secretsmanager get-secret-value `
    --secret-id prod/advrag/backend `
    --region $AWS_REGION `
    --query SecretString `
    --output text |
    .\.venv\Scripts\python.exe -c "import json,sys; print(*sorted(json.load(sys.stdin)), sep=chr(10))"
```

Expected Redis keys include `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_TOKEN`.

## 17. Build and Push AWS Images

Login to ECR:

```powershell
aws ecr get-login-password --region $AWS_REGION |
    docker login --username AWS --password-stdin $REGISTRY
```

Build:

```powershell
docker build `
    -f infra/docker/backend.Dockerfile `
    -t $BACKEND_IMAGE .

docker build `
    -f infra/docker/streamlit.Dockerfile `
    -t $STREAMLIT_IMAGE .
```

Push:

```powershell
docker push $BACKEND_IMAGE
docker push $STREAMLIT_IMAGE
```

Confirm tags exist:

```powershell
aws ecr describe-images `
    --repository-name new-adv-rag-backend `
    --image-ids imageTag=$TAG `
    --region $AWS_REGION

aws ecr describe-images `
    --repository-name new-adv-rag-streamlit `
    --image-ids imageTag=$TAG `
    --region $AWS_REGION
```

## 18. Generate ECS Task Payloads Without Breaking Secrets

Clone the currently running task definitions and change only the image. This is
safer than registering a stale repository template.

```powershell
New-Item -ItemType Directory -Force .cache\deployment | Out-Null
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function New-EcsTaskPayload {
    param(
        [Parameter(Mandatory=$true)][string]$Family,
        [Parameter(Mandatory=$true)][string]$Image,
        [Parameter(Mandatory=$true)][string]$Output
    )

    $task = (
        aws ecs describe-task-definition `
            --task-definition $Family `
            --region $AWS_REGION |
        ConvertFrom-Json
    ).taskDefinition

    if (-not $task) { throw "Could not load task definition: $Family" }
    $task.containerDefinitions[0].image = $Image

    $payload = [ordered]@{
        family                  = $task.family
        taskRoleArn             = $task.taskRoleArn
        executionRoleArn        = $task.executionRoleArn
        networkMode             = $task.networkMode
        containerDefinitions    = $task.containerDefinitions
        volumes                 = $task.volumes
        placementConstraints    = $task.placementConstraints
        requiresCompatibilities = $task.requiresCompatibilities
        cpu                     = $task.cpu
        memory                  = $task.memory
    }

    if ($task.runtimePlatform) {
        $payload.runtimePlatform = $task.runtimePlatform
    }

    $json = $payload | ConvertTo-Json -Depth 100
    $fullOutputPath = [System.IO.Path]::GetFullPath((Join-Path $PWD $Output))
    [System.IO.File]::WriteAllText($fullOutputPath, $json, $Utf8NoBom)
}

New-EcsTaskPayload `
    -Family "new-adv-rag-backend" `
    -Image $BACKEND_IMAGE `
    -Output ".cache\deployment\backend-task.json"

New-EcsTaskPayload `
    -Family "new-adv-rag-streamlit" `
    -Image $STREAMLIT_IMAGE `
    -Output ".cache\deployment\streamlit-task.json"
```

Validate JSON before registration:

```powershell
Get-Content .cache\deployment\backend-task.json -Raw | ConvertFrom-Json | Out-Null
Get-Content .cache\deployment\streamlit-task.json -Raw | ConvertFrom-Json | Out-Null
```

## 19. Register New ECS Task Revisions

```powershell
$BACKEND_TASK = (
    aws ecs register-task-definition `
        --cli-input-json file://.cache/deployment/backend-task.json `
        --region $AWS_REGION |
    ConvertFrom-Json
).taskDefinition.taskDefinitionArn

$STREAMLIT_TASK = (
    aws ecs register-task-definition `
        --cli-input-json file://.cache/deployment/streamlit-task.json `
        --region $AWS_REGION |
    ConvertFrom-Json
).taskDefinition.taskDefinitionArn

Write-Host "Backend task: $BACKEND_TASK"
Write-Host "Streamlit task: $STREAMLIT_TASK"

if (-not $BACKEND_TASK -or -not $STREAMLIT_TASK) {
    throw "Task registration failed; do not continue"
}
```

The files are written without a UTF-8 BOM because AWS CLI rejects BOM-prefixed JSON.

## 20. Deploy Backend, Then Streamlit

Deploy backend first:

```powershell
aws ecs update-service `
    --cluster $ECS_CLUSTER `
    --service $BACKEND_SERVICE `
    --task-definition $BACKEND_TASK `
    --region $AWS_REGION

aws ecs wait services-stable `
    --cluster $ECS_CLUSTER `
    --services $BACKEND_SERVICE `
    --region $AWS_REGION

curl.exe -fsS https://api.aiscientificlabs.com/health
```

Stop and investigate if the backend does not reach steady state. Do not deploy the
frontend on top of an unhealthy backend.

Deploy Streamlit:

```powershell
aws ecs update-service `
    --cluster $ECS_CLUSTER `
    --service $STREAMLIT_SERVICE `
    --task-definition $STREAMLIT_TASK `
    --region $AWS_REGION

aws ecs wait services-stable `
    --cluster $ECS_CLUSTER `
    --services $STREAMLIT_SERVICE `
    --region $AWS_REGION

curl.exe -fsS https://rag.aiscientificlabs.com/_stcore/health
```

## 21. AWS Deployment Verification

```powershell
aws ecs describe-services `
    --cluster $ECS_CLUSTER `
    --services $BACKEND_SERVICE $STREAMLIT_SERVICE `
    --region $AWS_REGION `
    --query "services[].{service:serviceName,task:taskDefinition,running:runningCount,pending:pendingCount,rollout:deployments[0].rolloutState}"
```

Expected for both services:

- `running = 1`
- `pending = 0`
- `rollout = COMPLETED`

Inspect recent service events:

```powershell
aws ecs describe-services `
    --cluster $ECS_CLUSTER `
    --services $BACKEND_SERVICE $STREAMLIT_SERVICE `
    --region $AWS_REGION `
    --query "services[].{service:serviceName,events:events[0:10].[createdAt,message]}"
```

Tail logs:

```powershell
aws logs tail /ecs/new-adv-rag-backend --since 15m --follow --region $AWS_REGION
aws logs tail /ecs/new-adv-rag-streamlit --since 15m --follow --region $AWS_REGION
```

Use separate terminals for `--follow`, or omit it for a finite result.

Run presets against AWS:

```powershell
powershell -ExecutionPolicy Bypass `
    -File scripts\live_preset_smoke.ps1 `
    -ApiBase https://api.aiscientificlabs.com
```

Run AWS health load:

```powershell
.\loadtests\run_k6.ps1 `
    -Script "health.js" `
    -BaseUrl "https://api.aiscientificlabs.com" `
    -Duration "10s" `
    -Vus "3"
```

## 22. AWS Rollback

If post-deployment checks fail, restore the task definitions recorded during preflight:

```powershell
aws ecs update-service `
    --cluster $ECS_CLUSTER `
    --service $BACKEND_SERVICE `
    --task-definition $PREVIOUS_BACKEND_TASK `
    --force-new-deployment `
    --region $AWS_REGION

aws ecs update-service `
    --cluster $ECS_CLUSTER `
    --service $STREAMLIT_SERVICE `
    --task-definition $PREVIOUS_STREAMLIT_TASK `
    --force-new-deployment `
    --region $AWS_REGION

aws ecs wait services-stable `
    --cluster $ECS_CLUSTER `
    --services $BACKEND_SERVICE $STREAMLIT_SERVICE `
    --region $AWS_REGION
```

Verify health after rollback.

## 23. Git and GitHub Delivery

Inspect everything first:

```powershell
git status --short
git diff --check
git diff --stat
git diff
```

Confirm secrets are not staged:

```powershell
git status --short | Select-String -Pattern "\.env|secret|credential|token|\.cache"
```

Stage intentionally:

```powershell
git add app db evals ui infra tests scripts docs .github
git add README.md WRITEUP.md AWS_DEPLOYMENT.md REBUILD_FROM_SCRATCH_GUIDE.md
git add pyproject.toml docker-compose.yml requirements.runtime.txt requirements.streamlit.txt
git status --short
```

If the complete reviewed repository change is intended, `git add -A` also records
moves and deletions, but review the staged result immediately afterward:

```powershell
git add -A
git diff --cached --check
git diff --cached --stat
git status --short
```

Commit and push:

```powershell
git commit -m "refactor: adopt enterprise repository structure and operations runbook"
git push origin main
```

Recommended feature-branch workflow:

```powershell
git switch -c refactor/enterprise-structure
git push -u origin refactor/enterprise-structure
```

Then open a pull request and require CI to pass before merging.

## 24. Final Release Checklist

```text
[ ] .env and credentials are not tracked
[ ] learner-documentation audit is idempotent
[ ] Ruff passes
[ ] compileall passes
[ ] all unit/integration/contract tests pass
[ ] fixture eval smoke passes
[ ] Docker images build
[ ] local backend and frontend health pass
[ ] frontend presets and SQL approval pass
[ ] immutable ECR tags exist
[ ] previous ECS task definitions are recorded
[ ] backend reaches steady state before frontend deployment
[ ] AWS backend and frontend HTTPS health pass
[ ] deployed presets/evals pass
[ ] load-test results are interpreted with rate limits in mind
[ ] CloudWatch logs show no startup or request errors
[ ] Git staged diff contains no secrets
[ ] GitHub CI passes
```

## 25. Common Troubleshooting

`Invalid JSON received` during ECS task registration:

- validate with `ConvertFrom-Json`
- write the file with `[System.Text.UTF8Encoding]::new($false)`
- do not use BOM-producing output for AWS CLI JSON

`$Output` is not a legal path:

- run the write command inside `New-EcsTaskPayload`
- provide all mandatory function parameters
- use `Join-Path $PWD $Output` before `GetFullPath`

Backend ECS task cannot retrieve an Upstash secret:

- confirm Secrets Manager contains `UPSTASH_REDIS_REST_URL`
- the task environment variable may remain `UPSTASH_REDIS_URL`
- its `valueFrom` must point to the actual REST URL JSON key

Local backend returns an empty response immediately after startup:

- wait for model imports to complete
- check `docker compose logs --tail=200 app`
- retry `/health`

Load test receives many 429 responses:

- the per-user rate limiter is working
- lower VUs, add pacing, or use separately authorized test identities
- do not describe rate-limit rejection as an application crash

Eval reports missing SQL tables:

- verify local `DATABASE_URL`
- run `scripts/seed_db.py --no-ingest` only against the local demo database
- never seed the production database casually
