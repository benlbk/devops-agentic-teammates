# ---------------------------------------------------------------------------------------------------------------------
# IRSA MODULE - IAM Roles for EKS Service Accounts
# Creates OIDC-federated IAM roles bound to Kubernetes service accounts
# ---------------------------------------------------------------------------------------------------------------------

variable "project_name" {
  type = string
}
variable "environment" {
  type = string
}
variable "tags" {
  type    = map(string)
  default = {}
}

variable "cluster_oidc_issuer_url" {
  description = "OIDC issuer URL from EKS cluster"
  type        = string
}

variable "roles" {
  description = "Map of IRSA role definitions"
  type = map(object({
    namespace       = string
    service_account = string
    policy_arns     = list(string)
    role_name       = optional(string)
  }))
  default = {}
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  oidc_provider = replace(var.cluster_oidc_issuer_url, "https://", "")
  account_id    = data.aws_caller_identity.current.account_id
}

resource "aws_iam_role" "irsa" {
  for_each = var.roles

  name = coalesce(each.value.role_name, "${var.project_name}-${var.environment}-${each.key}")

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = "arn:${data.aws_partition.current.partition}:iam::${local.account_id}:oidc-provider/${local.oidc_provider}"
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.oidc_provider}:sub" = "system:serviceaccount:${each.value.namespace}:${each.value.service_account}"
          "${local.oidc_provider}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })

  tags = merge(var.tags, { ServiceAccount = "${each.value.namespace}/${each.value.service_account}" })
}

resource "aws_iam_role_policy_attachment" "irsa" {
  for_each = { for pair in flatten([
    for role_key, role in var.roles : [
      for idx, arn in role.policy_arns : {
        key        = "${role_key}-${idx}"
        role_name  = aws_iam_role.irsa[role_key].name
        policy_arn = arn
      }
    ]
  ]) : pair.key => pair }

  role       = each.value.role_name
  policy_arn = each.value.policy_arn
}

output "role_arns" {
  description = "Map of role name to ARN"
  value       = { for k, v in aws_iam_role.irsa : k => v.arn }
}
