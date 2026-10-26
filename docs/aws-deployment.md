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

Terraform for: ECS cluster (Container Insights on), ALB with `/api/health`
health checks (15s interval, 3 failures → task replaced) and an HTTPS
listener when `certificate_arn` is supplied (otherwise HTTP forward, so a
fresh demo stack is reachable), API service (2 tasks baseline, scales 1→8 on
60% CPU and 500 req/target/min), Celery worker service (1–2 vCPU/2GB for the
verification sandbox), ElastiCache Redis as the Celery broker, an encrypted EFS
volume shared by the API and worker for run records/workspaces, CloudWatch logs
(30-day retention), Secrets Manager references for `OLLAMA_API_KEY` and, when
`github_token_secret_name` is set, `GITHUB_TOKEN` (values never in code or
tfvars), and IAM execution roles scoped to exactly those secrets.

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
aws secretsmanager create-secret --name repomate/ollama-api-key \
  --secret-string 'your-ollama-key'

# Optional, only for private repositories or higher rate limits:
aws secretsmanager create-secret --name repomate/github-token \
  --secret-string 'ghp_...'
# Omitting it is supported — pass no github_token_secret_name and the tasks
# clone unauthenticated, which is all public repositories need. Never store a
# whitespace or placeholder value here: any truthy token is sent as a bearer
# header and GitHub answers 401 even for public repos.

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
  -var "image_worker=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/repomate/worker:latest" \
  -var "allowed_origins=https://your-frontend.example.com"
# Optional: add HTTPS with an ACM certificate (must be in the same region):
#   terraform apply ... -var "certificate_arn=arn:aws:acm:..."
# Optional, only once the repomate/github-token secret exists:
#   terraform apply ... -var "github_token_secret_name=repomate/github-token"

# 4) Verify self-healing: kill a task and watch ECS replace it
TASK=$(aws ecs list-tasks --cluster repomate-cluster --service-name repomate-api \
  --query 'taskArns[0]' --output text)
aws ecs stop-task --cluster repomate-cluster --task "$TASK"
aws ecs describe-services --cluster repomate-cluster --services repomate-api \
  --query 'services[0].{desired:desiredCount,running:runningCount,pending:pendingCount}'
```

Point the frontend's `NEXT_PUBLIC_API_URL` at the ALB DNS name from
`terraform output api_url`. Without `certificate_arn` the stack serves plain
HTTP (fine for a demo); set the variable to attach an ACM certificate and get
an HTTP→HTTPS redirect plus an HTTPS listener.

Cost honesty: this is **not** a free-tier stack. The ALB, two API tasks, one
worker task, ElastiCache node and EFS all bill hourly. Run the AWS pricing
calculator for your region before applying.

## Verified live behaviour (ap-south-1, 2026-10-26)

Applied from a cold account. The ALB target reached `healthy`, `/api/health`
answered 200 with the model provider resolved, CORS echoed only the
configured origin (an unlisted origin gets `400 Disallowed CORS origin`),
`extra="forbid"` produced a 422, an unknown run id 404s on `/api/runs/{id}`,
`/events` and `/artifacts`, and a real Celery run against
`octocat/Hello-World` wrote a `DOCS_DIFF` patch plus `CONTRIBUTION_PLAN.md`
to EFS. Cancelling a run returned 202 and landed on `CANCELLED`.
`aws ecs stop-task` on the live API task produced a replacement task healthy
in about 65 seconds, and the dead task's artifacts were still downloadable
from the new one — the EFS-plus-`acks_late` claim, tested rather than
asserted.

**One verification check always fails on Fargate.** `sandbox-egress-isolation`
needs an unprivileged `bwrap` user namespace and the Fargate kernel refuses
to create one:

```
bwrap: No permissions to create a new namespace, likely because the kernel
does not allow non-privileged user namespaces.
```

So `receipt.sandbox.policy_enforced` is `false`, `VERIFY` reports FAILED and
the run is stored as `FAILED` even though `patch-applies-on-pinned-commit`
passed. Do not read that status as a model failure. Either treat the
deployment as a demo (artifacts are still served and correct) or run the
worker on an **EC2 launch type** that permits user namespaces, which costs a
host but lets the probe enforce egress policy and reach `SUCCEEDED`.

## HTTPS (and why `api_url` starts with `http://`)

A browser on an `https://` frontend will not call an `http://` API — mixed
content is blocked, not merely warned. ACM cannot issue a certificate for
`*.elb.amazonaws.com`, so plain HTTP is the default and you must add one of:

- a registered domain: Route 53 hosted zone + ACM certificate (DNS
  validation, free in the same region) and then `-var certificate_arn=…`,
  which turns the port-80 listener into a redirect and adds 443;
- CloudFront in front of the ALB using its default certificate, which needs
  no domain but **does** need the account enabled for CloudFront. New
  accounts fail with `AccessDenied: Your account must be verified before you
  can add new CloudFront resources` until AWS Support verifies the account.

## CI/CD

`.github/workflows/deploy-aws.yml` chains `ci.yml` → ECR images →
`terraform plan`/`apply` → `aws ecs wait services-stable` → a `/api/health`
curl gate → a `NEXT_PUBLIC_API_URL` repo-variable update → a dispatch of
`deploy-vercel.yml`, because `NEXT_PUBLIC_*` is baked into the client bundle
at build time and the frontend only follows the API after a rebuild.

Two pieces of setup it assumes:

- **State**: `backend.tf` puts Terraform state in
  `s3://repomate-tf-state-<account>/ap-south-1/repomate.tfstate` with native
  S3 locking. CI and your laptop must share it; a local `tfstate` makes every
  CI run build a second stack.
- **Auth**: the workflow assumes `repomate-github-deployments` through GitHub's
  OIDC provider, conditioned on `repo:<owner>/<repo>:environment:production`,
  so no long-lived AWS key exists in GitHub. That means the repository needs a
  `production` environment plus the `AWS_DEPLOY_ROLE_ARN` and `ALLOWED_ORIGINS`
  variables; the first job fails closed if either is missing. The role is
  `PowerUserAccess` plus an inline policy limited to `iam:*` on `repomate*`
  roles/policies, because Terraform creates the task execution roles.

`OLLAMA_API_KEY` and any `GITHUB_TOKEN` deliberately stay in Secrets Manager
only — they are runtime secrets, never CI secrets.

## Production hardening (next steps, in order)

1. **Redis HA**: the stack provisions a single `cache.t3.micro` node. Replace
   it with a Multi-AZ ElastiCache replication group (and point `REDIS_URL` at
   the primary endpoint) before relying on it for durable execution.
2. **PostgreSQL**: RDS Postgres (`db.t4g.micro`, Multi-AZ later) and set
   `REPOMATE_DATABASE_URL`. The SQL store is live-tested on SQLite; the
   PostgreSQL dialect shares the same schema/queries and should be
   smoke-tested in staging before production. With RDS, EFS only needs to hold
   temporary workspaces.
3. **EFS lifecycle**: the encrypted EFS volume is shared by the API and worker.
   Add a backup policy and move workspaces to a lifecycle-managed directory if
   you keep large repositories around.
4. **Worker queue-depth autoscaling**: publish
   `ApproximateNumberOfMessagesVisible` as a custom metric and add a
   step-scaling policy on the worker service (CPU tracking is fine to
   start).
5. **WAF + rate limiting** in front of the ALB; the API already returns
   typed errors for malformed input, but edge limiting protects the
   GitHub quota.
6. **Secrets rotation**: the execution role reads secrets per task
   start, so rotation needs no redeploy.
