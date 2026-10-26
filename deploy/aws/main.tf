# RepoMate on AWS ECS Fargate — autoscaling + self-healing.
#
# Topology:
#   ALB -> "/api/*" to the ECS "api" service (Fargate, 0.5 vCPU/1GB),
#         everything else to the ECS "web" service (Next.js, when image_web is
#         set) — one origin, so the browser never crosses schemes.
#   ECS "worker" service (Celery)  <- ElastiCache Redis (provisioned below)
#   API + worker share run storage on EFS
#   Secrets (OLLAMA_API_KEY, GITHUB_TOKEN) via AWS Secrets Manager — never in tfvars
#
# Self-healing comes from three cooperating mechanisms:
#   1. ALB health checks fail -> ECS replaces the task
#   2. ECS deployment circuit breaker + autoscaling roll back bad revisions
#   3. Celery acks-late + task_reject_on_worker_lost requeues work from dead workers
#
# See docs/aws-deployment.md for the full runbook (ECR build/push, secrets,
# apply order, RDS/ElastiCache production options).

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ---- secrets (create once, out-of-band; only references live here) ----

data "aws_secretsmanager_secret" "ollama_key" {
  name = "${var.project}/ollama-api-key"
}

data "aws_secretsmanager_secret" "github_token" {
  count = var.github_token_secret_name == "" ? 0 : 1
  name  = var.github_token_secret_name
}

# ---- cluster --------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = "${var.project}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ---- networking: ALB + health-checked target group -------------------------

resource "aws_security_group" "alb" {
  name_prefix = "${var.project}-alb-"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "services" {
  name_prefix = "${var.project}-svc-"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # The frontend task listens on 3000 and is reached only through the ALB.
  ingress {
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ---- shared run storage: EFS (API and worker mount the same files) ----------
#
# Without this, a Celery worker writes run records to its own ephemeral disk
# and the API can never read them. EFS also keeps file-store runs visible
# across API task restarts and autoscaling.

resource "aws_security_group" "efs" {
  name_prefix = "${var.project}-efs-"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.services.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_efs_file_system" "runs" {
  creation_token = "${var.project}-runs"
  encrypted      = true
}

resource "aws_efs_mount_target" "runs" {
  count           = length(data.aws_subnets.public.ids)
  file_system_id  = aws_efs_file_system.runs.id
  subnet_id       = data.aws_subnets.public.ids[count.index]
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_access_point" "runs" {
  file_system_id = aws_efs_file_system.runs.id

  # The images run as the non-root ``repomate`` user (UID/GID 1000). The
  # access point makes EFS enforce those IDs, so the container can write.
  posix_user {
    uid = 1000
    gid = 1000
  }

  root_directory {
    path = "/repomate"
    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "755"
    }
  }
}

# ---- Celery broker: ElastiCache Redis --------------------------------------

resource "aws_security_group" "redis" {
  name_prefix = "${var.project}-redis-"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.services.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${var.project}-redis"
  subnet_ids = data.aws_subnets.public.ids
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "${var.project}-redis"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = "cache.t3.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.redis.name
  security_group_ids   = [aws_security_group.redis.id]
  apply_immediately    = true
}

resource "aws_lb" "api" {
  name_prefix        = substr(var.project, 0, 6)
  load_balancer_type = "application"
  subnets            = data.aws_subnets.public.ids
  security_groups    = [aws_security_group.alb.id]
}

resource "aws_lb_target_group" "api" {
  name_prefix = substr(var.project, 0, 6)
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "ip"

  # Self-healing: an API task that stops answering /api/health is drained
  # and replaced by ECS within these bounds.
  health_check {
    path                = "/api/health"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

# ---- optional frontend on the same ALB --------------------------------------
#
# Path routing rather than a second load balancer: the browser talks to one
# origin, so an https:// page never has to call an http:// API and /api/* still
# lands on the FastAPI targets.

locals {
  web_enabled     = var.image_web != ""
  http_default_tg = local.web_enabled ? aws_lb_target_group.web[0].arn : aws_lb_target_group.api.arn
}

resource "aws_lb_target_group" "web" {
  count       = local.web_enabled ? 1 : 0
  name_prefix = substr(var.project, 0, 6)
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "ip"

  health_check {
    path                = "/"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

# Only one of the two listeners carries traffic: with a certificate port 80
# redirects, otherwise there is no port 443 listener at all.
resource "aws_lb_listener_rule" "api" {
  count        = local.web_enabled ? 1 : 0
  listener_arn = var.certificate_arn == "" ? aws_lb_listener.http.arn : aws_lb_listener.https[0].arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80

  # With a certificate, redirect to HTTPS. Without one, forward on HTTP so a
  # freshly applied demo stack is reachable instead of redirecting to a
  # listener that does not exist.
  dynamic "default_action" {
    for_each = var.certificate_arn == "" ? [1] : []
    content {
      type             = "forward"
      target_group_arn = local.http_default_tg
    }
  }

  dynamic "default_action" {
    for_each = var.certificate_arn == "" ? [] : [1]
    content {
      type = "redirect"
      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count             = var.certificate_arn == "" ? 0 : 1
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = local.http_default_tg
  }
}

# ---- IAM -------------------------------------------------------------------

resource "aws_iam_role" "task_execution" {
  name = "${var.project}-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_read_secrets" {
  name = "read-repomate-secrets"
  role = aws_iam_role.task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = concat(
        [data.aws_secretsmanager_secret.ollama_key.arn],
        var.github_token_secret_name == "" ? [] : [data.aws_secretsmanager_secret.github_token[0].arn],
      )
    }]
  })
}

# ---- shared task definition fragments ----------------------------------------

locals {
  shared_env = [
    { name = "OLLAMA_BASE_URL", value = "https://ollama.com/v1" },
    { name = "OLLAMA_MODELS", value = "gemma4:31b,gpt-oss:120b" },
    { name = "OLLAMA_TIMEOUT_SECONDS", value = "240" },
    { name = "REPOMATE_SANDBOX_ENABLED", value = "1" },
    { name = "REPOMATE_MAX_RUN_SECONDS", value = "900" },
    { name = "REDIS_URL", value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379/0" },
    { name = "ALLOWED_ORIGINS", value = var.allowed_origins },
  ]
  secrets = concat(
    [{ name = "OLLAMA_API_KEY", valueFrom = data.aws_secretsmanager_secret.ollama_key.arn }],
    # Unauthenticated clones are all public repositories need, so an absent
    # token is a supported configuration rather than a missing secret.
    var.github_token_secret_name == "" ? [] : [
      { name = "GITHUB_TOKEN", valueFrom = data.aws_secretsmanager_secret.github_token[0].arn },
    ],
  )
}

# ---- API service: task definition, service, autoscaling ---------------------

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([{
    name         = "api"
    image        = var.image_api
    essential    = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    mountPoints  = [{ sourceVolume = "runs", containerPath = "/var/lib/repomate" }]
    environment = concat(local.shared_env, [
      { name = "REPOMATE_EXECUTION", value = "celery" },
      { name = "REPOMATE_RUNS_ROOT", value = "/var/lib/repomate/runs" },
    ])
    secrets = concat(local.secrets, var.database_url == "" ? [] : [
      { name = "REPOMATE_DATABASE_URL", value = var.database_url }
    ])

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.main.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "api"
      }
    }
  }])

  volume {
    name = "runs"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.runs.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.runs.id
        iam             = "DISABLED"
      }
    }
  }
}

resource "aws_ecs_service" "api" {
  name            = "${var.project}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.public.ids
    security_groups  = [aws_security_group.services.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  health_check_grace_period_seconds = 30

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # Mount targets and Redis must exist before tasks start (tasks retry, but
  # this avoids a noisy first boot).
  depends_on = [
    aws_efs_mount_target.runs,
    aws_elasticache_cluster.redis,
    aws_lb_listener.http,
  ]
}

# Autoscaling: target tracking on CPU, plus ALB requests-per-target.
resource "aws_appautoscaling_target" "api" {
  max_capacity       = 8
  min_capacity       = 1
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${var.project}-api-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.api_cpu_target
    scale_in_cooldown  = 120
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_policy" "api_requests" {
  name               = "${var.project}-api-req"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 500 # requests per target, per minute
    scale_in_cooldown  = 120
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      # AWS wants the ARN suffixes joined with "/", not the full ARNs.
      resource_label = "${aws_lb.api.arn_suffix}/${aws_lb_target_group.api.arn_suffix}"
    }
  }
}

# ---- Worker service (Celery; scales with queue depth) -----------------------

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([{
    name        = "worker"
    image       = var.image_worker
    essential   = true
    command     = ["python", "-m", "services.worker"]
    mountPoints = [{ sourceVolume = "runs", containerPath = "/var/lib/repomate" }]
    environment = concat(local.shared_env, [
      { name = "REPOMATE_WORKER_CONCURRENCY", value = "2" },
      { name = "REPOMATE_RUNS_ROOT", value = "/var/lib/repomate/runs" },
    ])
    secrets = concat(local.secrets, var.database_url == "" ? [] : [
      { name = "REPOMATE_DATABASE_URL", value = var.database_url }
    ])

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.main.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "worker"
      }
    }
  }])

  volume {
    name = "runs"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.runs.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.runs.id
        iam             = "DISABLED"
      }
    }
  }
}

resource "aws_ecs_service" "worker" {
  name            = "${var.project}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.public.ids
    security_groups  = [aws_security_group.services.id]
    assign_public_ip = true
  }

  # Workers have no ALB; ECS restarts tasks that exit non-zero, and
  # acks-late requeues their in-flight runs.
  depends_on = [
    aws_efs_mount_target.runs,
    aws_elasticache_cluster.redis,
  ]
}

# ---- Frontend service (Next.js server; talks to the API through the ALB) ----
#
# NEXT_PUBLIC_API_URL is empty on purpose: the bundle then uses relative /api/*
# paths, which the same ALB resolves, so there is no cross-origin call to make
# and no mixed-content risk.

resource "aws_ecs_task_definition" "web" {
  count                    = local.web_enabled ? 1 : 0
  family                   = "${var.project}-web"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([{
    name         = "web"
    image        = var.image_web
    essential    = true
    portMappings = [{ containerPort = 3000, protocol = "tcp" }]
    environment = [
      { name = "NEXT_PUBLIC_API_URL", value = "" },
      { name = "PORT", value = "3000" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.main.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "web"
      }
    }
  }])
}

resource "aws_ecs_service" "web" {
  count           = local.web_enabled ? 1 : 0
  name            = "${var.project}-web"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.web[0].arn
  desired_count   = var.web_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.public.ids
    security_groups  = [aws_security_group.services.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web[0].arn
    container_name   = "web"
    container_port   = 3000
  }

  health_check_grace_period_seconds = 30

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # The /api/* rule has to exist before the web service claims the listener
  # default action, otherwise a first boot would route everything to Next.js.
  depends_on = [aws_lb_listener_rule.api, aws_lb_listener.http]
}

# ---- observability ------------------------------------------------------------

resource "aws_cloudwatch_log_group" "main" {
  name              = "/ecs/${var.project}"
  retention_in_days = 30
}

output "api_url" {
  value = var.certificate_arn == "" ? "http://${aws_lb.api.dns_name}" : "https://${aws_lb.api.dns_name}"
}

output "web_url" {
  description = "Frontend origin (same ALB; only when image_web is set)"
  value       = local.web_enabled ? (var.certificate_arn == "" ? "http://${aws_lb.api.dns_name}" : "https://${aws_lb.api.dns_name}") : null
}

output "redis_endpoint" {
  value = aws_elasticache_cluster.redis.cache_nodes[0].address
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}
