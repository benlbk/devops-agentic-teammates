# ---------------------------------------------------------------------------------------------------------------------
# ECR MODULE - Container Registries for agent and application images
# ---------------------------------------------------------------------------------------------------------------------

variable "project_name" { type = string }
variable "environment" { type = string }
variable "tags" { type = map(string); default = {} }

variable "repositories" {
  description = "List of ECR repository names to create"
  type        = list(string)
  default = [
    "agent-orchestrator",
    "agent-plan-collaborate",
    "agent-code-build",
    "agent-test-secure",
    "agent-release-deploy",
    "agent-operate-monitor",
    "app-frontend",
    "app-backend",
    "dashboard",
  ]
}

resource "aws_ecr_repository" "main" {
  for_each             = toset(var.repositories)
  name                 = "${var.project_name}/${each.value}"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-${each.value}"
  })
}

resource "aws_ecr_lifecycle_policy" "main" {
  for_each   = toset(var.repositories)
  repository = aws_ecr_repository.main[each.value].name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 20 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 20
        }
        action = { type = "expire" }
      }
    ]
  })
}

output "repository_urls" {
  value = { for k, v in aws_ecr_repository.main : k => v.repository_url }
}

output "repository_arns" {
  value = { for k, v in aws_ecr_repository.main : k => v.arn }
}
