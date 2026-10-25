# RepoMate on AWS ECS Fargate — autoscaling + self-healing.
#
# Topology:
#   ALB (health: GET /api/health) -> ECS "api" service (Fargate, 0.5 vCPU/1GB)
#   ECS "worker" service (Celery)  <- Redis (ElastiCache or the dev container)
#   Secrets (OPENAI_API_KEY, GITHUB_TOKEN) via AWS Secrets Manager — never in tfvars
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

data "aws_secretsmanager_secret" "openai_key" {
  name = "${var.project}/openai-api-key"
}

data "aws_secretsmanager_secret" "github_token" {
  name = "${var.project}/github-token"
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

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
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

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
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
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [
        data.aws_secretsmanager_secret.openai_key.arn,
        data.aws_secretsmanager_secret.github_token.arn,
      ]
    }]
  })
}

# ---- shared task definition fragments ----------------------------------------

locals {
  shared_env = [
    { name = "OPENAI_BASE_URL", value = "https://vyceai.com/v1" },
    { name = "OPENAI_MODEL", value = "deepseek-v4.1" },
    { name = "OPENAI_TIMEOUT_SECONDS", value = "240" },
    { name = "REPOMATE_SANDBOX_ENABLED", value = "1" },
    { name = "REPOMATE_MAX_RUN_SECONDS", value = "900" },
    { name = "REDIS_URL", value = "redis://redis:6379/0" },
    { name = "ALLOWED_ORIGINS", value = var.allowed_origins },
  ]
  secrets = [
    { name = "OPENAI_API_KEY", valueFrom = data.aws_secretsmanager_secret.openai_key.arn },
    { name = "GITHUB_TOKEN", valueFrom = data.aws_secretsmanager_secret.github_token.arn },
  ]
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
    environment = concat(local.shared_env, [
      { name = "REPOMATE_EXECUTION", value = "celery" },
      { name = "REPOMATE_RUNS_ROOT", value = "/var/lib/repomate" },
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
      resource_label         = "${aws_lb.api.arn}/${aws_lb_target_group.api.arn}"
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
    name      = "worker"
    image     = var.image_worker
    essential = true
    command   = ["python", "-m", "services.worker"]
    environment = concat(local.shared_env, [
      { name = "REPOMATE_WORKER_CONCURRENCY", value = "2" },
      { name = "REPOMATE_RUNS_ROOT", value = "/var/lib/repomate" },
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
}

# ---- observability ------------------------------------------------------------

resource "aws_cloudwatch_log_group" "main" {
  name              = "/ecs/${var.project}"
  retention_in_days = 30
}

output "api_url" {
  value = "http://${aws_lb.api.dns_name}" # point HTTPS/ACM at this in production
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}
