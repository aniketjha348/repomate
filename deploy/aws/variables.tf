variable "aws_region" {
  description = "AWS region for the stack"
  type        = string
  default     = "ap-south-1"
}

variable "project" {
  description = "Name prefix for resources"
  type        = string
  default     = "repomate"
}

variable "image_api" {
  description = "ECR/image URI for the API service (build deploy/Dockerfile.api and push first)"
  type        = string
}

variable "image_worker" {
  description = "ECR/image URI for the worker service (deploy/Dockerfile.worker)"
  type        = string
}

variable "allowed_origins" {
  description = "CORS origins for the API (your frontend URL)"
  type        = string
  default     = "https://repomate.vercel.app"
}

variable "api_desired_count" {
  description = "Baseline API tasks"
  type        = number
  default     = 2
}

variable "worker_desired_count" {
  description = "Baseline worker tasks"
  type        = number
  default     = 1
}

variable "api_cpu_target" {
  description = "Target-tracking CPU utilization for API autoscaling"
  type        = number
  default     = 60
}

variable "database_url" {
  description = "PostgreSQL URL for the SQL run store (empty = file store on the shared EFS volume)"
  type        = string
  default     = ""
}

variable "certificate_arn" {
  description = "ACM certificate ARN for the ALB HTTPS listener (empty = HTTP only, demo use)"
  type        = string
  default     = ""
}

variable "github_token_secret_name" {
  description = "Secrets Manager name holding a GitHub token (empty = unauthenticated clones, which is enough for public repositories)"
  type        = string
  default     = ""
}
