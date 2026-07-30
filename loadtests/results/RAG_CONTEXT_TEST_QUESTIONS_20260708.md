# RAG Context Test Questions

Use these questions to validate context awareness, retrieval quality, and Auto vs Manual behavior in the Kubernetes RAG system.

## Manual vs Auto Comparison

Question:
`What is the difference between a ConfigMap and a Secret in Kubernetes?`

Manual settings:
- `Search Mode = hybrid`
- `Rerank = On`
- `HyDE = On`
- `CRAG = Off`
- `SRAG = Off`
- `Top K = 5`

What to verify:
- Manual answer and Auto answer should be very similar.
- Auto should resolve to `hybrid` with `Rerank = On`.
- Auto should keep `HyDE = Off` for this direct object-comparison question.
- Sources should stay focused on `ConfigMap` and `Secret` docs.

## Five Context-Awareness Pairs

### 1. ConfigMap vs Secret

Question:
`What is the difference between a ConfigMap and a Secret in Kubernetes?`

Follow-up:
`For the non-sensitive one, if I inject it as environment variables instead of a volume, will updates show up automatically, or do I need to restart the Pod?`

What to verify:
- Follow-up should resolve `the non-sensitive one` to `ConfigMap`.
- Answer should say env-var updates do not refresh automatically and usually require a Pod restart.

### 2. StatefulSet vs Deployment

Question:
`How does a StatefulSet differ from a Deployment for stateful applications?`

Follow-up:
`Which one would you use for a database, and why?`

What to verify:
- Follow-up should expand to `StatefulSet or Deployment`.
- Answer should prefer `StatefulSet`.
- Sources should stay focused on StatefulSet material, not unrelated docs.

### 3. Secret Management

Question:
`What is the best practice for managing application secrets securely in Kubernetes?`

Follow-up:
`Would you still use that same object for a database password, or would you combine it with something else?`

What to verify:
- Follow-up should resolve `that same object` to `Secret`.
- Answer should say `Secret` is common, but should be combined with encryption at rest, RBAC, and optionally an external secret manager.

### 4. External vs Internal Exposure

Question:
`How do I expose a Kubernetes Deployment to external traffic?`

Follow-up:
`If I only need internal cluster access, would I still use that same resource?`

What to verify:
- Follow-up should resolve `that same resource` to `Service`.
- Answer should say internal-only access usually uses a `Service`, typically `ClusterIP`.

### 5. Readiness and Service Traffic

Question:
`When will my pod be ready to serve traffic?`

Follow-up:
`If that probe fails, will Services still send traffic to it?`

What to verify:
- Answer should tie readiness to readiness probes and ready conditions.
- Follow-up should say failed readiness means the Pod is marked unready and Services stop routing traffic to it.

## Current Expected Outcome

As of `2026-07-08`:
- Auto chooses `hybrid` for direct Kubernetes object comparisons like `ConfigMap vs Secret`.
- Auto keeps `HyDE = Off` for that comparison case.
- Follow-up rewriting is working for `ConfigMap`, `Secret`, `StatefulSet/Deployment`, and `Service`.
- Noisy sources like dashboard docs or non-Kubernetes documents should no longer appear in these five checks.

## srag flag-on Question
My Kubernetes app keeps restarting, and I am not sure whether the root cause is the liveness probe, OOMKilled, or a bad image. How should I troubleshoot it step by step?

 ### Good follow-up:
If the Pod shows CrashLoopBackOff but the readiness probe is also failing, which signal should I trust first and why?
