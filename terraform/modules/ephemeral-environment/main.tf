# ---------------------------------------------------------------------------------------------------------------------
# EPHEMERAL ENVIRONMENT MODULE
# Provisions per-PR full-stack environments with cost guardrails
# ---------------------------------------------------------------------------------------------------------------------

variable "project_name" {
  type = string
}
variable "environment" { type = string
  default = "ephemeral"
}
variable "pr_number" {
  type = number
}
variable "cluster_name" {
  type = string
}
variable "vpc_id" {
  type = string
}
variable "private_subnet_ids" {
  type = list(string)
}
variable "db_subnet_group_name" {
  type = string
}
variable "ecr_frontend_url" {
  type = string
}
variable "ecr_backend_url" {
  type = string
}
variable "frontend_image_tag" {
  type = string
}
variable "backend_image_tag" {
  type = string
}
variable "base_domain" { type = string
  default = "dev.example.com"
}
variable "ttl_hours" {
  type    = number
  default = 48
}
variable "max_cost_per_day" {
  type    = number
  default = 50
}
variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  namespace = "pr-${var.pr_number}"
  env_tags = merge(var.tags, {
    EphemeralEnv = "true"
    PRNumber     = tostring(var.pr_number)
    TTLHours     = tostring(var.ttl_hours)
    ExpiresAt    = timeadd(timestamp(), "${var.ttl_hours}h")
  })
}

# Kubernetes namespace
resource "kubernetes_namespace" "pr" {
  metadata {
    name = local.namespace
    labels = {
      "app.kubernetes.io/managed-by" = "devops-agentic-teammates"
      "ephemeral"                    = "true"
      "pr-number"                    = tostring(var.pr_number)
    }
    annotations = {
      "expires-at" = timeadd(timestamp(), "${var.ttl_hours}h")
    }
  }
}

# Resource quota to enforce cost guardrails
resource "kubernetes_resource_quota" "pr" {
  metadata {
    name      = "resource-quota"
    namespace = kubernetes_namespace.pr.metadata[0].name
  }

  spec {
    hard = {
      "requests.cpu"    = "4"
      "requests.memory" = "8Gi"
      "limits.cpu"      = "8"
      "limits.memory"   = "16Gi"
      "pods"            = "20"
    }
  }
}

# PostgreSQL for PR environment (using a lightweight container)
resource "kubernetes_deployment" "postgres" {
  metadata {
    name      = "postgres"
    namespace = kubernetes_namespace.pr.metadata[0].name
  }

  spec {
    replicas = 1
    selector {
      match_labels = { app = "postgres" }
    }

    template {
      metadata {
        labels = { app = "postgres" }
      }

      spec {
        container {
          name  = "postgres"
          image = "postgres:15-alpine"

          port {
            container_port = 5432
          }

          env {
            name  = "POSTGRES_DB"
            value = "appdb"
          }
          env {
            name  = "POSTGRES_USER"
            value = "dbadmin"
          }
          env {
            name = "POSTGRES_PASSWORD"
            value_from {
              secret_key_ref {
                name = "db-credentials"
                key  = "password"
              }
            }
          }

          resources {
            requests = {
              cpu    = "250m"
              memory = "512Mi"
            }
            limits = {
              cpu    = "500m"
              memory = "1Gi"
            }
          }

          volume_mount {
            name       = "pgdata"
            mount_path = "/var/lib/postgresql/data"
          }
        }

        volume {
          name = "pgdata"
          empty_dir {}
        }
      }
    }
  }
}

resource "kubernetes_service" "postgres" {
  metadata {
    name      = "postgres"
    namespace = kubernetes_namespace.pr.metadata[0].name
  }

  spec {
    selector = { app = "postgres" }
    port {
      port        = 5432
      target_port = 5432
    }
  }
}

resource "kubernetes_secret" "db_credentials" {
  metadata {
    name      = "db-credentials"
    namespace = kubernetes_namespace.pr.metadata[0].name
  }

  data = {
    password = "ephemeral-${var.pr_number}-${substr(sha256("${var.pr_number}-${timestamp()}"), 0, 16)}"
  }
}

# Backend deployment
resource "helm_release" "backend" {
  name       = "backend"
  namespace  = kubernetes_namespace.pr.metadata[0].name
  chart      = "${path.module}/../../helm/app-backend"

  set {
    name  = "image.repository"
    value = var.ecr_backend_url
  }
  set {
    name  = "image.tag"
    value = var.backend_image_tag
  }
  set {
    name  = "env.DATABASE_HOST"
    value = "postgres"
  }
  set {
    name  = "env.DATABASE_NAME"
    value = "appdb"
  }
  set {
    name  = "env.ASPNETCORE_ENVIRONMENT"
    value = "Development"
  }
  set {
    name  = "ingress.enabled"
    value = "true"
  }
  set {
    name  = "ingress.host"
    value = "api-pr-${var.pr_number}.${var.base_domain}"
  }

  depends_on = [kubernetes_deployment.postgres]
}

# Frontend deployment
resource "helm_release" "frontend" {
  name       = "frontend"
  namespace  = kubernetes_namespace.pr.metadata[0].name
  chart      = "${path.module}/../../helm/app-frontend"

  set {
    name  = "image.repository"
    value = var.ecr_frontend_url
  }
  set {
    name  = "image.tag"
    value = var.frontend_image_tag
  }
  set {
    name  = "env.NEXT_PUBLIC_API_URL"
    value = "https://api-pr-${var.pr_number}.${var.base_domain}"
  }
  set {
    name  = "ingress.enabled"
    value = "true"
  }
  set {
    name  = "ingress.host"
    value = "pr-${var.pr_number}.${var.base_domain}"
  }

  depends_on = [helm_release.backend]
}

output "frontend_url" { value = "https://pr-${var.pr_number}.${var.base_domain}" }
output "backend_url" { value = "https://api-pr-${var.pr_number}.${var.base_domain}" }
output "namespace" { value = local.namespace }
output "expires_at" { value = timeadd(timestamp(), "${var.ttl_hours}h") }
