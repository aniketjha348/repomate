# AWS Deployment — ECS Fargate (autoscaling + self-healing)

## Why ECS Fargate over EKS

**Recommendation: ECS Fargate.** For RepoMate's shape — two long-running
services (FastAPI API + Celery worker) with no Kubernetes-specific
dependencies — ECS gives you the two properties you asked for with the
least operational surface:

| Requirement | ECS Fargate | EKS |
|---|---|---|
| Autoscaling | Service autoscaling (target tracking on CPU + ALB requests/target) — native, minutes to configure | Requires the Horizontal Pod Autoscaler + metrics server + cluster autoscaler/Karpenter |
| Self-healing | ALB health-check failures drain and replace tasks automatically; deployment circuit breaker rolls back bad revisions | Pod eviction/rescheduling — same outcome, but you operate the control plane (upgrades, add-ons, IAM Roles for Service Accounts) |
| Ops burden | None at the orchestration layer | Control-plane upgrades and add-on management forever |
| Cost | Per-task vCPU/GB, no minimum | ~$73/mo control plane + nodes (some on Fargate) |

Move to EKS only when you run many heterogeneous workloads that need
Kubernetes-native tooling. Everything in the RepoMate containers is
orchestration-agnostic (health endpoint, env config, graceful
cancellation), so the switch later is a deployment change, not an app
change.

## What's in `deploy/aws/`

Terraform for: ECS cluster (Container Insights on), ALB with HTTPS
redirect and `/api/health` health checks (15s interval, 3 failures →
task replaced), API service (2 tasks baseline, scales 1→8 on 60% CPU and
500 req/target/min), Celery worker service (1–2 vCPU/2GB for the
verification sandbox), CloudWatch logs (30-day retention), Secrets
Manager references for `VYCE_API_KEY` / `GITHUB_TOKEN` (values never in
code or tfvars), and IAM execution roles scoped to exactly those secrets.

Self-healing layers (deliberately redundant):

1. **Task level** — unhealthy API tasks are replaced by ECS via ALB checks.
2. **Deployment level** — circuit breaker + rollback on bad revisions,
   min-healthy 100% / max 200% rolling deploys.
3. **Work level** — Celery `acks_late` + `task_reject_on_worker_lost`
   requeues runs that were mid-flight on a dead worker; the pipeline's
   idempotent store resumes cleanly from the run record.

## Runbook

```bash
cd deploy/aws

# 1) Secrets (once) — values stay out of the repo
aws secretsmanager create-secret --name repomate/vyce-api-key \
  --secret-string 'sk-...'
aws secretsmanager create-secret --name repomate/github-token \
  --secret-string 'ghp_...'   # or an empty-string secret if unused

# 2) Images: build and push to ECR
aws ecr create-repository --repository-name repomate/api || true
aws ecr create-repository --repository-name repomate/worker || true
aws ecr get-login-password --region "$AWS_REGION" | docker login \
  --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

docker build -f deploy/Dockerfile.api  -t "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/repomate/api:latest" .
docker build -f deploy/Dockerfile.worker -t "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/repomate/worker:latest" .
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/repomate/api:latest"
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/repomate/worker:latest"

# 3) Apply
terraform init
terraform apply \
  -var "image_api=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/repomate/api:latest" \
  -var "image_worker=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/repomate/worker:latest"

# 4) Verify self-healing: kill a task and watch ECS replace it
TASK=$(aws ecs list-tasks --cluster repomate-cluster --service-name repomate-api \
  --query 'taskArns[0]' --output text)
aws ecs stop-task --cluster repomate-cluster --task "$TASK"
aws ecs describe-services --cluster repomate-cluster --services repomate-api \
  --query 'services[0].{desired:desiredCount,running:runningCount,pending:pendingCount}'
```

Point the frontend's `NEXT_PUBLIC_API_URL` at the ALB DNS name from
`terraform output api_url` (attach an ACM certificate + HTTPS listener
before real traffic; the HTTP listener currently redirects to 443).

## Production hardening (next steps, in order)

1. **Redis**: replace the compose/dev redis with ElastiCache
   (serverless or `cache.t4g.micro`) in the same VPC; update `REDIS_URL`.
2. **PostgreSQL**: RDS Postgres (`db.t4g.micro`, Multi-AZ later) and set
   `REPOMATE_DATABASE_URL` — the SQL store is already live-tested
   (SQLite path) and schema-compatible.
3. **EFS volume** if you keep `REPOMATE_RUNS_ROOT` on disk while scaling
   the API beyond 1 task (shared run records) — or go SQL-only.
4. **Worker queue-depth autoscaling**: publish
   `ApproximateNumberOfMessagesVisible` as a custom metric and add a
   step-scaling policy on the worker service (CPU tracking is fine to
   start).
5. **WAF + rate limiting** in front of the ALB; the API already returns
   typed errors for malformed input, but edge limiting protects the
   GitHub quota.
6. **Secrets rotation**: the execution role reads secrets per task
   start, so rotation needs no redeploy.
